"""datastore: is the ArcGIS Data Store behind the hosting server healthy and backed up?

Runs against the hosting ArcGIS Server's Administrator API. ``gather`` finds the managed
data stores (``data/findItems``) and calls the documented ``validate`` operation for each;
``evaluate`` is pure. One validate call describes every machine in that data store, so
one machine name per store is enough (ADR 0005 covers where the name comes from).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .findings import Finding, Severity


@dataclass(frozen=True)
class Thresholds:
    backup_warn_days: float = 7.0


DEFAULTS = Thresholds()


@dataclass(frozen=True)
class DsMachine:
    name: str
    role: str | None  # PRIMARY | STANDBY | CLUSTER_MEMBER
    reachable: bool | None
    status: str | None  # Started | Stopped
    health: str | None  # Healthy | ...
    accepting: bool | None

    @property
    def ok(self) -> bool:
        return (
            self.reachable is not False
            and (self.status or "Started") == "Started"
            and (self.health or "Healthy") == "Healthy"
            and self.accepting is not False
        )


@dataclass(frozen=True)
class DataStoreHealth:
    path: str
    kind: str  # relational | tileCache | spatiotemporal
    name: str
    overall: str | None
    registered: bool | None = None
    server_connection: bool | None = None
    machines: tuple[DsMachine, ...] = ()
    unavailable: tuple[str, ...] = ()
    last_backup: datetime | None = None
    backup_reported: bool = False  # the response carried datastore.lastbackup
    release: str | None = None
    cluster_status: str | None = None  # spatiotemporal: GREEN | YELLOW | RED
    unassigned_shards: int | None = None


@dataclass
class DataStoreSnapshot:
    base_url: str
    stores: list[DataStoreHealth] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------- parsing


def _bool(v) -> bool | None:
    if v is None:
        return None
    return v is True or str(v).lower() == "true"


def _when(v) -> datetime | None:
    """Epoch milliseconds as documented; seconds accepted too (ADR 0004). -1 means never."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, tz=UTC)


def _kind(path: str, payload: dict) -> str:
    if "clusterStatus" in payload or "/nosqlDatabases/AGSDataStore_bigdata" in path:
        return "spatiotemporal"
    if path.startswith("/nosqlDatabases/"):
        return "tileCache"
    return "relational"


def parse_validation(path: str, payload: dict) -> DataStoreHealth:
    machines = tuple(
        DsMachine(
            m.get("name", "?"),
            m.get("role"),
            _bool(m.get("machine.isReachable")),
            m.get("status"),
            m.get("machine.overallhealth"),
            _bool(m.get("db.isAccepting")),
        )
        for m in payload.get("machines", [])
    )
    unavailable = tuple(payload.get("unavailableMachines") or payload.get("unavailableNodes") or ())
    shards = payload.get("unassigned_shards")
    return DataStoreHealth(
        path=path,
        kind=_kind(path, payload),
        name=payload.get("datastore.name") or path.rsplit("/", 1)[-1],
        overall=payload.get("datastore.overallhealth"),
        registered=_bool(payload.get("datastore.isRegistered")),
        server_connection=_bool(payload.get("datastore.hasValidServerConnection")),
        machines=machines,
        unavailable=unavailable,
        last_backup=_when(payload.get("datastore.lastbackup")),
        backup_reported="datastore.lastbackup" in payload,
        release=payload.get("datastore.release"),
        cluster_status=payload.get("clusterStatus"),
        unassigned_shards=int(shards) if shards is not None else None,
    )


def managed_items(payload: dict) -> list[dict]:
    """Data items ArcGIS Data Store manages for the server (``isManaged``)."""
    return [i for i in payload.get("items", []) if _bool((i.get("info") or {}).get("isManaged"))]


def machine_for(item: dict, override: str | None) -> str | None:
    if override:
        return override
    for m in (item.get("info") or {}).get("machines") or []:
        if isinstance(m, dict) and m.get("name"):
            return m["name"]
    return None


# --------------------------------------------------------------- gathering


def gather(admin, *, machine: str | None = None) -> DataStoreSnapshot:
    snap = DataStoreSnapshot(admin.base)
    items: list[dict] = []
    try:
        items += managed_items(
            admin.call("data/findItems", parentPath="/enterpriseDatabases", types="egdb")
        )
    except Exception as e:  # noqa: BLE001 - reported as a finding
        snap.errors.append(f"find relational data stores: {e}")
    try:
        nosql = admin.call("data/findItems", parentPath="/nosqlDatabases")
        items += [
            i
            for i in nosql.get("items", [])
            if str(i.get("path", "")).startswith("/nosqlDatabases/")
        ]
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"find tile cache and spatiotemporal data stores: {e}")
    for item in items:
        path = item.get("path", "?")
        name = machine_for(item, machine)
        if not name:
            snap.errors.append(
                f"{path}: no data store machine name in the item; pass --machine to validate it"
            )
            continue
        try:
            payload = admin.call(f"data/items{path}/machines/{name}/validate")
            snap.stores.append(parse_validation(path, payload))
        except Exception as e:  # noqa: BLE001
            snap.errors.append(f"validate {path} on {name}: {e}")
    return snap


# --------------------------------------------------------------- evaluating

_LABEL = {"relational": "Relational", "tileCache": "Tile cache", "spatiotemporal": "Spatiotemporal"}


def evaluate(s: DataStoreSnapshot, now: datetime, t: Thresholds = DEFAULTS) -> list[Finding]:
    out: list[Finding] = []
    if not s.stores and not s.errors:
        out.append(
            Finding(
                "DST000",
                Severity.WARN,
                "No ArcGIS Data Store is registered with this server",
                "A hosting server needs a relational data store for hosted feature layers. "
                "Configure ArcGIS Data Store against this server, or point egisops at the "
                "hosting server.",
            )
        )
    elif s.stores:
        kinds = ", ".join(sorted({_LABEL[x.kind].lower() for x in s.stores}))
        out.append(
            Finding("DST000", Severity.OK, f"{len(s.stores)} data store(s) validated ({kinds})")
        )

    for d in s.stores:
        label = f"{_LABEL[d.kind]} data store {d.name}"

        # DST001 overall health as the data store reports it
        if d.overall and d.overall != "Healthy":
            out.append(
                Finding(
                    "DST001",
                    Severity.FAIL,
                    f"{label} reports {d.overall}",
                    "Check the machines below and the data store logs on each machine.",
                    {"path": d.path},
                )
            )

        # DST002 machines. The summary can say Healthy while a machine is listed as
        # unavailable (Esri's own tile cache example does), so the lists are read too.
        bad = [m for m in d.machines if not m.ok]
        total = len(d.machines) + len(d.unavailable)
        for m in bad:
            primary = (m.role or "").upper() == "PRIMARY" or len(d.machines) == 1
            why = []
            if m.reachable is False:
                why.append("not reachable")
            if m.status and m.status != "Started":
                why.append(f"status {m.status}")
            if m.health and m.health != "Healthy":
                why.append(f"health {m.health}")
            if m.accepting is False:
                why.append("database not accepting connections")
            out.append(
                Finding(
                    "DST002",
                    Severity.FAIL if primary else Severity.WARN,
                    f"{label}: machine {m.name} ({m.role or 'member'}) is {', '.join(why)}",
                    "Hosted layers stop working when the primary is down. Start the ArcGIS Data "
                    "Store service on the machine and validate again."
                    if primary
                    else "The data store is running without this machine. Start the ArcGIS Data "
                    "Store service on it and validate again.",
                    {"path": d.path, "machine": m.name, "role": m.role},
                )
            )
        if d.unavailable:
            all_gone = not [m for m in d.machines if m.ok]
            out.append(
                Finding(
                    "DST002",
                    Severity.FAIL if all_gone else Severity.WARN,
                    f"{label}: {len(d.unavailable)} of {total} machine(s) unavailable",
                    ", ".join(d.unavailable)
                    + ". The data store answered without them. Check the machines and the "
                    "ArcGIS Data Store service on each.",
                    {"path": d.path, "unavailable": list(d.unavailable)},
                )
            )

        # DST003 standby for the relational store
        if d.kind == "relational" and len(d.machines) == 1 and not d.unavailable:
            out.append(
                Finding(
                    "DST003",
                    Severity.INFO,
                    f"{label} has no standby machine",
                    "If its machine fails, hosted feature layers are down until it is restored "
                    "from backup. A standby machine takes over on its own.",
                    {"path": d.path},
                )
            )

        # DST004 registration and the server connection
        if d.registered is False or d.server_connection is False:
            out.append(
                Finding(
                    "DST004",
                    Severity.FAIL,
                    f"{label} "
                    + (
                        "is not registered with the server"
                        if d.registered is False
                        else "has no valid connection to the server"
                    ),
                    "Hosted layers cannot reach their data. Run the Data Store configuration "
                    "against this server again, then validate.",
                    {"path": d.path},
                )
            )

        # DST005 newest backup (relational stores report it)
        if d.backup_reported:
            if d.last_backup is None:
                out.append(
                    Finding(
                        "DST005",
                        Severity.WARN,
                        f"{label}: no backup recorded",
                        "Check the backup schedule and location with the describedatastore and "
                        "configurebackuplocation utilities on the data store machine.",
                        {"path": d.path},
                    )
                )
            else:
                age = (now - d.last_backup).total_seconds() / 86400
                sev = Severity.WARN if age > t.backup_warn_days else Severity.OK
                out.append(
                    Finding(
                        "DST005",
                        sev,
                        f"{label}: newest backup {age:.1f} days old",
                        ""
                        if sev == Severity.OK
                        else f"Older than the {t.backup_warn_days:g}-day target. Check that "
                        "scheduled backups are on and the backup location has space.",
                        {"path": d.path, "last_backup": d.last_backup.isoformat()},
                    )
                )

        # DST006 spatiotemporal cluster
        if d.kind == "spatiotemporal" and d.cluster_status:
            cs = d.cluster_status.upper()
            sev = {"GREEN": Severity.OK, "YELLOW": Severity.WARN}.get(cs, Severity.FAIL)
            if d.unassigned_shards and sev == Severity.OK:
                sev = Severity.WARN
            out.append(
                Finding(
                    "DST006",
                    sev,
                    f"{label}: cluster {cs}"
                    + (
                        f", {d.unassigned_shards} unassigned shard(s)"
                        if d.unassigned_shards
                        else ""
                    ),
                    ""
                    if sev == Severity.OK
                    else "Some data has no copy on a running node. Bring the missing nodes back "
                    "before the cluster loses more.",
                    {"path": d.path, "clusterStatus": cs},
                )
            )

    for e in s.errors:
        out.append(Finding("DST009", Severity.WARN, "Part of the check could not run", e))
    return out

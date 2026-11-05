"""portal-health: is Portal for ArcGIS up, licensed, federated and searchable?

``gather`` reads the Portal Administrator API (and the TLS handshake); ``evaluate`` is
pure. Response shapes follow Esri's documented examples, linked in
tests/fixtures/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .findings import Finding, Severity
from .server import (
    DEFAULTS as SERVER_DEFAULTS,
)
from .server import (
    TARGET_RELEASES,
    Certificate,
    certificate_findings,
)


@dataclass(frozen=True)
class Thresholds:
    license_warn_days: int = 30
    license_info_days: int = 90
    cert_fail_days: int = SERVER_DEFAULTS.cert_fail_days
    cert_warn_days: int = SERVER_DEFAULTS.cert_warn_days
    members_info_ratio: float = 0.9


DEFAULTS = Thresholds()


@dataclass(frozen=True)
class PortalMachine:
    name: str
    role: str | None  # primary | standby
    ready: bool | None  # None when the status call could not run
    reason: str = ""  # what the status call said when the machine is not ready


@dataclass(frozen=True)
class Entitlement:
    kind: str  # userType | appBundle | app | extension | portalCapability
    id: str
    expires: datetime | None
    current: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class FederatedServer:
    id: str
    name: str
    admin_url: str
    role: str  # HOSTING_SERVER | FEDERATED_SERVER
    function: str


@dataclass(frozen=True)
class ServerValidation:
    server_id: str
    status: str  # success | success with warnings | failure | undetermined
    messages: tuple[str, ...]
    admin_url: str | None = None


@dataclass(frozen=True)
class IndexCount:
    name: str
    database: int
    index: int


@dataclass
class PortalSnapshot:
    base_url: str
    health_status: int | None = None
    health_ok: bool | None = None
    version: str | None = None
    licensed: bool | None = None
    site_error: str | None = None  # the admin root answered with an error (not initialized)
    machines: list[PortalMachine] = field(default_factory=list)
    entitlements: list[Entitlement] = field(default_factory=list)
    members: tuple[int, int] | None = None  # (current, maximum)
    certificate: Certificate | None = None
    servers: list[FederatedServer] | None = None  # None when not read
    validation_status: str | None = None
    validations: list[ServerValidation] = field(default_factory=list)
    indexes: list[IndexCount] | None = None
    index_sync: bool | None = None
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------- parsing


def _ms(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _true(v) -> bool:
    return v is True or str(v).lower() == "true"


_ENTITLEMENT_KEYS = {
    "userTypes": "userType",
    "appBundles": "appBundle",
    "apps": "app",
    "extensions": "extension",
    "portalCapabilities": "portalCapability",
}


def parse_license(payload: dict) -> tuple[list[Entitlement], tuple[int, int] | None]:
    out = []
    for key, kind in _ENTITLEMENT_KEYS.items():
        for item in payload.get(key) or []:
            out.append(
                Entitlement(
                    kind,
                    str(item.get("id", "?")),
                    _ms(item.get("expiration")),
                    _int(item.get("currentRegisteredMembers")),
                    _int(item.get("maximumRegisteredMembers")),
                )
            )
    cur, mx = (
        _int(payload.get("currentRegisteredMembers")),
        _int(payload.get("maximumRegisteredMembers")),
    )
    return out, (cur, mx) if cur is not None and mx else None


def parse_servers(payload: dict) -> list[FederatedServer]:
    return [
        FederatedServer(
            s.get("id", "?"),
            s.get("name", "?"),
            s.get("adminUrl", ""),
            s.get("serverRole", "?"),
            s.get("serverFunction", "") or "",
        )
        for s in payload.get("servers", [])
    ]


def parse_validation(payload: dict) -> tuple[str | None, list[ServerValidation]]:
    return payload.get("status"), [
        ServerValidation(
            v.get("serverId", "?"),
            v.get("status", "undetermined"),
            tuple(v.get("messages") or ()),
            v.get("adminUrl"),
        )
        for v in payload.get("serversStatus", [])
    ]


def parse_indexer(payload: dict) -> tuple[list[IndexCount], bool | None]:
    idx = [
        IndexCount(
            i.get("name", "?"), _int(i.get("databaseCount")) or 0, _int(i.get("indexCount")) or 0
        )
        for i in payload.get("indexes", [])
    ]
    sync = payload.get("syncStatus")
    return idx, None if sync is None else _true(sync)


# --------------------------------------------------------------- gathering


def gather(portal, *, read_cert=None) -> PortalSnapshot:
    if read_cert is None:
        from .server import read_certificate as read_cert
    snap = PortalSnapshot(portal.base)
    try:
        status, body = portal.healthcheck()
        snap.health_status = status
        snap.health_ok = status == 200 and bool(body) and body.get("status") == "success"
    except Exception as e:  # noqa: BLE001 - each part is reported, not fatal
        snap.errors.append(f"health check: {e}")
    try:
        root = portal.call("")
        snap.version = str(root.get("currentbuild") or root.get("version") or "") or None
        if "isPortalLicensed" in root:
            snap.licensed = _true(root["isPortalLicensed"])
    except Exception as e:  # noqa: BLE001
        snap.site_error = str(e)
    if portal.token is None:
        snap.errors.append("not signed in: only the public health check ran")
    else:
        _gather_admin(portal, snap)
    try:
        snap.certificate = read_cert(portal.base)
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"certificate: {e}")
    return snap


def _gather_admin(portal, snap: PortalSnapshot) -> None:
    try:
        for m in portal.call("machines").get("machines", []):
            name = m.get("machineName", "?")
            try:
                st = portal.call(f"machines/status/{name}")
                snap.machines.append(
                    PortalMachine(name, m.get("role"), st.get("status") == "success")
                )
            except Exception as e:  # noqa: BLE001 - a failed status call is the answer
                snap.machines.append(PortalMachine(name, m.get("role"), False, str(e)))
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"machines: {e}")
    try:
        snap.entitlements, snap.members = parse_license(portal.call("license"))
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"license: {e}")
    try:
        snap.servers = parse_servers(portal.call("federation/servers"))
        if snap.servers:
            snap.validation_status, snap.validations = parse_validation(
                portal.call("federation/servers/validate")
            )
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"federation: {e}")
    try:
        snap.indexes, snap.index_sync = parse_indexer(portal.call("system/indexer/status"))
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"indexer: {e}")


# --------------------------------------------------------------- evaluating


def _days(until: datetime, now: datetime) -> float:
    return (until - now).total_seconds() / 86400


_STATUS_SEV = {
    "success": Severity.OK,
    "success with warnings": Severity.WARN,
    "failure": Severity.FAIL,
    "undetermined": Severity.WARN,
}


def evaluate(s: PortalSnapshot, now: datetime, t: Thresholds = DEFAULTS) -> list[Finding]:
    out: list[Finding] = []

    # PTL001 health check
    if s.health_ok:
        out.append(Finding("PTL001", Severity.OK, "Portal health check: success"))
    else:
        out.append(
            Finding(
                "PTL001",
                Severity.FAIL,
                "Portal health check failed"
                + (f" (HTTP {s.health_status})" if s.health_status else ""),
                "The portal machine that answered cannot take requests. Check the Portal for "
                "ArcGIS service on the host and the portal logs.",
                {"http_status": s.health_status},
            )
        )

    # PTL002 site and license
    if s.site_error:
        out.append(
            Finding(
                "PTL002",
                Severity.FAIL,
                "Portal site is not ready",
                f"The Portal Administrator root answered with an error: {s.site_error}",
            )
        )
    elif s.licensed is False:
        out.append(
            Finding(
                "PTL002",
                Severity.FAIL,
                "Portal is not licensed",
                "Import the portal license file from My Esri (portaladmin/license).",
            )
        )
    elif s.licensed:
        out.append(Finding("PTL002", Severity.OK, "Portal is licensed"))

    # PTL003 machines
    if s.machines:
        down = [m for m in s.machines if not m.ready]
        for m in s.machines:
            role = f" ({m.role})" if m.role else ""
            if m.ready:
                out.append(
                    Finding("PTL003", Severity.OK, f"Portal machine {m.name}{role} is ready")
                )
            else:
                out.append(
                    Finding(
                        "PTL003",
                        Severity.FAIL if len(down) == len(s.machines) else Severity.WARN,
                        f"Portal machine {m.name}{role} is not ready",
                        (f"{m.reason.split(': ', 1)[-1].rstrip('.')}. " if m.reason else "")
                        + "The machine status call did not return success. "
                        + (
                            "No portal machine can take requests."
                            if len(down) == len(s.machines)
                            else "The site is running on its other machine, without a standby."
                        ),
                        {"machine": m.name, "role": m.role},
                    )
                )
        if len(s.machines) == 1 and not down:
            out.append(
                Finding(
                    "PTL003",
                    Severity.INFO,
                    "Single portal machine, no standby",
                    "If this machine fails, the portal is down until it is restored. A second "
                    "machine in a highly available deployment takes over on its own.",
                )
            )

    # PTL004 entitlement expiry, PTL005 member capacity
    dated = [e for e in s.entitlements if e.expires]
    if dated:
        soonest = min(dated, key=lambda e: e.expires)
        days = _days(soonest.expires, now)
        sev = (
            Severity.FAIL
            if days < 0
            else Severity.WARN
            if days < t.license_warn_days
            else Severity.INFO
            if days < t.license_info_days
            else Severity.OK
        )
        out.append(
            Finding(
                "PTL004",
                sev,
                f"Portal license {soonest.kind} {soonest.id} "
                + (
                    f"expired {abs(days):.0f} days ago"
                    if days < 0
                    else f"expires in {days:.0f} days"
                ),
                ""
                if sev == Severity.OK
                else "Get the renewed portal license from My Esri and import it before then; "
                "members with an expired user type lose access.",
                {"id": soonest.id, "expires": soonest.expires.isoformat()},
            )
        )
    if s.members:
        cur, mx = s.members
        ratio = cur / mx
        sev = (
            Severity.WARN
            if cur >= mx
            else Severity.INFO
            if ratio >= t.members_info_ratio
            else Severity.OK
        )
        out.append(
            Finding(
                "PTL005",
                sev,
                f"{cur} of {mx} member licenses in use",
                ""
                if sev == Severity.OK
                else "New members cannot be added once every license is assigned. Remove "
                "inactive members or add user type licenses.",
                {"current": cur, "maximum": mx},
            )
        )
    full = [
        e
        for e in s.entitlements
        if e.kind == "userType" and e.maximum and e.current is not None and e.current >= e.maximum
    ]
    for e in full:
        out.append(
            Finding(
                "PTL005",
                Severity.WARN,
                f"User type {e.id}: all {e.maximum} licenses assigned",
                "No new member can get this user type until one is freed or more are licensed.",
                {"userType": e.id, "current": e.current, "maximum": e.maximum},
            )
        )

    # PTL006 / PTL007 certificate
    out += certificate_findings(s.certificate, now, t, "PTL006", "PTL007")

    # PTL008 federation
    if s.servers is not None:
        names = {x.id: x for x in s.servers}
        hosting = [x for x in s.servers if x.role == "HOSTING_SERVER"]
        if not s.servers:
            out.append(
                Finding(
                    "PTL008",
                    Severity.WARN,
                    "No ArcGIS Server is federated with this portal",
                    "A base deployment federates one ArcGIS Server and makes it the hosting "
                    "server. Without it, members cannot publish hosted layers.",
                )
            )
        elif not hosting:
            out.append(
                Finding(
                    "PTL008",
                    Severity.WARN,
                    "No hosting server is designated",
                    "Members cannot publish hosted feature layers. Set the federated server "
                    "that has ArcGIS Data Store registered as the hosting server.",
                )
            )
        bad = 0
        for v in s.validations:
            sev = _STATUS_SEV.get(v.status, Severity.WARN)
            if sev == Severity.OK:
                continue
            bad += 1
            srv = names.get(v.server_id)
            label = srv.name if srv else v.server_id
            role = " (hosting server)" if srv and srv.role == "HOSTING_SERVER" else ""
            out.append(
                Finding(
                    "PTL008",
                    sev,
                    f"Federated server {label}{role}: validation {v.status}",
                    "\n".join(v.messages[-4:])
                    or "No messages returned. Open portaladmin/federation/servers/validate.",
                    {
                        "serverId": v.server_id,
                        "adminUrl": v.admin_url or (srv.admin_url if srv else None),
                    },
                )
            )
        if s.validations and not bad:
            out.append(
                Finding(
                    "PTL008",
                    Severity.OK,
                    f"{len(s.validations)} federated server(s) validated"
                    + (f", hosting server {hosting[0].name}" if hosting else ""),
                )
            )

    # PTL009 search index
    if s.indexes is not None:
        off = [i for i in s.indexes if i.database != i.index]
        if off or s.index_sync is False:
            out.append(
                Finding(
                    "PTL009",
                    Severity.WARN,
                    "Search index does not match the portal content",
                    "; ".join(f"{i.name}: {i.database} stored, {i.index} indexed" for i in off)
                    + ". Members will not find some content. If indexing is not running, "
                    "reindex from portaladmin/system/indexer/reindex.",
                    {"indexes": [i.__dict__ for i in off], "syncStatus": s.index_sync},
                )
            )
        elif s.indexes:
            out.append(Finding("PTL009", Severity.OK, "Search index matches the portal content"))

    # PTL010 version
    if s.version:
        mm = ".".join(s.version.split(".")[:2])
        if mm in TARGET_RELEASES:
            out.append(Finding("PTL010", Severity.OK, f"Portal for ArcGIS {s.version}"))
        else:
            out.append(
                Finding(
                    "PTL010",
                    Severity.INFO,
                    f"Portal for ArcGIS {s.version} is outside the tested releases",
                    f"egisops is written against {', '.join(TARGET_RELEASES)}.",
                )
            )

    for e in s.errors:
        out.append(Finding("PTL000", Severity.WARN, "Part of the check could not run", e))
    return out

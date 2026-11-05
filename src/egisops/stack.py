"""stack-compat: do the pieces of this ArcGIS Enterprise stack belong together?

Checks that Portal, the hosting server and ArcGIS Data Store run the same release, that the
RDS for PostgreSQL geodatabase is supported by that release, that ArcGIS Pro is the
companion version, and, with ``--target``, what an upgrade involves.

The database side is not duplicated here. It is rdsops ``compat.check`` with rdsops's own
dated Esri support matrix (ADR 0007). Without rdsops installed, that part reports STK009
and the rest still runs. ``evaluate`` is pure; the rdsops check is passed in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .findings import Finding, Severity

# Esri, "Upgrade ArcGIS Enterprise": latest target supported for a direct upgrade.
DIRECT_UPGRADE = (
    ((11, 0), (12, 0), "12.1"),
    ((10, 8), (10, 9, 1), "11.5"),
    ((10, 7), (10, 7, 1), "11.3"),
    ((10, 5), (10, 6, 1), "10.9.1"),
)
UPGRADE_ORDER = (
    "Portal for ArcGIS",
    "Web Adaptor for Portal",
    "the hosting server",
    "Web Adaptor for ArcGIS Server",
    "ArcGIS Data Store",
    "other federated servers",
)
RETIRED_AT_12 = (
    "ArcGIS Web AppBuilder, ArcGIS Configurable Apps, Map Viewer Classic, the tile cache data "
    "store, ArcGIS Insights and other features were retired at 12.0"
)


def vtuple(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def release(v: str | None) -> str | None:
    """'11.5.0.12345' -> '11.5'; '10.9.1' stays '10.9.1' (Esri names that release)."""
    if not v:
        return None
    t = vtuple(v)
    if len(t) >= 3 and t[:2] in ((10, 9), (10, 7), (10, 6), (10, 8)) and t[2]:
        return ".".join(map(str, t[:3]))
    return ".".join(map(str, t[:2])) if len(t) >= 2 else None


@dataclass(frozen=True)
class Component:
    name: str  # "Portal for ArcGIS", "ArcGIS Server", "ArcGIS Data Store (ds_x)"
    version: str


@dataclass
class StackSnapshot:
    components: list[Component] = field(default_factory=list)
    engine_version: str | None = None  # RDS for PostgreSQL
    postgis_version: str | None = None
    pro_version: str | None = None
    target: str | None = None  # an ArcGIS Enterprise release to plan an upgrade to
    errors: list[str] = field(default_factory=list)


# rdsops pieces, looked up at run time so the evaluator stays importable without rdsops.
DbCheck = Callable[[str, str, str | None], list]
ProFor = Callable[[str], str | None]


def rdsops_hooks() -> tuple[DbCheck | None, ProFor | None]:
    try:
        from rdsops import compat
    except ImportError:
        return None, None

    def pro_for(rel: str) -> str | None:
        for r in compat.load_matrix():
            if r.enterprise == rel:
                return r.pro
        return None

    def db_check(engine: str, rel: str, postgis: str | None) -> list[Finding]:
        return [
            Finding(f.code, Severity(int(f.severity)), f.title, f.detail, dict(f.evidence))
            for f in compat.check(engine, rel, postgis)
        ]

    return db_check, pro_for


# --------------------------------------------------------------- gathering


def gather(admin=None, *, portal_version=None, server_version=None, datastores=None, **db):
    """Server version from the admin root unless given; Data Store releases from the
    datastore check's validate calls unless given."""
    snap = StackSnapshot(
        engine_version=db.get("engine_version"),
        postgis_version=db.get("postgis_version"),
        pro_version=db.get("pro_version"),
        target=db.get("target"),
    )
    if portal_version:
        snap.components.append(Component("Portal for ArcGIS", portal_version))
    if server_version is None and admin is not None:
        try:
            root = admin.call("")
            server_version = str(root.get("fullVersion") or root.get("currentVersion") or "")
        except Exception as e:  # noqa: BLE001 - reported as a finding
            snap.errors.append(f"admin root: {e}")
    if server_version:
        snap.components.append(Component("ArcGIS Server (hosting)", server_version))
    if datastores is None and admin is not None:
        from . import datastore

        ds = datastore.gather(admin, machine=db.get("machine"))
        datastores = [(d.name, d.release) for d in ds.stores if d.release]
        snap.errors += [e for e in ds.errors]
    for name, rel in datastores or []:
        snap.components.append(Component(f"ArcGIS Data Store ({name})", rel))
    return snap


# --------------------------------------------------------------- evaluating


def _pad(t: tuple[int, ...], fill: int) -> tuple[int, ...]:
    return (t + (fill, fill, fill))[:3]


def _direct_target(rel: str) -> str | None:
    v = _pad(vtuple(rel), 0)
    for lo, hi, target in DIRECT_UPGRADE:
        if _pad(lo, 0) <= v <= _pad(hi, 99):
            return target
    return None


def evaluate(
    s: StackSnapshot, db_check: DbCheck | None = None, pro_for: ProFor | None = None
) -> list[Finding]:
    out: list[Finding] = []
    rels = {c.name: release(c.version) for c in s.components if release(c.version)}

    # STK001 base components on one release
    distinct = sorted(set(rels.values()), key=vtuple)
    if len(distinct) > 1:
        out.append(
            Finding(
                "STK001",
                Severity.FAIL,
                f"Base deployment is on mixed releases: {', '.join(distinct)}",
                "; ".join(f"{n} {v}" for n, v in rels.items())
                + ". Esri: all base ArcGIS Enterprise components must use the same software "
                "version. Finish the upgrade in order: " + ", ".join(UPGRADE_ORDER) + ".",
                {"components": rels},
            )
        )
    elif distinct:
        out.append(
            Finding(
                "STK001",
                Severity.OK,
                f"{len(rels)} component(s) on ArcGIS Enterprise {distinct[0]}",
                "",
                {"components": rels},
            )
        )
    current = release(
        next((c.version for c in s.components if c.name.startswith("ArcGIS Server")), "")
    ) or (distinct[0] if len(distinct) == 1 else None)

    # STK002 every data store on the server at the same Data Store release
    ds = {n: v for n, v in ((c.name, c.version) for c in s.components) if "Data Store" in n}
    if len({release(v) for v in ds.values()}) > 1:
        out.append(
            Finding(
                "STK002",
                Severity.FAIL,
                "Data stores on this server run different releases",
                "; ".join(f"{n} {v}" for n, v in ds.items())
                + ". Esri: all data stores registered to the same ArcGIS Server site must run "
                "the same ArcGIS Data Store release.",
            )
        )

    # STK003 the geodatabase, through rdsops compat
    if s.engine_version and current:
        if db_check is None:
            out.append(
                Finding(
                    "STK009",
                    Severity.WARN,
                    "Database side not checked: rdsops is not installed",
                    "pip install 'egisops[stack]' (or install rds-geodatabase-ops) to check the "
                    "RDS for PostgreSQL and PostGIS versions against Esri's support matrix.",
                )
            )
        else:
            for f in db_check(s.engine_version, current, s.postgis_version):
                out.append(f)
    elif current and not s.engine_version:
        out.append(
            Finding(
                "STK003",
                Severity.INFO,
                "Geodatabase versions not given",
                "Pass --engine-version and --postgis (rdsops inventory prints them) to check the "
                "RDS for PostgreSQL geodatabase against this release.",
            )
        )

    # STK004 ArcGIS Pro companion version
    if s.pro_version and current and pro_for:
        companion = pro_for(current)
        if companion and release(s.pro_version) != companion:
            out.append(
                Finding(
                    "STK004",
                    Severity.INFO,
                    f"ArcGIS Pro {s.pro_version} is not the companion of Enterprise {current}",
                    f"Esri recommends companion versions; for {current} that is ArcGIS Pro "
                    f"{companion}.",
                    {"pro": s.pro_version, "companion": companion},
                )
            )
        elif companion:
            out.append(
                Finding("STK004", Severity.OK, f"ArcGIS Pro {s.pro_version} is the companion")
            )

    # STK005 planning an upgrade to --target
    if s.target and current:
        tgt = release(s.target)
        if vtuple(tgt) <= vtuple(current):
            out.append(
                Finding(
                    "STK005",
                    Severity.INFO,
                    f"Already at or past {tgt}",
                    f"The deployment is on {current}.",
                )
            )
        else:
            direct = _direct_target(current)
            steps = []
            if direct and vtuple(tgt) <= vtuple(direct):
                path = f"{current} upgrades directly to {tgt}."
                sev = Severity.INFO
            else:
                path = (
                    f"{current} cannot upgrade directly to {tgt}"
                    + (f"; the latest direct target is {direct}" if direct else "")
                    + ". Upgrade to an interim release first."
                )
                sev = Severity.WARN
            steps.append(path)
            steps.append("Take a WebGISDR backup before upgrading any component.")
            steps.append("Order: " + ", ".join(UPGRADE_ORDER) + ".")
            if vtuple(current) < (12, 0) <= vtuple(tgt):
                steps.append(f"{RETIRED_AT_12}: migrate away on {current} first.")
                tcs = [c.name for c in s.components if "(tcs_" in c.name]
                if tcs:
                    sev = max(sev, Severity.WARN)
                    steps.append(
                        f"This site has a tile cache data store ({', '.join(tcs)}); it does not "
                        "exist at 12.0 and later, so move its scene layers before upgrading."
                    )
            if s.engine_version and db_check:
                after = [
                    f for f in db_check(s.engine_version, tgt, s.postgis_version) if f.severity >= 2
                ]
                if after:
                    sev = max(sev, Severity.WARN)
                    steps.append(
                        f"At {tgt} the geodatabase needs attention: "
                        + "; ".join(f"{f.code} {f.title}" for f in after)
                        + "."
                    )
                else:
                    steps.append(f"RDS for PostgreSQL {s.engine_version} is supported at {tgt}.")
            if pro_for and pro_for(tgt):
                steps.append(f"Companion ArcGIS Pro for {tgt}: {pro_for(tgt)}.")
            out.append(
                Finding(
                    "STK005",
                    sev,
                    f"Upgrade plan: {current} to {tgt}",
                    " ".join(steps),
                    {"from": current, "to": tgt, "direct_target": direct},
                )
            )

    for e in s.errors:
        out.append(Finding("STK009", Severity.WARN, "Part of the check could not run", e))
    return out

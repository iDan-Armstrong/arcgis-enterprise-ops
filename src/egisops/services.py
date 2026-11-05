"""services: is every service that should be running, running, and can its pool keep up?

Reads ``/admin/services`` for the folder list, then each folder's ``report``. The report
carries ``configuredState`` and
``realTimeState`` per service, and instance counts (``max``, ``busy``, ``free``), so pool
pressure comes from the same call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .findings import Finding, Severity


@dataclass(frozen=True)
class Thresholds:
    pool_info_ratio: float = 0.8  # busy / max at or above this is worth knowing


DEFAULTS = Thresholds()


@dataclass(frozen=True)
class Service:
    folder: str  # "" for the root folder
    name: str
    type: str
    configured: str | None
    realtime: str | None
    max: int | None = None
    busy: int | None = None
    free: int | None = None

    @property
    def full_name(self) -> str:
        base = f"{self.name}.{self.type}"
        return f"{self.folder}/{base}" if self.folder else base


@dataclass
class ServicesSnapshot:
    folders: list[str]
    services: list[Service] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_report(payload: dict, folder: str) -> list[Service]:
    out = []
    for r in payload.get("reports", []):
        st = r.get("status") or {}
        inst = r.get("instances") or {}
        out.append(
            Service(
                folder=r.get("folderName", folder)
                if r.get("folderName") not in (None, "/")
                else "",
                name=r["serviceName"],
                type=r.get("type", "?"),
                configured=st.get("configuredState"),
                realtime=st.get("realTimeState"),
                max=_int(inst.get("max")),
                busy=_int(inst.get("busy")),
                free=_int(inst.get("free")),
            )
        )
    return out


def gather(admin, folders: list[str] | None = None) -> ServicesSnapshot:
    try:
        root = admin.call("services")
    except Exception as e:  # noqa: BLE001 - reported as a finding
        return ServicesSnapshot([], errors=[f"services root: {e}"])
    names = folders if folders is not None else ["", *root.get("folders", [])]
    snap = ServicesSnapshot(names)
    for folder in names:
        path = f"services/{folder}/report" if folder else "services/report"
        try:
            # The documented default lists every property. Esri's docs do not show how to
            # format the `parameters` filter, so it is left out rather than guessed.
            payload = admin.call(path)
            snap.services += parse_report(payload, folder)
        except Exception as e:  # noqa: BLE001
            snap.errors.append(f"report for {folder or 'root'}: {e}")
    return snap


def evaluate(s: ServicesSnapshot, t: Thresholds = DEFAULTS) -> list[Finding]:
    out: list[Finding] = []
    running = stopped_on_purpose = 0
    for svc in s.services:
        if svc.configured == "STARTED" and svc.realtime != "STARTED":
            out.append(
                Finding(
                    "SVC001",
                    Severity.FAIL,
                    f"{svc.full_name} should be running but is {svc.realtime or 'unknown'}",
                    "Configured STARTED, real-time not: requests to it fail. Check the logs for "
                    f"the service, then POST services/{svc.full_name}/start.",
                    {"service": svc.full_name},
                )
            )
            continue
        if svc.configured == "STOPPED":
            stopped_on_purpose += 1
            continue
        running += 1
        if svc.max and svc.busy is not None:
            ratio = svc.busy / svc.max
            if svc.busy >= svc.max:
                out.append(
                    Finding(
                        "SVC003",
                        Severity.WARN,
                        f"{svc.full_name}: all {svc.max} instances busy",
                        "New requests wait for an instance and can time out. Raise the maximum "
                        "instances per machine if the machines have memory to spare, or move the "
                        "service to a dedicated pool.",
                        {"service": svc.full_name, "busy": svc.busy, "max": svc.max},
                    )
                )
            elif ratio >= t.pool_info_ratio:
                out.append(
                    Finding(
                        "SVC003",
                        Severity.INFO,
                        f"{svc.full_name}: {svc.busy} of {svc.max} instances busy",
                        "Close to the pool limit. Watch it at peak hours.",
                        {"service": svc.full_name, "busy": svc.busy, "max": svc.max},
                    )
                )
    if stopped_on_purpose:
        names = [x.full_name for x in s.services if x.configured == "STOPPED"]
        out.append(
            Finding(
                "SVC002",
                Severity.INFO,
                f"{stopped_on_purpose} service(s) stopped on purpose",
                ", ".join(names[:10]) + (f" and {len(names) - 10} more" if len(names) > 10 else ""),
                {"services": names},
            )
        )
    if s.services:
        failing = sum(1 for f in out if f.code == "SVC001")
        out.insert(
            0,
            Finding(
                "SVC000",
                Severity.OK if not failing else Severity.INFO,
                f"{running} service(s) running in {len(s.folders)} folder(s)",
            ),
        )
    for e in s.errors:
        out.append(Finding("SVC009", Severity.WARN, "Part of the check could not run", e))
    return out

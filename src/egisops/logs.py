"""logs: what has ArcGIS Server been complaining about?

Queries ``/admin/logs/query`` for SEVERE entries over a window and groups them by source
and code, so twenty identical errors from one service read as one problem.

Paging follows Esri's documentation: ``startTime`` is the newest time and ``endTime`` the
oldest; when ``hasMore`` is true, the response's ``endTime`` becomes the next
``startTime``. The documentation says times are epoch milliseconds while its sample
request uses seconds-sized values, so times read back are accepted in either unit.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .findings import Finding, Severity

ALL = {
    "codes": [],
    "processIds": [],
    "requestIds": [],
    "component": "*",
    "services": "*",
    "machines": "*",
}


@dataclass(frozen=True)
class Thresholds:
    storm_count: int = 50  # one source and code this many times in the window is a FAIL
    groups_shown: int = 8


DEFAULTS = Thresholds()


@dataclass(frozen=True)
class LogEntry:
    type: str
    code: int | None
    source: str
    machine: str
    message: str
    time: datetime | None


@dataclass
class LogSnapshot:
    hours: float
    level: str
    entries: list[LogEntry] = field(default_factory=list)
    truncated: bool = False
    errors: list[str] = field(default_factory=list)


def to_datetime(value) -> datetime | None:
    """Epoch milliseconds, or seconds (values below 10^11), to a UTC datetime."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n < 1e11:
        n *= 1000
    return datetime.fromtimestamp(n / 1000, tz=UTC)


def parse_entries(payload: dict) -> list[LogEntry]:
    out = []
    for m in payload.get("logMessages", []):
        try:
            code = int(m.get("code"))
        except (TypeError, ValueError):
            code = None
        out.append(
            LogEntry(
                type=m.get("type", "?"),
                code=code,
                source=m.get("source") or "?",
                machine=m.get("machine") or "?",
                message=(m.get("message") or "").strip(),
                time=to_datetime(m.get("time")),
            )
        )
    return out


def gather(
    admin,
    now: datetime,
    hours: float = 24,
    level: str = "SEVERE",
    page_size: int = 1000,
    max_pages: int = 5,
) -> LogSnapshot:
    snap = LogSnapshot(hours, level)
    start = int(now.timestamp() * 1000)
    end = int((now - timedelta(hours=hours)).timestamp() * 1000)
    for _ in range(max_pages):
        try:
            page = admin.call(
                "logs/query",
                startTime=start,
                endTime=end,
                level=level,
                filterType="json",
                filter=json.dumps(ALL),
                pageSize=page_size,
            )
        except Exception as e:  # noqa: BLE001 - reported as a finding
            snap.errors.append(f"logs/query: {e}")
            return snap
        snap.entries += parse_entries(page)
        if not page.get("hasMore"):
            return snap
        nxt = to_datetime(page.get("endTime"))
        nxt_ms = int(nxt.timestamp() * 1000) if nxt else None
        if nxt_ms is None or nxt_ms >= start or nxt_ms <= end:
            break  # no progress, or past the window: stop rather than loop
        start = nxt_ms
    snap.truncated = True
    return snap


def evaluate(s: LogSnapshot, t: Thresholds = DEFAULTS) -> list[Finding]:
    out: list[Finding] = []
    severe = [e for e in s.entries if e.type == "SEVERE"]
    if not severe:
        out.append(
            Finding("LOG001", Severity.OK, f"No SEVERE log entries in the last {s.hours:g} hours")
        )
    else:
        out.append(
            Finding(
                "LOG001",
                Severity.WARN,
                f"{len(severe)} SEVERE log entr{'y' if len(severe) == 1 else 'ies'} "
                f"in the last {s.hours:g} hours",
                "Grouped by source and code below. Fix the largest group first.",
                {"count": len(severe)},
            )
        )
        groups: dict[tuple[str, int | None], list[LogEntry]] = defaultdict(list)
        for e in severe:
            groups[(e.source, e.code)].append(e)
        ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
        for (source, code), items in ranked[: t.groups_shown]:
            machines = Counter(e.machine for e in items)
            latest = max((e for e in items if e.time), key=lambda e: e.time, default=items[0])
            n = len(items)
            out.append(
                Finding(
                    "LOG002",
                    Severity.FAIL if n >= t.storm_count else Severity.WARN,
                    f"{source}: code {code if code is not None else '?'} x{n}",
                    f"Latest: {latest.message[:300]}\nMachines: "
                    + ", ".join(f"{m} ({c})" for m, c in machines.most_common()),
                    {
                        "source": source,
                        "code": code,
                        "count": n,
                        "latest": latest.time.isoformat() if latest.time else None,
                    },
                )
            )
        if len(ranked) > t.groups_shown:
            out.append(
                Finding(
                    "LOG002",
                    Severity.INFO,
                    f"{len(ranked) - t.groups_shown} smaller group(s) not shown",
                )
            )
    if s.truncated:
        out.append(
            Finding(
                "LOG003",
                Severity.INFO,
                "Stopped after the page limit",
                "There are more entries than were read. Narrow --hours or raise --max-pages.",
            )
        )
    for e in s.errors:
        out.append(Finding("LOG009", Severity.WARN, "Log query could not run", e))
    return out

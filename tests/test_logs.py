import json
from datetime import UTC, datetime

from conftest import BASE, FakeSite, fixture, healthy_routes

from egisops import logs
from egisops.client import ServerAdmin
from egisops.findings import Severity
from egisops.logs import LogEntry, LogSnapshot, to_datetime

NOW = datetime.fromtimestamp(1793836800, tz=UTC)


class Pages(FakeSite):
    """Answers logs/query with page 1, then page 2, recording the times asked for."""

    def __init__(self):
        super().__init__(healthy_routes())
        self.pages = [fixture("logs_page1.json"), fixture("logs_page2.json")]

    def __call__(self, method, url, form):
        if url.endswith("/admin/logs/query"):
            self.requests.append((method, url, form))
            return 200, json.dumps(self.pages.pop(0))
        return super().__call__(method, url, form)


def test_to_datetime_accepts_milliseconds_and_seconds():
    assert to_datetime(1793836800000) == to_datetime(1793836800) == NOW
    assert to_datetime("not a time") is None


def test_pages_follow_end_time_and_send_the_documented_filter():
    site = Pages()
    snap = logs.gather(ServerAdmin(BASE, site, token="t"), NOW, hours=24)
    assert len(snap.entries) == 4 and not snap.truncated
    first, second = (form for _, url, form in site.requests if url.endswith("logs/query"))
    assert int(first["startTime"]) == 1793836800000
    assert int(first["endTime"]) == 1793836800000 - 24 * 3600 * 1000
    assert int(second["startTime"]) == 1793829600000  # page 1's endTime
    assert first["filterType"] == "json" and json.loads(first["filter"])["services"] == "*"
    assert first["level"] == "SEVERE"


def test_groups_by_source_and_code():
    snap = logs.gather(ServerAdmin(BASE, Pages(), token="t"), NOW)
    f = logs.evaluate(snap)
    assert f[0].code == "LOG001" and f[0].severity == Severity.WARN and "4 SEVERE" in f[0].title
    groups = [x for x in f if x.code == "LOG002"]
    assert groups[0].title == "Maps/Sewer.FeatureServer: code 8252 x3"
    assert "MACHINE.EXAMPLE.COM (2)" in groups[0].detail
    assert groups[1].title == "Maps/Parcels.MapServer: code 10837 x1"


def test_quiet_logs_storms_and_truncation():
    assert logs.evaluate(LogSnapshot(24, "SEVERE"))[0].severity == Severity.OK
    e = LogEntry("SEVERE", 9003, "Maps/X.MapServer", "M1", "boom", NOW)
    storm = logs.evaluate(LogSnapshot(24, "SEVERE", entries=[e] * 60, truncated=True))
    assert any(x.code == "LOG002" and x.severity == Severity.FAIL for x in storm)
    assert any(x.code == "LOG003" for x in storm)


def test_page_limit_marks_truncated():
    site = Pages()
    snap = logs.gather(ServerAdmin(BASE, site, token="t"), NOW, max_pages=1)
    assert snap.truncated and len(snap.entries) == 3

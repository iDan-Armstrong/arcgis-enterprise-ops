from conftest import BASE, FakeSite, fixture, healthy_routes

from egisops import services
from egisops.client import ServerAdmin
from egisops.findings import Severity


def routes():
    return healthy_routes(
        {
            ("POST", "/admin/services"): (200, fixture("services_root.json")),
            ("POST", "/admin/services/report"): (200, fixture("report_root.json")),
            ("POST", "/admin/services/Maps/report"): (200, fixture("report_maps.json")),
            ("POST", "/admin/services/System/report"): (200, fixture("report_system.json")),
            ("POST", "/admin/services/Utilities/report"): (200, fixture("report_utilities.json")),
        }
    )


def run(r=None, folders=None):
    site = FakeSite(r or routes())
    snap = services.gather(ServerAdmin(BASE, site, token="t"), folders=folders)
    return site, snap, services.evaluate(snap)


def test_walks_every_folder_and_reads_status_and_instances():
    site, snap, _ = run()
    assert snap.folders == ["", "Maps", "System", "Utilities"]
    names = {s.full_name for s in snap.services}
    assert names == {
        "SampleWorldCities.MapServer",
        "Maps/Stormwater.MapServer",
        "Maps/Sewer.FeatureServer",
        "Maps/Parcels.MapServer",
        "Maps/OldBasemap.MapServer",
        "System/PublishingTools.GPServer",
    }
    stormwater = next(s for s in snap.services if s.name == "Stormwater")
    assert (stormwater.max, stormwater.busy, stormwater.free) == (4, 4, 0)


def test_findings_for_stopped_saturated_and_intentional():
    _, _, f = run()
    by = {(x.code, x.evidence.get("service")): x for x in f}
    assert by[("SVC001", "Maps/Sewer.FeatureServer")].severity == Severity.FAIL
    assert by[("SVC003", "Maps/Stormwater.MapServer")].severity == Severity.WARN
    assert by[("SVC003", "Maps/Parcels.MapServer")].severity == Severity.INFO  # 4 of 5
    stopped = next(x for x in f if x.code == "SVC002")
    assert stopped.severity == Severity.INFO and "OldBasemap" in stopped.detail
    head = f[0]
    assert head.code == "SVC000" and "4 service(s) running" in head.title


def test_one_folder_failing_does_not_stop_the_rest():
    bad = {("POST", "/admin/services/Maps/report"): (200, fixture("error_token_required.json"))}
    _, snap, f = run(routes() | bad)
    assert any(x.code == "SVC009" and "Maps" in x.detail for x in f)
    assert any(s.name == "PublishingTools" for s in snap.services)


def test_folder_filter():
    site, snap, _ = run(folders=["System"])
    assert [s.name for s in snap.services] == ["PublishingTools"]
    assert not any("/Maps/" in url for _, url, _ in site.requests)

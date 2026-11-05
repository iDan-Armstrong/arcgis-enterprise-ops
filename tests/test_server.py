from datetime import UTC, datetime, timedelta

from conftest import BASE, M2, FakeSite, fixture, healthy_routes

from egisops import server
from egisops.client import ServerAdmin
from egisops.findings import Severity
from egisops.server import Certificate, LicenseItem, Machine, ServerSnapshot

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def licenses_expiring_in(days):
    payload = fixture("licenses.json")
    ms = int((NOW + timedelta(days=days)).timestamp() * 1000)
    for k in ("edition", "level", "datafeature"):
        payload[k]["expiration"] = ms + 10_000_000
    for item in payload["extensions"] + payload["features"]:
        item["expiration"] = ms + 10_000_000
    payload["features"][1]["expiration"] = ms  # the soonest
    return payload


def no_cert(url):
    return None


def run(routes, cert=no_cert):
    admin = ServerAdmin(BASE, FakeSite(routes), token="t")
    snap = server.gather(admin, read_cert=cert)
    return snap, server.evaluate(snap, NOW)


def by(findings, code):
    return [f for f in findings if f.code == code]


def test_healthy_site_reads_every_documented_field():
    routes = healthy_routes({("POST", "/admin/system/licenses"): (200, licenses_expiring_in(300))})
    snap, f = run(routes)
    assert snap.full_version == "11.5.0" and snap.licensed is True and snap.health_success
    assert [m.name for m in snap.machines] == ["MACHINE.EXAMPLE.COM", "MACHINE2.EXAMPLE.COM"]
    assert {x.name for x in snap.licenses} >= {
        "svradvanced",
        "ArcGIS Server Advanced",
        "Data Interoperability",
    }
    assert all(x.severity == Severity.OK for x in f), [x for x in f if x.severity != Severity.OK]


def test_machine_down_fails_and_stopped_by_admin_warns():
    routes = healthy_routes(
        {
            ("POST", f"{M2}/status"): (200, fixture("machine_status_down.json")),
            ("POST", "/admin/system/licenses"): (200, licenses_expiring_in(300)),
        }
    )
    _, f = run(routes)
    assert [x.severity for x in by(f, "SRV003")] == [Severity.OK, Severity.FAIL]
    s = ServerSnapshot(
        BASE, 200, True, "11.5.0", True, machines=[Machine("M", "STOPPED", "STOPPED")]
    )
    assert by(server.evaluate(s, NOW), "SRV003")[0].severity == Severity.WARN


def test_license_bands_pick_the_soonest_item():
    for days, sev in [
        (200, Severity.OK),
        (60, Severity.INFO),
        (10, Severity.WARN),
        (-3, Severity.FAIL),
    ]:
        _, f = run(
            healthy_routes({("POST", "/admin/system/licenses"): (200, licenses_expiring_in(days))})
        )
        lic = by(f, "SRV004")[0]
        assert lic.severity == sev, (days, lic)
        assert "Data Interoperability" in lic.title


def test_failed_health_check_and_unlicensed():
    routes = healthy_routes(
        {
            ("GET", "/rest/info/healthcheck"): (503, {"success": False}),
            ("POST", "/admin/"): (200, {**fixture("admin_root.json"), "isServerLicensed": "false"}),
        }
    )
    _, f = run(routes)
    assert by(f, "SRV001")[0].severity == Severity.FAIL
    assert "503" in by(f, "SRV001")[0].title
    assert by(f, "SRV002")[0].severity == Severity.FAIL


def test_missing_token_is_reported_per_part_not_fatal():
    err = (200, fixture("error_token_required.json"))
    routes = healthy_routes(
        {("POST", p): err for p in ["/admin/", "/admin/machines", "/admin/system/licenses"]}
    )
    snap, f = run(routes)
    assert snap.health_success  # the public check still ran
    assert len(by(f, "SRV000")) == 3
    assert all(x.severity == Severity.WARN for x in by(f, "SRV000"))


def test_certificate_bands_and_trust():
    def cert(days, trusted=True, issuer="CN=Example CA"):
        return Certificate(
            "gis.example.com", "CN=gis.example.com", issuer, NOW + timedelta(days=days), trusted
        )

    def sev(c):
        s = ServerSnapshot(BASE, 200, True, "11.5.0", True, certificate=c)
        return {x.code: x.severity for x in server.evaluate(s, NOW)}

    assert sev(cert(200))["SRV005"] == Severity.OK
    assert sev(cert(20))["SRV005"] == Severity.WARN
    assert sev(cert(3))["SRV005"] == Severity.FAIL
    assert sev(cert(-1))["SRV005"] == Severity.FAIL
    assert "SRV006" not in sev(cert(200))
    assert sev(cert(200, trusted=False, issuer="CN=gis.example.com"))["SRV006"] == Severity.WARN


def test_untested_version_is_info():
    s = ServerSnapshot(BASE, 200, True, "10.9.1", True)
    assert by(server.evaluate(s, NOW), "SRV007")[0].severity == Severity.INFO


def test_parse_licenses_handles_missing_and_bad_values():
    items = server.parse_licenses(
        {"edition": {"name": "x", "canExpire": True, "expiration": "soon"}}
    )
    assert items == [LicenseItem("x", True, None)]
    assert server.parse_licenses({}) == []

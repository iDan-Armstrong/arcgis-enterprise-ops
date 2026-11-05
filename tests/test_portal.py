from dataclasses import replace
from datetime import UTC, datetime, timedelta

from conftest import PA, PORTAL, FakeSite, fixture, portal_routes

from egisops import portal
from egisops.client import PortalAdmin
from egisops.findings import Severity
from egisops.server import Certificate

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def ms(days: float) -> int:
    return int((NOW + timedelta(days=days)).timestamp() * 1000)


def license_expiring(days: float) -> dict:
    lic = fixture("portal_license.json")
    for key in ("userTypes", "appBundles", "apps"):
        for item in lic[key]:
            item["expiration"] = ms(400)
    lic["userTypes"][1]["expiration"] = ms(days)
    return lic


def snapshot(overrides=None, cert=None, login=True):
    site = FakeSite(
        portal_routes({("GET", f"{PA}/license"): (200, license_expiring(200)), **(overrides or {})})
    )
    p = PortalAdmin(PORTAL, site)
    if login:
        p.login("portaladmin", "pw")
    return portal.gather(p, read_cert=lambda url: cert), site


def by_code(findings, code):
    return [f for f in findings if f.code == code]


def test_healthy_documented_site_is_clean():
    snap, _ = snapshot()
    findings = portal.evaluate(snap, NOW)
    assert max(f.severity for f in findings) <= Severity.INFO, [
        (f.code, f.title) for f in findings if f.severity > 1
    ]
    titles = {f.code: f.title for f in findings}
    assert titles["PTL001"] == "Portal health check: success"
    assert titles["PTL010"] == "Portal for ArcGIS 11.5.0.0"
    assert "3 federated server(s) validated, hosting server machine3.esri.com:6443" in [
        f.title for f in by_code(findings, "PTL008")
    ]
    assert by_code(findings, "PTL005")[0].severity == Severity.OK  # 70 of 1400


def test_token_goes_in_header_not_url():
    snap, site = snapshot()
    login = [r for r in site.requests if r[1].endswith("/sharing/rest/generateToken")][0]
    assert login[0] == "POST" and login[2]["client"] == "referer" and login[2]["referer"] == PORTAL
    for (method, url, _), headers in zip(site.requests, site.headers, strict=True):
        assert "token=" not in url
        if method == "GET" and "/portaladmin/" in url:
            assert headers == {
                "X-Esri-Authorization": f"Bearer {fixture('portal_generate_token.json')['token']}"
            }


def test_health_check_html_page_fails():
    snap, _ = snapshot({("GET", f"{PA}/healthCheck"): (503, "<html>Service Unavailable</html>")})
    f = by_code(portal.evaluate(snap, NOW), "PTL001")[0]
    assert f.severity == Severity.FAIL and "HTTP 503" in f.title


def test_site_not_initialized_is_reported():
    snap, _ = snapshot({("GET", PA): (200, fixture("portal_root_not_initialized.json"))})
    f = by_code(portal.evaluate(snap, NOW), "PTL002")[0]
    assert f.severity == Severity.FAIL and "not been initialized" in f.detail


def test_one_of_two_machines_down_warns_both_down_fails():
    err = {"status": "error", "messages": ["Machine is not available."]}
    snap, _ = snapshot({("GET", f"{PA}/machines/status/machine1.example.com"): (200, err)})
    f = [x for x in by_code(portal.evaluate(snap, NOW), "PTL003") if x.severity > Severity.OK]
    assert len(f) == 1 and f[0].severity == Severity.WARN and "standby" in f[0].title
    snap, _ = snapshot(
        {
            ("GET", f"{PA}/machines/status/machine1.example.com"): (200, err),
            ("GET", f"{PA}/machines/status/machine2.example.com"): (200, err),
        }
    )
    assert all(x.severity == Severity.FAIL for x in by_code(portal.evaluate(snap, NOW), "PTL003"))


def test_single_machine_is_info():
    one = {"machines": fixture("portal_machines.json")["machines"][1:]}
    snap, _ = snapshot({("GET", f"{PA}/machines"): (200, one)})
    f = by_code(portal.evaluate(snap, NOW), "PTL003")
    assert [x.severity for x in f] == [Severity.OK, Severity.INFO]


def test_license_bands():
    for days, sev in [
        (-2, Severity.FAIL),
        (10, Severity.WARN),
        (60, Severity.INFO),
        (200, Severity.OK),
    ]:
        snap, _ = snapshot({("GET", f"{PA}/license"): (200, license_expiring(days))})
        f = by_code(portal.evaluate(snap, NOW), "PTL004")[0]
        assert f.severity == sev, (days, f.title)
        assert "creatorUT" in f.title


def test_member_capacity_and_full_user_type():
    lic = license_expiring(200)
    lic["currentRegisteredMembers"] = 1300
    lic["userTypes"][1]["currentRegisteredMembers"] = 200
    snap, _ = snapshot({("GET", f"{PA}/license"): (200, lic)})
    f = by_code(portal.evaluate(snap, NOW), "PTL005")
    assert f[0].severity == Severity.INFO and f[0].title == "1300 of 1400 member licenses in use"
    assert f[1].severity == Severity.WARN and "creatorUT" in f[1].title


def test_federation_failure_names_server_and_role():
    v = fixture("portal_federation_validate.json")
    v["status"] = "failure"
    v["serversStatus"][1]["status"] = "failure"
    v["serversStatus"][1]["messages"].append("The server managed database is not accessible.")
    v["serversStatus"][0]["status"] = "success with warnings"
    snap, _ = snapshot({("GET", f"{PA}/federation/servers/validate"): (200, v)})
    f = by_code(portal.evaluate(snap, NOW), "PTL008")
    sevs = {x.title: x.severity for x in f}
    assert (
        sevs["Federated server machine3.esri.com:6443 (hosting server): validation failure"]
        == Severity.FAIL
    )
    assert (
        sevs["Federated server machine1.esri.com:6443: validation success with warnings"]
        == Severity.WARN
    )
    assert "not accessible" in [x for x in f if x.severity == Severity.FAIL][0].detail


def test_no_hosting_server_and_no_servers():
    servers = fixture("portal_federation_servers.json")
    servers["servers"][1]["serverRole"] = "FEDERATED_SERVER"
    snap, _ = snapshot({("GET", f"{PA}/federation/servers"): (200, servers)})
    assert "No hosting server is designated" in [
        x.title for x in by_code(portal.evaluate(snap, NOW), "PTL008")
    ]
    snap, site = snapshot({("GET", f"{PA}/federation/servers"): (200, {"servers": []})})
    f = by_code(portal.evaluate(snap, NOW), "PTL008")
    assert len(f) == 1 and f[0].severity == Severity.WARN and "federated" in f[0].title
    assert not any(r[1].split("?")[0].endswith("/validate") for r in site.requests)


def test_index_mismatch_warns():
    idx = fixture("portal_indexer_status.json")
    idx["indexes"][2]["indexCount"] = 16000
    idx["syncStatus"] = False
    snap, _ = snapshot({("GET", f"{PA}/system/indexer/status"): (200, idx)})
    f = by_code(portal.evaluate(snap, NOW), "PTL009")[0]
    assert f.severity == Severity.WARN and "search: 16451 stored, 16000 indexed" in f.detail


def test_certificate_findings_shared_with_server():
    cert = Certificate(
        "gis.example.com",
        "CN=gis.example.com, O=SelfSignedCertificate",
        "CN=gis.example.com, O=SelfSignedCertificate",
        NOW + timedelta(days=5),
        False,
    )
    snap, _ = snapshot(cert=cert)
    f = portal.evaluate(snap, NOW)
    assert by_code(f, "PTL006")[0].severity == Severity.FAIL
    assert "self-signed" in by_code(f, "PTL007")[0].title


def test_without_login_only_public_checks_run():
    snap, site = snapshot(login=False)
    f = portal.evaluate(snap, NOW)
    assert {x.code for x in f} >= {"PTL001", "PTL000"}
    assert not by_code(f, "PTL003")
    assert all("/machines" not in r[1] for r in site.requests)


def test_one_failing_part_does_not_stop_the_rest():
    snap, _ = snapshot({("GET", f"{PA}/license"): (500, "oops")})
    f = portal.evaluate(snap, NOW)
    assert [x for x in by_code(f, "PTL000") if "license" in x.detail]
    assert by_code(f, "PTL008") and by_code(f, "PTL009")


def test_version_outside_targets_is_info():
    snap, _ = snapshot()
    f = by_code(portal.evaluate(replace(snap, version="10.9.1"), NOW), "PTL010")[0]
    assert f.severity == Severity.INFO

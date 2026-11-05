import json
from datetime import UTC, datetime, timedelta

from conftest import BASE, PA, PORTAL, FakeSite, fixture, healthy_routes, portal_routes

from egisops import cli, security
from egisops.client import PortalAdmin, ServerAdmin
from egisops.findings import Severity
from egisops.server import Certificate

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
SECRETS = ("PORTAL-SECRET-DO-NOT-PRINT", "TRUST-KEY-DO-NOT-PRINT", "JQDMe5Idm")


def server_routes(over=None):
    r = {
        ("POST", "/admin/security/config"): (200, fixture("security_config.json")),
        ("POST", "/admin/security/tokens"): (200, fixture("security_tokens.json")),
        ("POST", "/admin/security/psa"): (200, fixture("security_psa.json")),
        ("POST", "/admin/system/properties"): (200, fixture("system_properties.json")),
        ("POST", "/admin/system/handlers/rest/servicesdirectory"): (
            200,
            fixture("servicesdirectory.json"),
        ),
        ("POST", "/admin/system/webadaptors"): (200, fixture("webadaptors.json")),
    }
    r.update(over or {})
    return healthy_routes(r)


def server_snap(over=None, cert=None):
    admin = ServerAdmin(BASE, FakeSite(server_routes(over)))
    admin.login("siteadmin", "pw")
    return security.gather_server(admin, read_cert=lambda url: cert)


def portal_snap(cert=None, **over):
    r = portal_routes(
        {
            ("GET", f"{PA}/security/config"): (200, fixture("portal_security_config.json")),
            ("GET", "/portal/sharing/rest/portals/self"): (200, fixture("portal_self.json")),
            **over,
        }
    )
    p = PortalAdmin(PORTAL, FakeSite(r))
    p.login("portaladmin", "pw")
    return security.gather_portal(p, read_cert=lambda url: cert)


def codes(findings, sev=None):
    return {f.code for f in findings if sev is None or f.severity == sev}


def find(findings, code):
    return [f for f in findings if f.code == code]


def test_server_documented_defaults():
    s = server_snap()
    assert s.errors == []
    assert s.protocol == "HTTPS" and s.token_get is False and s.standardized_queries is True
    f = security.evaluate_server(s, NOW)
    # documented defaults are safe for tokens and queries
    assert {x.severity for x in find(f, "ESC003")} == {Severity.OK}
    assert {x.severity for x in find(f, "ESC002")} == {Severity.OK}
    # the example has the services directory on with any origin, and the PSA enabled
    assert any(
        x.severity == Severity.WARN and x.evidence["esri"] == "SS07" for x in find(f, "ESC004")
    )
    assert any(
        x.evidence.get("esri") == "SS08" for x in find(f, "ESC004") if x.severity == Severity.WARN
    )
    assert find(f, "ESC006")[0].severity == Severity.WARN
    assert any("HSTS" in x.title for x in find(f, "ESC001"))


def test_secrets_never_reach_the_snapshot():
    s, p = server_snap(), portal_snap()
    text = repr(s) + repr(p)
    for secret in SECRETS:
        assert secret not in text


def test_secrets_never_reach_json_output(monkeypatch, capsys):
    site = FakeSite(server_routes())
    monkeypatch.setattr(cli, "connect", lambda args, portal=False: ServerAdmin(BASE, site))
    real = security.gather_server
    monkeypatch.setattr(security, "gather_server", lambda a: real(a, read_cert=lambda u: None))
    cli.main(["security", "--url", BASE, "--json", "--verbose"])
    out = capsys.readouterr().out
    json.loads(out)
    for secret in SECRETS:
        assert secret not in out


def test_server_bad_settings_fail():
    cfg = fixture("security_config.json") | {
        "sslEnabled": True,
        "httpEnabled": True,
        "httpsProtocols": "TLSv1,TLSv1.2",
    }
    toks = fixture("security_tokens.json")
    toks["properties"] |= {"allowHttpGet": "true", "allowHttpPostQueryParams": True}
    s = server_snap(
        {
            ("POST", "/admin/security/config"): (200, cfg),
            ("POST", "/admin/security/tokens"): (200, toks),
            ("POST", "/admin/system/properties"): (
                200,
                {"properties": {"standardizedQueries": False, "allowLegacyURLParser": True}},
            ),
            ("POST", "/admin/system/webadaptors"): (
                200,
                {"webadaptors": [{"webAdaptorURL": "http://gis.example.com/arcgis"}]},
            ),
        }
    )
    f = security.evaluate_server(s, NOW)
    fails = {x.evidence.get("esri") for x in f if x.severity == Severity.FAIL}
    assert {"SS01", "SS02", "SS03", "SS04"} <= fails
    assert any("TLSv1" in x.title for x in find(f, "ESC001"))
    assert any(x.evidence.get("esri") == "SS10" and x.severity == Severity.WARN for x in f)


def test_server_hardened_is_clean():
    s = security.ServerSecurity(
        "x",
        protocol="HTTPS",
        https_protocols=["TLSv1.2", "TLSv1.3"],
        hsts=True,
        direct_access=False,
        virtual_dirs_secured=True,
        token_get=False,
        token_post_query=False,
        psa_disabled=True,
        standardized_queries=True,
        legacy_url_parser=False,
        services_directory=False,
        allowed_origins="https://apps.example.com",
        web_adaptors=["https://gis.example.com/arcgis"],
    )
    f = security.evaluate_server(s, NOW)
    assert codes(f, Severity.WARN) | codes(f, Severity.FAIL) == set()


def test_self_signed_certificate_maps_to_ss14():
    cert = Certificate("gis.example.com", "CN=gis", "CN=gis", NOW + timedelta(days=300), False)
    f = security.evaluate_server(security.ServerSecurity("x", certificate=cert), NOW)
    w = [x for x in find(f, "ESC007") if x.severity == Severity.WARN]
    assert w and w[0].evidence["esri"] == "SS14" and "self-signed" in w[0].title


def test_unreadable_parts_are_reported_not_assumed():
    s = server_snap(
        {("POST", "/admin/security/psa"): (403, {"status": "error", "messages": ["no"]})}
    )
    f = security.evaluate_server(s, NOW)
    assert find(f, "ESC000") and not find(f, "ESC006")


def test_portal_example():
    p = portal_snap()
    assert p.errors == []
    f = security.evaluate_portal(p, NOW)
    assert find(f, "ESC011")[0].severity == Severity.OK
    assert find(f, "ESC012")[0].severity == Severity.WARN
    assert find(f, "ESC013")[0].severity == Severity.OK
    assert find(f, "ESC014")[0].severity == Severity.WARN  # empty list means any origin
    assert find(f, "ESC015")[0].severity == Severity.INFO


def test_portal_http_and_public():
    p = security.PortalSecurity(
        "x",
        all_ssl=False,
        access="public",
        can_share_public=True,
        allowed_origins=["https://apps.example.com"],
    )
    f = security.evaluate_portal(p, NOW)
    assert find(f, "ESC011")[0].severity == Severity.FAIL
    assert "share publicly" in find(f, "ESC013")[0].detail
    assert find(f, "ESC014")[0].severity == Severity.OK


def test_not_checked_lists_scanner_ids():
    ids = {f.evidence["esri"] for f in security.not_checked(portal=True)}
    assert "PS01" in ids and "PS18" in ids
    assert all(f.severity == Severity.INFO for f in security.not_checked(portal=False))

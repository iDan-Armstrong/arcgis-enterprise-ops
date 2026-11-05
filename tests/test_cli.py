import json

from conftest import FakeSite, healthy_routes

from egisops import cli, client, server


def test_cli_json_with_token_from_env(monkeypatch, capsys):
    site = FakeSite(healthy_routes())
    monkeypatch.setattr(client, "urllib_transport", lambda **kw: site)
    monkeypatch.setattr(server, "read_certificate", lambda url, **kw: None)
    monkeypatch.setenv("EGISOPS_TOKEN", "from-env")
    code = cli.main(["server-health", "--url", "https://gis.example.com/arcgis", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == "11.5.0"
    assert any(f["code"] == "SRV004" for f in out["findings"])
    assert code == 2  # the documented example license expired in 2011
    assert all(form is None or form.get("token") == "from-env" for _, _, form in site.requests)


def test_cli_has_no_password_flag():
    actions = {
        a.dest
        for sp in cli.build_parser()._subparsers._group_actions[0].choices.values()
        for a in sp._actions
    }
    assert "password" not in actions
    assert "insecure" not in actions and "no_verify" not in actions


def test_cli_portal_health_text(monkeypatch, capsys):
    from conftest import FakeSite, portal_routes

    site = FakeSite(portal_routes())
    monkeypatch.setattr(client, "urllib_transport", lambda **kw: site)
    monkeypatch.setattr(server, "read_certificate", lambda url, **kw: None)
    monkeypatch.setenv("EGISOPS_TOKEN", "from-env")
    cli.main(["portal-health", "--url", "https://gis.example.com/portal"])
    out = capsys.readouterr().out
    assert out.startswith("portal-health  https://gis.example.com/portal  Portal for ArcGIS 11.5")
    assert "PTL008" in out and "PTL009" in out
    assert all(h.get("X-Esri-Authorization") == "Bearer from-env" for h in site.headers)


def test_cli_datastore_json(monkeypatch, capsys):
    from conftest import FakeSite, datastore_routes

    site = FakeSite(datastore_routes())
    monkeypatch.setattr(client, "urllib_transport", lambda **kw: site)
    monkeypatch.setenv("EGISOPS_TOKEN", "from-env")
    code = cli.main(["datastore", "--url", "https://gis.example.com/arcgis", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert len(out["stores"]) == 2
    assert code == 1  # unavailable tile cache machine, and the example backup is years old

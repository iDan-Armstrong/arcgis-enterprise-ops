import pytest
from conftest import BASE, FakeSite, fixture, healthy_routes

from egisops.client import AdminError, ServerAdmin


def test_login_uses_post_and_referer_token(site):
    admin = ServerAdmin(BASE, site)
    admin.login("siteadmin", "s3cret")
    method, url, form = site.requests[-1]
    assert method == "POST" and url.endswith("/admin/generateToken")
    assert form["client"] == "referer" and form["referer"] == BASE and form["f"] == "json"
    assert admin.token == fixture("generate_token.json")["token"]


def test_token_travels_in_the_body_never_the_url(site):
    admin = ServerAdmin(BASE, site, token="abc123")
    admin.call("machines")
    method, url, form = site.requests[-1]
    assert method == "POST" and "abc123" not in url and form["token"] == "abc123"


def test_esri_error_bodies_raise_even_with_http_200():
    site = FakeSite(
        healthy_routes({("POST", "/admin/machines"): (200, fixture("error_token_required.json"))})
    )
    with pytest.raises(AdminError, match="Token not found"):
        ServerAdmin(BASE, site).call("machines")
    site = FakeSite(
        healthy_routes(
            {
                ("POST", "/admin/machines"): (
                    200,
                    {"error": {"code": 498, "message": "Invalid token."}},
                )
            }
        )
    )
    with pytest.raises(AdminError, match="498 Invalid token"):
        ServerAdmin(BASE, site).call("machines")


def test_non_json_and_failed_login():
    site = FakeSite(
        healthy_routes({("POST", "/admin/machines"): (502, "<html>Bad gateway</html>")})
    )
    with pytest.raises(AdminError, match="HTTP 502"):
        ServerAdmin(BASE, site).call("machines")
    site = FakeSite(
        healthy_routes(
            {
                ("POST", "/admin/generateToken"): (
                    200,
                    {"status": "error", "messages": ["Invalid credentials"]},
                )
            }
        )
    )
    with pytest.raises(AdminError, match="Invalid credentials"):
        ServerAdmin(BASE, site).login("x", "y")

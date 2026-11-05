import json
import pathlib
from urllib.parse import urlparse

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
BASE = "https://gis.example.com/arcgis"
M1 = "/admin/machines/MACHINE.EXAMPLE.COM"
M2 = "/admin/machines/MACHINE2.EXAMPLE.COM"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeSite:
    """Answers admin calls from documented example responses and records every request."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, dict | str]]):
        self.routes = routes
        self.requests: list[tuple[str, str, dict | None]] = []
        self.headers: list[dict] = []

    def __call__(self, method, url, form, headers=None):
        self.requests.append((method, url, form))
        self.headers.append(headers or {})
        path = urlparse(url).path.removeprefix("/arcgis")
        key = (method, path)
        if key not in self.routes:
            return 404, json.dumps({"status": "error", "messages": [f"no route {key}"]})
        status, body = self.routes[key]
        if callable(body):  # answer depends on the form, e.g. findItems by parentPath
            body = body(form or {})
        return status, body if isinstance(body, str) else json.dumps(body)


def healthy_routes(overrides: dict | None = None):
    routes = {
        ("GET", "/rest/info/healthcheck"): (200, fixture("healthcheck_ok.json")),
        ("POST", "/admin/generateToken"): (200, fixture("generate_token.json")),
        ("POST", "/admin/"): (200, fixture("admin_root.json")),
        ("POST", "/admin/machines"): (200, fixture("machines.json")),
        ("POST", f"{M1}/status"): (200, fixture("machine_status_started.json")),
        ("POST", f"{M2}/status"): (200, fixture("machine_status_started.json")),
        ("POST", "/admin/system/licenses"): (200, fixture("licenses.json")),
    }
    routes.update(overrides or {})
    return routes


@pytest.fixture
def site():
    return FakeSite(healthy_routes())


PORTAL = "https://gis.example.com/portal"
PA = "/portal/portaladmin"


def portal_routes(overrides: dict | None = None):
    routes = {
        ("GET", f"{PA}/healthCheck"): (200, fixture("portal_health_ok.json")),
        ("POST", "/portal/sharing/rest/generateToken"): (
            200,
            fixture("portal_generate_token.json"),
        ),
        ("GET", PA): (200, fixture("portal_root.json")),
        ("GET", f"{PA}/machines"): (200, fixture("portal_machines.json")),
        ("GET", f"{PA}/machines/status/machine1.example.com"): (
            200,
            fixture("portal_machine_status.json"),
        ),
        ("GET", f"{PA}/machines/status/machine2.example.com"): (
            200,
            fixture("portal_machine_status.json"),
        ),
        ("GET", f"{PA}/license"): (200, fixture("portal_license.json")),
        ("GET", f"{PA}/federation/servers"): (200, fixture("portal_federation_servers.json")),
        ("GET", f"{PA}/federation/servers/validate"): (
            200,
            fixture("portal_federation_validate.json"),
        ),
        ("GET", f"{PA}/system/indexer/status"): (200, fixture("portal_indexer_status.json")),
    }
    routes.update(overrides or {})
    return routes


_DSM = "machines/MACHINE.EXAMPLE.COM/validate"
DS_REL = f"/admin/data/items/enterpriseDatabases/AGSDataStore_ds_d0hv9sqh/{_DSM}"
DS_TC = f"/admin/data/items/nosqlDatabases/AGSDataStore_nosql_tcs_abcdef8x/{_DSM}"


def find_items(form):
    return (
        fixture("find_items_egdb.json")
        if form.get("parentPath") == "/enterpriseDatabases"
        else fixture("find_items_nosql.json")
    )


def datastore_routes(overrides: dict | None = None):
    routes = {
        ("POST", "/admin/generateToken"): (200, fixture("generate_token.json")),
        ("POST", "/admin/data/findItems"): (200, find_items),
        ("POST", DS_REL): (200, fixture("validate_relational.json")),
        ("POST", DS_TC): (200, fixture("validate_tilecache_unavailable.json")),
    }
    routes.update(overrides or {})
    return routes

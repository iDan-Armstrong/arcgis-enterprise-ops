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

    def __call__(self, method, url, form):
        self.requests.append((method, url, form))
        path = urlparse(url).path.removeprefix("/arcgis")
        key = (method, path)
        if key not in self.routes:
            return 404, json.dumps({"status": "error", "messages": [f"no route {key}"]})
        status, body = self.routes[key]
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

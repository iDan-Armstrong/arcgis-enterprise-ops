"""Small clients for the ArcGIS Server and Portal Administrator APIs, standard library only.

- Server tokens come from ``/admin/generateToken`` (POST); Portal tokens from
  ``/sharing/rest/generateToken`` (POST); either can come from ``EGISOPS_TOKEN``.
- Passwords come from ``EGISOPS_PASSWORD`` or an interactive prompt, never a flag.
- Server admin calls are POSTs with ``f=json`` and the token in the form body. Portal
  admin resources are documented as GET, so the token goes in the
  ``X-Esri-Authorization: Bearer`` header instead (ADR 0005). Either way tokens do not end
  up in URLs, proxy logs or browser history.
- Esri reports many errors as HTTP 200 with an error body; those raise ``AdminError``.

The transport is injectable so tests can answer with documented example responses.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

# transport(method, url, form, headers=None) -> (http_status, body_text)
Transport = Callable[..., tuple[int, str]]


class AdminError(RuntimeError):
    pass


def urllib_transport(timeout: float = 30.0, context: ssl.SSLContext | None = None) -> Transport:
    def send(
        method: str, url: str, form: dict | None, headers: dict | None = None
    ) -> tuple[int, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "egisops")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    return send


def _raise_for_esri_error(payload: dict, what: str) -> None:
    if isinstance(payload, dict):
        if payload.get("status") == "error":
            raise AdminError(f"{what}: {'; '.join(payload.get('messages', [])) or 'error'}")
        if "error" in payload:
            err = payload["error"] or {}
            raise AdminError(f"{what}: {err.get('code', '')} {err.get('message', '')}".strip())


@dataclass
class ServerAdmin:
    """``base`` is the server root, e.g. https://gis.example.com/arcgis or
    https://machine.example.com:6443/arcgis."""

    base: str
    transport: Transport
    token: str | None = None

    def __post_init__(self):
        self.base = self.base.rstrip("/")

    @property
    def admin(self) -> str:
        return f"{self.base}/admin"

    def login(self, username: str, password: str, minutes: int = 60) -> None:
        self.token = _token_from(
            self.transport, f"{self.admin}/generateToken", username, password, minutes
        )

    def call(self, path: str, **params) -> dict:
        """POST an admin resource or operation and return the JSON body."""
        form = {"f": "json", **{k: str(v) for k, v in params.items()}}
        if self.token:
            form["token"] = self.token
        status, body = self.transport("POST", f"{self.admin}/{path.lstrip('/')}", form)
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise AdminError(f"{path}: HTTP {status}, not JSON") from e
        _raise_for_esri_error(payload, path)
        return payload

    def healthcheck(self) -> tuple[int, dict | None]:
        """Public endpoint for load balancers: HTTP 200 and success=true when healthy."""
        status, body = self.transport("GET", f"{self.base}/rest/info/healthcheck?f=json", None)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None


def _token_from(transport: Transport, url: str, username: str, password: str, minutes: int):
    status, body = transport(
        "POST",
        url,
        {
            "username": username,
            "password": password,
            "client": "referer",
            "referer": url.split("/sharing/")[0].split("/admin/")[0],
            "expiration": str(minutes),
            "f": "json",
        },
    )
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise AdminError(f"generateToken: HTTP {status}, not JSON") from e
    _raise_for_esri_error(payload, "generateToken")
    if "token" not in payload:
        raise AdminError("generateToken: no token in response")
    return payload["token"]


@dataclass
class PortalAdmin:
    """``base`` is the portal root, e.g. https://gis.example.com/portal or
    https://portal.example.com:7443/arcgis. Admin resources live under ``/portaladmin``."""

    base: str
    transport: Transport
    token: str | None = None

    def __post_init__(self):
        self.base = self.base.rstrip("/")

    @property
    def admin(self) -> str:
        return f"{self.base}/portaladmin"

    def login(self, username: str, password: str, minutes: int = 60) -> None:
        self.token = _token_from(
            self.transport, f"{self.base}/sharing/rest/generateToken", username, password, minutes
        )

    def _headers(self) -> dict:
        return {"X-Esri-Authorization": f"Bearer {self.token}"} if self.token else {}

    def call(self, path: str) -> dict:
        """GET a portaladmin resource and return the JSON body."""
        url = f"{self.admin}/{path.lstrip('/')}".rstrip("/") + "?f=json"
        status, body = self.transport("GET", url, None, self._headers())
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise AdminError(f"{path or 'portaladmin'}: HTTP {status}, not JSON") from e
        _raise_for_esri_error(payload, path or "portaladmin")
        return payload

    def healthcheck(self) -> tuple[int, dict | None]:
        """HTTP 200 and status=success when the machine can take requests. An unavailable
        machine answers with something other than 200, often an HTML page."""
        status, body = self.transport(
            "GET", f"{self.admin}/healthCheck?f=json", None, self._headers()
        )
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None


def credentials_from_env(username: str | None) -> tuple[str | None, str | None, str | None]:
    """(username, password, token) from flags and the environment. Never from argv."""
    token = os.environ.get("EGISOPS_TOKEN")
    user = username or os.environ.get("EGISOPS_USER")
    password = os.environ.get("EGISOPS_PASSWORD")
    return user, password, token

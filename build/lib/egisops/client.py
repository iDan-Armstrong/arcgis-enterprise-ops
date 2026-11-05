"""A small client for the ArcGIS Server Administrator API, standard library only.

- Tokens come from ``/admin/generateToken`` (POST), or from ``EGISOPS_TOKEN``.
- Passwords come from ``EGISOPS_PASSWORD`` or an interactive prompt, never a flag.
- Every admin call is a POST with ``f=json`` and the token in the form body, so tokens do
  not end up in URLs, proxy logs or browser history.
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

# transport(method, url, form) -> (http_status, body_text)
Transport = Callable[[str, str, dict | None], tuple[int, str]]


class AdminError(RuntimeError):
    pass


def urllib_transport(timeout: float = 30.0, context: ssl.SSLContext | None = None) -> Transport:
    def send(method: str, url: str, form: dict | None) -> tuple[int, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "egisops")
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
        status, body = self.transport(
            "POST",
            f"{self.admin}/generateToken",
            {
                "username": username,
                "password": password,
                "client": "referer",
                "referer": self.base,
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
        self.token = payload["token"]

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


def credentials_from_env(username: str | None) -> tuple[str | None, str | None, str | None]:
    """(username, password, token) from flags and the environment. Never from argv."""
    token = os.environ.get("EGISOPS_TOKEN")
    user = username or os.environ.get("EGISOPS_USER")
    password = os.environ.get("EGISOPS_PASSWORD")
    return user, password, token

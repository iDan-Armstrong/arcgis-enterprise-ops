"""server-health: is this ArcGIS Server site up, licensed, and not about to expire?

``gather`` reads the site through the Administrator API (and the TLS handshake);
``evaluate`` is pure. Response shapes follow Esri's documented examples, linked in
tests/fixtures/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .findings import Finding, Severity

# Releases this tool is written and tested against (docs-based; see ADR 0003).
TARGET_RELEASES = ("11.5", "12.0", "12.1")


@dataclass(frozen=True)
class Thresholds:
    license_warn_days: int = 30
    license_info_days: int = 90
    cert_fail_days: int = 7
    cert_warn_days: int = 30


DEFAULTS = Thresholds()


@dataclass(frozen=True)
class Machine:
    name: str
    configured: str  # STARTED | STOPPED
    realtime: str | None  # STARTED | STOPPED | None when status could not be read


@dataclass(frozen=True)
class LicenseItem:
    name: str
    can_expire: bool
    expires: datetime | None


@dataclass(frozen=True)
class Certificate:
    host: str
    subject: str
    issuer: str
    not_after: datetime
    trusted: bool  # chains to a CA this machine trusts and matches the host name


@dataclass
class ServerSnapshot:
    base_url: str
    health_status: int | None
    health_success: bool | None
    full_version: str | None
    licensed: bool | None
    machines: list[Machine] = field(default_factory=list)
    licenses: list[LicenseItem] = field(default_factory=list)
    certificate: Certificate | None = None
    errors: list[str] = field(default_factory=list)  # parts that could not be read


# --------------------------------------------------------------- gathering


def _ms(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def parse_licenses(payload: dict) -> list[LicenseItem]:
    """Edition, level, datafeature, extensions and (10.5+) features each carry
    name, canExpire and expiration in epoch milliseconds."""
    out: list[LicenseItem] = []
    for key in ("edition", "level", "datafeature"):
        item = payload.get(key)
        if isinstance(item, dict) and item.get("name"):
            out.append(
                LicenseItem(item["name"], bool(item.get("canExpire")), _ms(item.get("expiration")))
            )
    for key in ("features", "extensions"):
        for item in payload.get(key) or []:
            name = item.get("displayName") or item.get("name")
            if name and not any(x.name == name for x in out):
                out.append(
                    LicenseItem(name, bool(item.get("canExpire")), _ms(item.get("expiration")))
                )
    return out


_SHORT = {
    "commonName": "CN",
    "organizationName": "O",
    "organizationalUnitName": "OU",
    "countryName": "C",
    "stateOrProvinceName": "ST",
    "localityName": "L",
}


def _name(parts) -> str:
    """Distinguished name in the usual short form, e.g. 'CN=gis.example.com, O=Example'."""
    return ", ".join(f"{_SHORT.get(k, k)}={v}" for rdn in parts for (k, v) in rdn)


def _from_decoded(host: str, info: dict, trusted: bool) -> Certificate:
    not_after = datetime.strptime(info["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    return Certificate(
        host, _name(info.get("subject", ())), _name(info.get("issuer", ())), not_after, trusted
    )


def read_certificate(url: str, timeout: float = 10.0) -> Certificate | None:
    """The certificate the site presents, read from the TLS handshake.

    First a normal verified handshake: the public ssl API then returns the dates, and
    success means the certificate is trusted. If verification fails (self-signed or a
    private CA), the dates are decoded from the raw certificate instead and it is
    reported as untrusted.
    """
    import socket
    import ssl
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme != "https":
        return None
    host, port = u.hostname, u.port or 443
    try:
        ctx = ssl.create_default_context()
        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as tls,
        ):
            return _from_decoded(host, tls.getpeercert(), trusted=True)
    except ssl.SSLCertVerificationError:
        pass
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection((host, port), timeout=timeout) as sock,
        ctx.wrap_socket(sock, server_hostname=host) as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    return certificate_from_der(host, der, trusted=False)


def certificate_from_der(host: str, der: bytes, trusted: bool = False) -> Certificate:
    """Decode an untrusted certificate's fields with the standard library's decoder."""
    import os
    import ssl
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
        fh.write(ssl.DER_cert_to_PEM_cert(der))
        path = fh.name
    try:
        # CPython's own certificate decoder. It is not public API, which is why it is
        # only used for certificates the public verified path cannot read.
        info = ssl._ssl._test_decode_cert(path)
    finally:
        os.unlink(path)
    return _from_decoded(host, info, trusted)


def gather(admin, *, read_cert=read_certificate) -> ServerSnapshot:
    snap = ServerSnapshot(admin.base, None, None, None, None)
    try:
        status, body = admin.healthcheck()
        snap.health_status = status
        snap.health_success = bool(body and body.get("success") is True and status == 200)
    except Exception as e:  # noqa: BLE001 - each part is reported, not fatal
        snap.errors.append(f"health check: {e}")
    try:
        root = admin.call("")
        snap.full_version = str(root.get("fullVersion") or root.get("currentVersion") or "")
        snap.licensed = str(root.get("isServerLicensed", "")).lower() == "true"
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"admin root: {e}")
    try:
        for m in admin.call("machines").get("machines", []):
            name = m["machineName"]
            try:
                st = admin.call(f"machines/{name}/status")
                snap.machines.append(
                    Machine(name, st.get("configuredState", "?"), st.get("realTimeState"))
                )
            except Exception as e:  # noqa: BLE001
                snap.machines.append(Machine(name, "?", None))
                snap.errors.append(f"machine {name} status: {e}")
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"machines: {e}")
    try:
        snap.licenses = parse_licenses(admin.call("system/licenses"))
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"licenses: {e}")
    try:
        snap.certificate = read_cert(admin.base)
    except Exception as e:  # noqa: BLE001
        snap.errors.append(f"certificate: {e}")
    return snap


# --------------------------------------------------------------- evaluating


def _days(until: datetime, now: datetime) -> float:
    return (until - now).total_seconds() / 86400


def certificate_findings(
    c: Certificate | None, now: datetime, t: Thresholds, expiry_code: str, trust_code: str
) -> list[Finding]:
    """Expiry and trust of a certificate read from the TLS handshake. Shared by
    server-health and portal-health."""
    if not c:
        return []
    out: list[Finding] = []
    days = _days(c.not_after, now)
    sev = (
        Severity.FAIL
        if days < t.cert_fail_days
        else Severity.WARN
        if days < t.cert_warn_days
        else Severity.OK
    )
    out.append(
        Finding(
            expiry_code,
            sev,
            f"TLS certificate for {c.host} "
            + (f"expired {abs(days):.0f} days ago" if days < 0 else f"expires in {days:.0f} days"),
            ""
            if sev == Severity.OK
            else "Renew it and import it on the web adaptor or each machine before it lapses; "
            "clients refuse expired certificates.",
            {"not_after": c.not_after.isoformat(), "issuer": c.issuer},
        )
    )
    if not c.trusted:
        self_signed = c.subject == c.issuer
        out.append(
            Finding(
                trust_code,
                Severity.WARN,
                f"{c.host} presents a "
                + (
                    "self-signed certificate"
                    if self_signed
                    else "certificate this machine does not trust"
                ),
                "Browsers, ArcGIS Pro and federation need a certificate they trust. Replace "
                "it with a CA-signed one (the default self-signed certificate is for setup "
                "only), or install the private CA on every client.",
                {"subject": c.subject, "issuer": c.issuer},
            )
        )
    return out


def evaluate(s: ServerSnapshot, now: datetime, t: Thresholds = DEFAULTS) -> list[Finding]:
    out: list[Finding] = []

    if s.health_success is None:
        out.append(
            Finding(
                "SRV001",
                Severity.FAIL,
                "Health check could not be reached",
                "GET /rest/info/healthcheck failed. Load balancers using it will "
                "route around this machine.",
            )
        )
    elif s.health_success:
        out.append(Finding("SRV001", Severity.OK, "Health check: success"))
    else:
        out.append(
            Finding(
                "SRV001",
                Severity.FAIL,
                f"Health check failed (HTTP {s.health_status})",
                "The machine that answered cannot accept requests. Check the "
                "ArcGIS Server service and the logs.",
                {"http_status": s.health_status},
            )
        )

    if s.licensed is False:
        out.append(
            Finding(
                "SRV002",
                Severity.FAIL,
                "Server is not licensed",
                "Authorize the site with a license file from My Esri.",
            )
        )
    elif s.licensed:
        out.append(Finding("SRV002", Severity.OK, "Server is licensed"))

    for m in s.machines:
        if m.realtime is None:
            out.append(
                Finding(
                    "SRV003",
                    Severity.WARN,
                    f"Machine {m.name}: status unknown",
                    "The status call failed; see errors.",
                )
            )
        elif m.realtime == "STARTED":
            out.append(Finding("SRV003", Severity.OK, f"Machine {m.name} is running"))
        elif m.configured == "STOPPED":
            out.append(
                Finding(
                    "SRV003",
                    Severity.WARN,
                    f"Machine {m.name} was stopped by an admin",
                    "Configured state STOPPED. If the stop is finished, start it from "
                    "Manager or POST machines/<name>/start.",
                    {"machine": m.name},
                )
            )
        else:
            out.append(
                Finding(
                    "SRV003",
                    Severity.FAIL,
                    f"Machine {m.name} should be running but is {m.realtime}",
                    "Configured STARTED, real-time not. Services on this machine are "
                    "not serving. Check the ArcGIS Server service on the host.",
                    {"machine": m.name},
                )
            )

    expiring = [x for x in s.licenses if x.can_expire and x.expires]
    if expiring:
        soonest = min(expiring, key=lambda x: x.expires)
        days = _days(soonest.expires, now)
        sev = (
            Severity.FAIL
            if days < 0
            else Severity.WARN
            if days < t.license_warn_days
            else Severity.INFO
            if days < t.license_info_days
            else Severity.OK
        )
        out.append(
            Finding(
                "SRV004",
                sev,
                f"License {soonest.name} "
                + (
                    f"expired {abs(days):.0f} days ago"
                    if days < 0
                    else f"expires in {days:.0f} days"
                ),
                ""
                if sev == Severity.OK
                else "Request the renewal from My Esri now; an expired license stops services.",
                {"license": soonest.name, "expires": soonest.expires.isoformat()},
            )
        )

    out += certificate_findings(s.certificate, now, t, "SRV005", "SRV006")

    if s.full_version:
        major_minor = ".".join(s.full_version.split(".")[:2])
        if major_minor in TARGET_RELEASES:
            out.append(Finding("SRV007", Severity.OK, f"ArcGIS Server {s.full_version}"))
        else:
            out.append(
                Finding(
                    "SRV007",
                    Severity.INFO,
                    f"ArcGIS Server {s.full_version} is outside the tested releases",
                    f"egisops is written against {', '.join(TARGET_RELEASES)}.",
                )
            )

    for e in s.errors:
        out.append(Finding("SRV000", Severity.WARN, "Part of the check could not run", e))
    return out

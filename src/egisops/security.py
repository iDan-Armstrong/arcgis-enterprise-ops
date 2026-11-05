"""security: an ArcGIS Server site or a portal against Esri's security best practices.

Esri ships two scanners with ArcGIS Enterprise, serverScan.py and portalScan.py. This
check reads the same settings through the Administrator API and reports them with the
scanner's check ID in the evidence (``esri``), so a finding here can be compared with a
scan report. Not every scanner check has a documented setting to read; those are listed
as not checked rather than assumed safe.

Secrets in these resources are never kept. ``security/tokens`` returns the token shared
key and ``security/config`` can return ``portalSecretKey`` and ``webgisServerTrustKey``;
the parsers read named fields only, so those values never reach the snapshot, the output
or ``--json``.

``gather`` reads the site; ``evaluate`` is pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .findings import Finding, Severity
from .server import DEFAULTS as SERVER_DEFAULTS
from .server import Certificate, certificate_findings

WEAK_TLS = {"TLSv1", "TLSv1.1"}

# Scanner checks this tool does not read, and why (shown with --verbose and in the docs).
NOT_CHECKED_SERVER = {
    "SS05": "filter web content per feature service (use egisops services and the scanner)",
    "SS06": "permissions on System folder services",
    "SS09": "dynamic workspaces per service",
    "SS12": "anonymous update or delete per feature service",
    "SS13": "LDAP identity store encryption",
    "SS15": "System services shared as portal items",
}
NOT_CHECKED_PORTAL = {
    "PS01": "proxy restrictions (no documented setting found to read)",
    "PS02": "token requests with credentials in the query string",
    "PS05": "built-in account sign-up",
    "PS07": "LDAP identity store encryption",
    "PS10": "federated server admin URL trust (portal-health validates federation)",
    "PS11": "federated server services URL trust",
    "PS12": "items still shared with Everyone",
    "PS13": "SAML encrypted assertions and signed requests",
    "PS14": "default print service",
    "PS15": "legend service",
    "PS16": "RSS service",
    "PS17": "KML service",
    "PS18": "Windows service account in local Administrators",
}


def _bool(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return True if s == "true" else False if s == "false" else None


@dataclass
class ServerSecurity:
    base_url: str
    protocol: str | None = None  # HTTP | HTTP_AND_HTTPS | HTTPS
    https_protocols: list[str] | None = None
    hsts: bool | None = None
    direct_access: bool | None = None  # allowDirectAccess (port 6080 admin)
    virtual_dirs_secured: bool | None = None
    admin_ips: str | None = None  # allowedAdminAccessIPs
    token_get: bool | None = None  # allowHttpGet
    token_post_query: bool | None = None  # allowHttpPostQueryParams
    psa_disabled: bool | None = None
    standardized_queries: bool | None = None
    legacy_url_parser: bool | None = None
    services_directory: bool | None = None
    allowed_origins: str | None = None
    web_adaptors: list[str] | None = None
    certificate: Certificate | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class PortalSecurity:
    base_url: str
    services_directory_disabled: bool | None = None
    auto_accounts: bool | None = None  # enableAutomaticAccountCreation
    access: str | None = None  # portals/self access: public | private
    all_ssl: bool | None = None
    can_share_public: bool | None = None
    allowed_origins: list[str] | None = None
    certificate: Certificate | None = None
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------- parsing


def parse_server_config(payload: dict, s: ServerSecurity) -> None:
    """security/config. Only named fields are read: portalProperties holds secrets."""
    proto = payload.get("Protocol") or payload.get("protocol")
    if not proto:
        ssl_on, http_on = _bool(payload.get("sslEnabled")), _bool(payload.get("httpEnabled"))
        if ssl_on is not None and http_on is not None:
            proto = "HTTP_AND_HTTPS" if ssl_on and http_on else "HTTPS" if ssl_on else "HTTP"
    s.protocol = proto
    tls = payload.get("httpsProtocols")
    if tls:
        s.https_protocols = [x.strip() for x in str(tls).split(",") if x.strip()]
    s.hsts = _bool(payload.get("HSTSEnabled"))
    s.direct_access = _bool(payload.get("allowDirectAccess"))
    s.virtual_dirs_secured = _bool(payload.get("virtualDirsSecurityEnabled"))
    ips = payload.get("allowedAdminAccessIPs")
    s.admin_ips = str(ips) if ips else None


def parse_tokens(payload: dict, s: ServerSecurity) -> None:
    """security/tokens. The shared key is in here; it is not read."""
    props = payload.get("properties") or {}
    s.token_get = _bool(props.get("allowHttpGet"))
    s.token_post_query = _bool(props.get("allowHttpPostQueryParams"))
    # Esri documents both as false by default; absent means the default.
    if s.token_get is None:
        s.token_get = False
    if s.token_post_query is None:
        s.token_post_query = False


def parse_system_properties(payload: dict, s: ServerSecurity) -> None:
    props = payload.get("properties", payload) or {}
    sq = _bool(props.get("standardizedQueries"))
    s.standardized_queries = True if sq is None else sq  # default true
    lp = _bool(props.get("allowLegacyURLParser"))
    s.legacy_url_parser = False if lp is None else lp


def parse_web_adaptors(payload: dict) -> list[str]:
    items = payload.get("webAdaptors") or payload.get("webadaptors") or []
    return [w.get("webAdaptorURL", "") for w in items if w.get("webAdaptorURL")]


def parse_portal_config(payload: dict, p: PortalSecurity) -> None:
    """portaladmin/security/config. webgisServerTrustKey is in here; it is not read."""
    p.services_directory_disabled = _bool(payload.get("disableServicesDirectory"))
    p.auto_accounts = _bool(payload.get("enableAutomaticAccountCreation"))


def parse_portal_self(payload: dict, p: PortalSecurity) -> None:
    p.access = payload.get("access")
    p.all_ssl = _bool(payload.get("allSSL"))
    p.can_share_public = _bool(payload.get("canSharePublic"))
    origins = payload.get("allowedOrigins")
    if origins is not None:
        p.allowed_origins = (
            [o.strip() for o in origins.split(",") if o.strip()]
            if isinstance(origins, str)
            else list(origins)
        )


# --------------------------------------------------------------- gathering


def gather_server(admin, *, read_cert=None) -> ServerSecurity:
    s = ServerSecurity(admin.base)
    for path, parse in (
        ("security/config", lambda d: parse_server_config(d, s)),
        ("security/tokens", lambda d: parse_tokens(d, s)),
        ("system/properties", lambda d: parse_system_properties(d, s)),
    ):
        try:
            parse(admin.call(path))
        except Exception as e:  # noqa: BLE001 - report and keep going
            s.errors.append(f"{path}: {e}")
    try:
        s.psa_disabled = _bool(admin.call("security/psa").get("disabled"))
    except Exception as e:  # noqa: BLE001
        s.errors.append(f"security/psa: {e}")
    try:
        d = admin.call("system/handlers/rest/servicesdirectory")
        s.services_directory = _bool(d.get("enabled"))
        s.allowed_origins = d.get("allowedOrigins")
    except Exception as e:  # noqa: BLE001
        s.errors.append(f"system/handlers/rest/servicesdirectory: {e}")
    try:
        s.web_adaptors = parse_web_adaptors(admin.call("system/webadaptors"))
    except Exception as e:  # noqa: BLE001
        s.errors.append(f"system/webadaptors: {e}")
    if read_cert is None:
        from .server import read_certificate as read_cert
    try:
        s.certificate = read_cert(admin.base)
    except Exception as e:  # noqa: BLE001
        s.errors.append(f"certificate: {e}")
    return s


def gather_portal(portal, *, read_cert=None) -> PortalSecurity:
    p = PortalSecurity(portal.base)
    try:
        parse_portal_config(portal.call("security/config"), p)
    except Exception as e:  # noqa: BLE001
        p.errors.append(f"portaladmin/security/config: {e}")
    try:
        parse_portal_self(portal.sharing("portals/self"), p)
    except Exception as e:  # noqa: BLE001
        p.errors.append(f"sharing/rest/portals/self: {e}")
    if read_cert is None:
        from .server import read_certificate as read_cert
    try:
        p.certificate = read_cert(portal.base)
    except Exception as e:  # noqa: BLE001
        p.errors.append(f"certificate: {e}")
    return p


# --------------------------------------------------------------- evaluation


def _f(code, sev, title, detail="", esri=None, **ev) -> Finding:
    if esri:
        ev["esri"] = esri
    return Finding(code, sev, title, detail, ev)


def evaluate_server(s: ServerSecurity, now: datetime) -> list[Finding]:
    out: list[Finding] = []

    # ESC001 HTTPS only (SS01), TLS versions, HSTS
    if s.protocol == "HTTPS":
        out.append(_f("ESC001", Severity.OK, "HTTPS only", esri="SS01"))
    elif s.protocol:
        out.append(
            _f(
                "ESC001",
                Severity.FAIL,
                f"Protocol is {s.protocol}",
                "Tokens and credentials can cross the network in clear text. Set the "
                "protocol to HTTPS in security/config/update; HTTP calls are then redirected.",
                esri="SS01",
                protocol=s.protocol,
            )
        )
    weak = sorted(set(s.https_protocols or []) & WEAK_TLS)
    if weak:
        out.append(
            _f(
                "ESC001",
                Severity.WARN,
                f"Old TLS versions enabled: {', '.join(weak)}",
                "TLS 1.2 and 1.3 are the defaults. Remove the old versions from httpsProtocols "
                "unless a named client still needs them.",
                protocols=s.https_protocols,
            )
        )
    if s.protocol == "HTTPS" and s.hsts is False:
        out.append(
            _f(
                "ESC001",
                Severity.INFO,
                "HSTS is off",
                "With HTTPS only, turning on HSTSEnabled tells browsers never to try HTTP.",
            )
        )

    # ESC002 standardized queries (SS02), legacy URL parser
    if s.standardized_queries is False:
        out.append(
            _f(
                "ESC002",
                Severity.FAIL,
                "Standardized queries are off",
                "Standardized queries guard against SQL injection through where clauses. "
                "Turn standardizedQueries back on in system/properties.",
                esri="SS02",
            )
        )
    elif s.standardized_queries:
        out.append(_f("ESC002", Severity.OK, "Standardized queries enforced", esri="SS02"))
    if s.legacy_url_parser:
        out.append(
            _f(
                "ESC002",
                Severity.WARN,
                "The legacy URL parser is allowed",
                "allowLegacyURLParser accepts request URLs the current parser rejects. Turn it "
                "off once no client needs it.",
            )
        )

    # ESC003 token requests (SS03, SS04)
    if s.token_get:
        out.append(
            _f(
                "ESC003",
                Severity.FAIL,
                "Tokens can be requested with GET",
                "Usernames and passwords then appear in URLs, proxy logs and browser history. "
                "Set allowHttpGet to false in security/tokens.",
                esri="SS03",
            )
        )
    if s.token_post_query:
        out.append(
            _f(
                "ESC003",
                Severity.FAIL,
                "Tokens can be requested with credentials in the query string",
                "Set allowHttpPostQueryParams to false in security/tokens.",
                esri="SS04",
            )
        )
    if s.token_get is False and s.token_post_query is False:
        out.append(
            _f("ESC003", Severity.OK, "Token requests need POST with a body", esri="SS03/SS04")
        )

    # ESC004 services directory (SS07), cross-domain (SS08)
    if s.services_directory:
        out.append(
            _f(
                "ESC004",
                Severity.WARN,
                "The REST services directory is browsable",
                "It lists every service to anyone who can reach the site. Turn it off in "
                "production (system/handlers/rest/servicesdirectory/edit, enabled=false).",
                esri="SS07",
            )
        )
    elif s.services_directory is False:
        out.append(_f("ESC004", Severity.OK, "Services directory is off", esri="SS07"))
    if s.allowed_origins is not None:
        if s.allowed_origins.strip() in ("", "*"):
            out.append(
                _f(
                    "ESC004",
                    Severity.WARN,
                    "Cross-domain requests are allowed from any site",
                    "Set allowedOrigins to the web apps that need this server.",
                    esri="SS08",
                )
            )
        else:
            out.append(
                _f(
                    "ESC004",
                    Severity.OK,
                    "Cross-domain requests limited to listed origins",
                    esri="SS08",
                    origins=s.allowed_origins,
                )
            )

    # ESC005 Web Adaptors over HTTPS (SS10), admin through port 6080, virtual dirs
    if s.web_adaptors:
        http = [u for u in s.web_adaptors if u.lower().startswith("http://")]
        if http:
            out.append(
                _f(
                    "ESC005",
                    Severity.WARN,
                    f"{len(http)} Web Adaptor(s) registered over HTTP",
                    ", ".join(http) + ". Register them with their HTTPS URL.",
                    esri="SS10",
                )
            )
        else:
            out.append(_f("ESC005", Severity.OK, "Web Adaptors registered over HTTPS", esri="SS10"))
    if s.direct_access and s.web_adaptors:
        out.append(
            _f(
                "ESC005",
                Severity.INFO,
                "Administrators can still reach the server directly",
                "allowDirectAccess is true, so the admin API answers on the server port as well "
                "as through the Web Adaptor. Set it to false, or limit allowedAdminAccessIPs, "
                "if every administrator can go through the Web Adaptor.",
                adminIPs=s.admin_ips,
            )
        )
    if s.virtual_dirs_secured is False:
        out.append(
            _f(
                "ESC005",
                Severity.INFO,
                "Output, job and input directories do not require sign-in",
                "With virtualDirsSecurityEnabled false, files written to arcgisoutput, "
                "arcgisjobs and arcgisinput can be fetched by URL. Turn it on if secured "
                "services write there.",
            )
        )

    # ESC006 primary site administrator (SS11)
    if s.psa_disabled is False:
        out.append(
            _f(
                "ESC006",
                Severity.WARN,
                "The primary site administrator account is enabled",
                "It cannot be locked out and is not in the identity store. Disable it once "
                "another administrator works (security/psa/disable); it can be re-enabled from "
                "the machine if needed.",
                esri="SS11",
            )
        )
    elif s.psa_disabled:
        out.append(_f("ESC006", Severity.OK, "Primary site administrator disabled", esri="SS11"))

    # ESC007 certificate (SS14)
    out += _cert(s.certificate, now, "ESC007", "SS14")

    for e in s.errors:
        out.append(_f("ESC000", Severity.WARN, "Part of the check could not run", e))
    return out


def evaluate_portal(p: PortalSecurity, now: datetime) -> list[Finding]:
    out: list[Finding] = []

    # ESC011 HTTPS only (PS04)
    if p.all_ssl is False:
        out.append(
            _f(
                "ESC011",
                Severity.FAIL,
                "The portal allows HTTP",
                "Turn on HTTPS only for all communication (allSSL) in the portal security "
                "settings, and use HTTPS in the Web Adaptor.",
                esri="PS04",
            )
        )
    elif p.all_ssl:
        out.append(_f("ESC011", Severity.OK, "HTTPS only", esri="PS04"))

    # ESC012 services directory (PS03)
    if p.services_directory_disabled is False:
        out.append(
            _f(
                "ESC012",
                Severity.WARN,
                "The portal services directory is browsable",
                "Set disableServicesDirectory to true in portaladmin/security/config/update.",
                esri="PS03",
            )
        )
    elif p.services_directory_disabled:
        out.append(_f("ESC012", Severity.OK, "Portal services directory is off", esri="PS03"))

    # ESC013 anonymous access and public sharing (PS06)
    if p.access == "public":
        out.append(
            _f(
                "ESC013",
                Severity.INFO,
                "Anonymous access is on",
                "Anyone who can reach the portal can see content shared with Everyone. Fine "
                "for a public site; on an internal one, turn it off."
                + (" Members can also share publicly." if p.can_share_public else ""),
                esri="PS06",
            )
        )
    elif p.access == "private":
        out.append(_f("ESC013", Severity.OK, "Anonymous access is off", esri="PS06"))

    # ESC014 cross-domain (PS09)
    if p.allowed_origins is not None:
        if not p.allowed_origins or "*" in p.allowed_origins:
            out.append(
                _f(
                    "ESC014",
                    Severity.WARN,
                    "Cross-domain requests are allowed from any site",
                    "List the web apps that need the portal in allowed origins.",
                    esri="PS09",
                )
            )
        else:
            out.append(
                _f(
                    "ESC014",
                    Severity.OK,
                    f"Cross-domain requests limited to {len(p.allowed_origins)} origin(s)",
                    esri="PS09",
                )
            )

    # ESC015 accounts created at first sign-in
    if p.auto_accounts:
        out.append(
            _f(
                "ESC015",
                Severity.INFO,
                "Accounts are created automatically at first enterprise sign-in",
                "Anyone the identity provider lets in becomes a member, with the default user "
                "type and role. Check that those defaults are the least you would give.",
            )
        )

    # ESC016 certificate (PS08)
    out += _cert(p.certificate, now, "ESC016", "PS08")

    for e in p.errors:
        out.append(_f("ESC000", Severity.WARN, "Part of the check could not run", e))
    return out


def _cert(cert: Certificate | None, now: datetime, code: str, esri: str) -> list[Finding]:
    found = certificate_findings(cert, now, SERVER_DEFAULTS, code, code)
    return [
        Finding(f.code, f.severity, f.title, f.detail, {**f.evidence, "esri": esri}) for f in found
    ]


def not_checked(portal: bool) -> list[Finding]:
    items = NOT_CHECKED_PORTAL if portal else NOT_CHECKED_SERVER
    return [_f("ESC099", Severity.INFO, f"{k} not checked", v, esri=k) for k, v in items.items()]

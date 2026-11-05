"""egisops command line.

    egisops server-health --url https://gis.example.com/arcgis --user siteadmin
    egisops services      --url https://gis.example.com/arcgis --user siteadmin
    egisops logs          --url https://gis.example.com/arcgis --hours 24
    EGISOPS_TOKEN=... egisops server-health --url ... --json

Credentials: EGISOPS_TOKEN, or a user (--user or EGISOPS_USER) with EGISOPS_PASSWORD or
an interactive prompt. There is no password option, and TLS verification cannot be
turned off; use --ca-file for a private CA.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from . import __version__
from .findings import Finding, Severity, exit_code

MARK = {Severity.OK: "ok  ", Severity.INFO: "info", Severity.WARN: "WARN", Severity.FAIL: "FAIL"}


def render_findings(findings: list[Finding], quiet: bool = False) -> list[str]:
    lines = []
    for f in findings:
        if quiet and f.severity == Severity.OK:
            continue
        lines.append(f"  [{MARK[f.severity]}] {f.code}  {f.title}")
        lines.extend(f"               {d}" for d in f.detail.splitlines())
    return lines


def emit(args, header: list[str], findings: list[Finding], extra: dict) -> int:
    if args.json:
        print(
            json.dumps(
                {**extra, "findings": [f.to_dict() for f in findings]}, indent=2, default=str
            )
        )
    else:
        print("\n".join(header + [""] + render_findings(findings, args.quiet)))
    return exit_code(findings)


def connect(args):
    import getpass
    import ssl

    from .client import ServerAdmin, credentials_from_env, urllib_transport

    context = ssl.create_default_context(cafile=args.ca_file) if args.ca_file else None
    admin = ServerAdmin(args.url, urllib_transport(context=context))
    if args.no_login:
        return admin
    user, password, token = credentials_from_env(args.user)
    if token:
        admin.token = token
    elif user:
        if not password and sys.stdin.isatty():
            password = getpass.getpass(f"Password for {user}: ")
        if password:
            admin.login(user, password)
    return admin


def cmd_server_health(args) -> int:
    from . import server

    admin = connect(args)
    snap = server.gather(admin)
    findings = server.evaluate(snap, datetime.now(UTC))
    header = [
        f"server-health  {snap.base_url}"
        + (f"  ArcGIS Server {snap.full_version}" if snap.full_version else "")
    ]
    return emit(args, header, findings, {"url": snap.base_url, "version": snap.full_version})


def cmd_services(args) -> int:
    from . import services

    admin = connect(args)
    snap = services.gather(admin, folders=args.folder)
    findings = services.evaluate(snap)
    header = [f"services  {admin.base}  {len(snap.services)} service(s)"]
    return emit(args, header, findings, {"url": admin.base, "folders": snap.folders})


def cmd_logs(args) -> int:
    from . import logs

    admin = connect(args)
    snap = logs.gather(
        admin, datetime.now(UTC), hours=args.hours, level=args.level, max_pages=args.max_pages
    )
    findings = logs.evaluate(snap)
    header = [
        f"logs  {admin.base}  {args.level} and worse, last {args.hours:g} hours, "
        f"{len(snap.entries)} entries read"
    ]
    return emit(args, header, findings, {"url": admin.base, "entries": len(snap.entries)})


def _site_args(sp, *, allow_no_login: bool = False):
    sp.add_argument("--url", required=True, help="Server root, e.g. https://gis.example.com/arcgis")
    sp.add_argument(
        "--user", help="Admin user (or EGISOPS_USER); password from EGISOPS_PASSWORD or a prompt"
    )
    if allow_no_login:
        sp.add_argument("--no-login", action="store_true", help="Public checks only")
    else:
        sp.set_defaults(no_login=False)
    sp.add_argument("--ca-file", help="CA bundle for a private certificate authority")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--quiet", action="store_true", help="Hide passing checks")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="egisops", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"egisops {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sh = sub.add_parser("server-health", help="Health check, machines, license, TLS certificate")
    _site_args(sh, allow_no_login=True)
    sh.set_defaults(func=cmd_server_health)

    sv = sub.add_parser("services", help="Stopped services and saturated instance pools")
    _site_args(sv)
    sv.add_argument(
        "--folder",
        action="append",
        help="Only this folder (repeatable; use '' for root). Default: all",
    )
    sv.set_defaults(func=cmd_services)

    lg = sub.add_parser("logs", help="SEVERE log entries grouped by source and code")
    _site_args(lg)
    lg.add_argument("--hours", type=float, default=24)
    lg.add_argument(
        "--level",
        default="SEVERE",
        choices=["SEVERE", "WARNING", "INFO", "FINE", "VERBOSE", "DEBUG"],
    )
    lg.add_argument("--max-pages", type=int, default=5)
    lg.set_defaults(func=cmd_logs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""egisops command line.

    egisops server-health --url https://gis.example.com/arcgis --user siteadmin
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="egisops", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"egisops {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sh = sub.add_parser("server-health", help="Health check, machines, license, TLS certificate")
    sh.add_argument("--url", required=True, help="Server root, e.g. https://gis.example.com/arcgis")
    sh.add_argument(
        "--user", help="Admin user (or EGISOPS_USER); password from EGISOPS_PASSWORD or a prompt"
    )
    sh.add_argument("--no-login", action="store_true", help="Public checks only")
    sh.add_argument("--ca-file", help="CA bundle for a private certificate authority")
    sh.add_argument("--json", action="store_true")
    sh.add_argument("--quiet", action="store_true", help="Hide passing checks")
    sh.set_defaults(func=cmd_server_health)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

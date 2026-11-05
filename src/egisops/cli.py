"""egisops command line.

    egisops server-health --url https://gis.example.com/arcgis --user siteadmin
    egisops services      --url https://gis.example.com/arcgis --user siteadmin
    egisops logs          --url https://gis.example.com/arcgis --hours 24
    egisops portal-health --url https://gis.example.com/portal --user portaladmin
    egisops datastore     --url https://gis.example.com/server --user siteadmin
    egisops stack-compat  --url https://gis.example.com/server --portal-version 11.5 \
                          --engine-version 16.8 --postgis 3.5.2 --target 12.1
    egisops backup-check  --properties webgisdr.properties --backups D:\\backups --rpo-hours 24
    egisops security      --url https://gis.example.com/server --user siteadmin
    egisops security      --url https://gis.example.com/portal --portal --user portaladmin
    egisops incident      --kind token --server https://gis.example.com/server --federal
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


def connect(args, portal: bool = False):
    import getpass
    import ssl

    from .client import PortalAdmin, ServerAdmin, credentials_from_env, urllib_transport

    context = ssl.create_default_context(cafile=args.ca_file) if args.ca_file else None
    cls = PortalAdmin if portal else ServerAdmin
    admin = cls(args.url, urllib_transport(context=context))
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


def cmd_portal_health(args) -> int:
    from . import portal

    p = connect(args, portal=True)
    snap = portal.gather(p)
    findings = portal.evaluate(snap, datetime.now(UTC))
    header = [
        f"portal-health  {snap.base_url}"
        + (f"  Portal for ArcGIS {snap.version}" if snap.version else "")
    ]
    return emit(args, header, findings, {"url": snap.base_url, "version": snap.version})


def cmd_datastore(args) -> int:
    from . import datastore

    admin = connect(args)
    snap = datastore.gather(admin, machine=args.machine)
    findings = datastore.evaluate(
        snap, datetime.now(UTC), datastore.Thresholds(backup_warn_days=args.backup_days)
    )
    header = [f"datastore  {admin.base}  {len(snap.stores)} data store(s)"]
    return emit(
        args, header, findings, {"url": admin.base, "stores": [d.path for d in snap.stores]}
    )


def cmd_stack_compat(args) -> int:
    from . import stack

    admin = None if args.server_version else connect(args)
    snap = stack.gather(
        admin,
        portal_version=args.portal_version,
        server_version=args.server_version,
        engine_version=args.engine_version,
        postgis_version=args.postgis,
        pro_version=args.pro_version,
        target=args.target,
        machine=args.machine,
    )
    db, pro = stack.rdsops_hooks()
    findings = stack.evaluate(snap, db, pro)
    header = [
        "stack-compat  "
        + ", ".join(f"{c.name} {c.version}" for c in snap.components)
        + (f"  RDS for PostgreSQL {snap.engine_version}" if snap.engine_version else "")
    ]
    extra = {"components": {c.name: c.version for c in snap.components}}
    return emit(args, header, findings, extra)


def cmd_backup_check(args) -> int:
    from . import backup

    snap = backup.gather(args.properties, backups_dir=args.backups, outputs=args.output_file or ())
    findings = backup.evaluate(snap, datetime.now(UTC), backup.Thresholds(rpo_hours=args.rpo_hours))
    header = [
        f"backup-check  {args.properties}"
        + (f"  backups in {snap.backups_dir}" if snap.backups_dir else "")
        + f"  RPO {args.rpo_hours:g}h"
    ]
    extra = {
        "properties": backup.safe_properties(snap.properties),
        "backups_dir": snap.backups_dir,
        "backups": len(snap.backups or []),
    }
    return emit(args, header, findings, extra)


def cmd_security(args) -> int:
    from . import security

    now = datetime.now(UTC)
    if args.portal:
        snap = security.gather_portal(connect(args, portal=True))
        findings = security.evaluate_portal(snap, now)
    else:
        snap = security.gather_server(connect(args))
        findings = security.evaluate_server(snap, now)
    if args.verbose:
        findings += security.not_checked(args.portal)
    kind = "portal" if args.portal else "server"
    header = [f"security  {snap.base_url}  ({kind}, against Esri's {kind}Scan checks)"]
    return emit(args, header, findings, {"url": snap.base_url})


def cmd_incident(args) -> int:
    from . import incident

    ctx = incident.IncidentContext(
        kind=args.kind,
        server=args.server or "https://<server>/arcgis",
        portal=args.portal_url,
        federal=args.federal,
        user=args.account,
        service=args.service,
        item=args.item,
        machine=args.machine,
        since=datetime.fromisoformat(args.since) if args.since else None,
        now=datetime.now(UTC),
        backup_age_hours=args.backup_age_hours,
        rpo_hours=args.rpo_hours,
        psa_enabled=True if args.psa_enabled else None,
    )
    pb = incident.playbook(ctx)
    if args.json:
        print(json.dumps(pb.to_dict(), indent=2, default=str))
        return exit_code(pb.findings)
    header = [
        f"incident  {args.kind}: {incident.KINDS[args.kind]}",
        f"  server {ctx.server}"
        + (f"  portal {ctx.portal}" if ctx.portal else "")
        + ("  federal" if args.federal else ""),
    ]
    code = emit(args, header, pb.findings, {})
    print("\n  Playbook (nothing here has been run)")
    phase = None
    for n, st in enumerate(pb.steps, 1):
        if st.phase != phase:
            phase = st.phase
            print(f"\n  {phase}")
        print(f"  {n:>2}. {st.title}")
        if st.command:
            print(f"      {'$' if incident.is_command(st.command) else '>'} {st.command}")
        if st.why:
            print(f"      {st.why}")
    return code


def _site_args(sp, *, allow_no_login: bool = False):
    sp.add_argument(
        "--url",
        required=True,
        help="Site root, e.g. https://gis.example.com/arcgis (Server) or .../portal (Portal)",
    )
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

    ph = sub.add_parser(
        "portal-health", help="Portal health, machines, license, federation, search index"
    )
    _site_args(ph, allow_no_login=True)
    ph.set_defaults(func=cmd_portal_health)

    ds = sub.add_parser("datastore", help="ArcGIS Data Store validation and backup age")
    _site_args(ds)
    ds.add_argument(
        "--machine", help="A data store machine name, if the data item does not list one"
    )
    ds.add_argument(
        "--backup-days", type=float, default=7, help="Warn when the newest backup is older"
    )
    ds.set_defaults(func=cmd_datastore)

    sc = sub.add_parser(
        "stack-compat",
        help="Portal, Server, Data Store, RDS geodatabase and Pro versions together; upgrade plan",
    )
    sc.add_argument("--url", help="Hosting server root (omit with --server-version)")
    sc.add_argument("--user", help="Admin user (or EGISOPS_USER)")
    sc.add_argument("--ca-file")
    sc.set_defaults(no_login=False)
    sc.add_argument("--server-version", help="Use this instead of reading the server")
    sc.add_argument("--portal-version", help="Portal for ArcGIS version, e.g. 11.5")
    sc.add_argument("--machine", help="A data store machine name, as for datastore")
    sc.add_argument("--engine-version", help="RDS for PostgreSQL version, e.g. 16.8")
    sc.add_argument("--postgis", help="PostGIS version, e.g. 3.5.2")
    sc.add_argument("--pro-version", help="ArcGIS Pro version in use")
    sc.add_argument("--target", help="Plan an upgrade to this ArcGIS Enterprise release")
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--quiet", action="store_true", help="Hide passing checks")
    sc.set_defaults(func=cmd_stack_compat)

    bk = sub.add_parser(
        "backup-check", help="WebGISDR properties lint and newest backup against an RPO (offline)"
    )
    bk.add_argument("--properties", required=True, help="The webgisdr.properties file")
    bk.add_argument("--backups", help="Folder holding .webgissite files (default: BACKUP_LOCATION)")
    bk.add_argument(
        "--output-file",
        action="append",
        help="JSON written by webgisdr --output (repeatable; the newest is scored)",
    )
    bk.add_argument("--rpo-hours", type=float, default=24, help="Recovery point objective")
    bk.add_argument("--json", action="store_true")
    bk.add_argument("--quiet", action="store_true", help="Hide passing checks")
    bk.set_defaults(func=cmd_backup_check)

    se = sub.add_parser("security", help="Settings against Esri's serverScan and portalScan checks")
    _site_args(se)
    se.add_argument("--portal", action="store_true", help="The URL is a portal")
    se.add_argument("--verbose", action="store_true", help="Also list scanner checks not read")
    se.set_defaults(func=cmd_security)

    from .incident import KINDS

    ic = sub.add_parser("incident", help="Contingency playbook for a security incident (prints)")
    ic.add_argument("--kind", required=True, choices=sorted(KINDS))
    ic.add_argument("--server", help="Server root, e.g. https://gis.example.com/server")
    ic.add_argument("--portal-url", help="Portal root, if the server is federated")
    ic.add_argument("--account", help="The account involved")
    ic.add_argument("--service", help="folder/name.Type, e.g. Utilities/Hydrants.MapServer")
    ic.add_argument("--item", help="Portal item id")
    ic.add_argument("--machine", help="Site machine name")
    ic.add_argument("--since", help="Last known good time, ISO 8601")
    ic.add_argument("--backup-age-hours", type=float, help="Age of the newest webgisdr backup")
    ic.add_argument("--rpo-hours", type=float, default=24)
    ic.add_argument("--psa-enabled", action="store_true", help="The PSA account is enabled")
    ic.add_argument("--federal", action="store_true", help="Federal system: CISA one-hour report")
    ic.add_argument("--json", action="store_true")
    ic.add_argument("--quiet", action="store_true")
    ic.set_defaults(func=cmd_incident)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

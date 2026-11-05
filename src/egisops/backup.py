"""backup-check: is the WebGISDR backup set up correctly, and is there a recent one?

Works offline, on files: the ``webgisdr.properties`` file, the backup folder, and the JSON
files the tool writes with ``--output``. ``gather`` reads them; ``evaluate`` is pure.
Secret values (passwords, keys, tokens) are parsed only to see whether they are set and
encrypted. They never appear in a finding.

Sources: Esri's "WebGISDR tool properties file", "WebGISDR tool output file", "Create an
ArcGIS Enterprise backup" and "ArcGIS Enterprise backups" pages (docs/SCOPE.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .findings import Finding, Severity


@dataclass(frozen=True)
class Thresholds:
    rpo_hours: float = 24.0
    fail_multiple: float = 3.0  # older than this many RPOs is a failure, not a warning


DEFAULTS = Thresholds()

SECRET = re.compile(r"PASSWORD|SECRET|ACCESSKEY|ACCOUNT_KEY|SAS_TOKEN", re.I)
PATH_KEYS = ("SHARED_LOCATION", "BACKUP_LOCATION")
MODES = ("backup", "full", "incremental")
PROVIDERS = {"filesystem": "FileSystem", "amazons3": "AmazonS3", "azureblob": "AzureBlob"}


@dataclass(frozen=True)
class BackupFile:
    name: str
    modified: datetime
    size: int


@dataclass(frozen=True)
class Component:
    name: str
    status: str
    store_type: str | None = None
    url: str | None = None
    messages: str = ""


@dataclass(frozen=True)
class RunResult:
    path: str
    written: datetime | None  # when the output file was written: the end of the run
    operation: str | None
    status: str | None
    backup_location: str | None
    elapsed: str | None
    messages: str = ""
    components: tuple[Component, ...] = ()


@dataclass
class BackupSnapshot:
    properties_path: str | None
    properties: dict[str, str] = field(default_factory=dict)  # decoded values
    raw: dict[str, str] = field(default_factory=dict)  # values as written in the file
    backups_dir: str | None = None
    backups: list[BackupFile] | None = None  # None when no folder was read
    runs: list[RunResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------- parsing


def _decode(raw: str) -> str:
    """Java .properties escapes: a backslash escapes the next character, so an unescaped
    single backslash in a path is dropped, which is why Esri says to double them."""
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            out.append({"t": "\t", "n": "\n", "r": "\r", "f": "\f"}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_properties(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """(decoded, raw) values by key. Comments start with # or !. Keys are case-sensitive
    in the file; Esri's examples use upper case."""
    decoded, raw = {}, {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line[0] in "#!":
            continue
        while (len(line) - len(line.rstrip("\\"))) % 2 == 1 and i < len(lines):
            line = line[:-1] + lines[i].strip()  # line continuation
            i += 1
        m = re.match(r"([^=:\s]+)\s*[=:\s]\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        raw[key] = value
        decoded[key] = _decode(value)
    return decoded, raw


def parse_output(path: str, payload: dict, written: datetime | None) -> RunResult:
    comps = tuple(
        Component(
            c.get("name", "?"),
            str(c.get("status", "")).lower(),
            c.get("storeType"),
            c.get("URL"),
            str(c.get("messages") or ""),
        )
        for c in payload.get("results") or []
    )
    return RunResult(
        path=path,
        written=written,
        operation=payload.get("operation"),
        status=str(payload.get("status", "")).lower() or None,
        backup_location=payload.get("backupLocation"),
        elapsed=payload.get("elapsedTime"),
        messages=str(payload.get("messages") or ""),
        components=comps,
    )


NAME_TIME = re.compile(r"(\d{8})-(\d{6})-[A-Za-z]+-([A-Za-z]+)\.webgissite$")


def mode_from_name(name: str) -> str | None:
    """Esri's sample name is 20221123-133229-PST-FULL.webgissite."""
    m = NAME_TIME.search(name)
    return m.group(3).lower() if m else None


# --------------------------------------------------------------- gathering


def gather(properties_path: str, backups_dir: str | None = None, outputs=()) -> BackupSnapshot:
    import json
    import os

    snap = BackupSnapshot(properties_path)
    try:
        with open(properties_path, encoding="utf-8-sig") as fh:
            snap.properties, snap.raw = parse_properties(fh.read())
    except OSError as e:
        snap.errors.append(f"properties file: {e.strerror or e}")

    folder = backups_dir
    loc = snap.properties.get("BACKUP_LOCATION", "")
    if folder is None and provider(snap.properties) == "FileSystem" and loc:
        if os.path.isdir(loc):
            folder = loc
        elif os.path.isdir(os.path.dirname(loc)):
            folder = os.path.dirname(loc)
        else:
            snap.errors.append(
                "BACKUP_LOCATION is not readable from this machine. Pass --backups with a "
                "folder this machine can read to check backup age."
            )
    if folder:
        snap.backups_dir = folder
        try:
            files = []
            for entry in os.scandir(folder):
                if entry.is_file() and entry.name.lower().endswith(".webgissite"):
                    st = entry.stat()
                    files.append(
                        BackupFile(entry.name, datetime.fromtimestamp(st.st_mtime, UTC), st.st_size)
                    )
            snap.backups = files
        except OSError as e:
            snap.errors.append(
                f"backup folder {folder}: {e.strerror or e}. Pass --backups with a folder "
                "this machine can read."
            )
    for path in outputs:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                payload = json.load(fh)
            written = datetime.fromtimestamp(os.path.getmtime(path), UTC)
            snap.runs.append(parse_output(path, payload, written))
        except (OSError, ValueError) as e:
            snap.errors.append(f"output file {path}: {e}")
    return snap


# --------------------------------------------------------------- evaluating


def provider(props: dict) -> str | None:
    p = props.get("BACKUP_STORE_PROVIDER") or props.get("BACKUP_PROVIDER")
    return PROVIDERS.get((p or "").strip().lower(), p or None)


def _get(props: dict, *keys) -> str:
    """First non-empty value among spellings. Esri's page uses both AZURE_BLOB_CREDENTIALTYPE
    and AZURE_BLOB_CREDENTIAL_TYPE, for example."""
    for k in keys:
        v = props.get(k, "").strip()
        if v:
            return v
    return ""


def _true(v: str) -> bool:
    return v.strip().lower() == "true"


def _age(hours: float) -> str:
    return f"{hours:.1f} hours" if hours < 48 else f"{hours / 24:.1f} days"


def _lint(s: BackupSnapshot) -> list[Finding]:
    p = s.properties
    out: list[Finding] = []

    # BAK001 required properties
    missing = [k for k in ("PORTAL_ADMIN_URL", "PORTAL_ADMIN_USERNAME") if not _get(p, k)]
    if not _get(p, "PORTAL_ADMIN_PASSWORD") and not _true(p.get("IS_PORTAL_PKI_AUTHENTICATED", "")):
        missing.append("PORTAL_ADMIN_PASSWORD")
    prov = provider(p)
    need: list[tuple[str, ...]] = []
    if prov == "FileSystem":
        need = [("BACKUP_LOCATION",)]
    elif prov == "AmazonS3":
        need = [("S3_BUCKET",), ("S3_REGION",), ("S3_CREDENTIALTYPE",)]
        if _get(p, "S3_CREDENTIALTYPE").lower() == "accesskey":
            need += [("S3_ACCESSKEY",), ("S3_SECRETKEY",)]
    elif prov == "AzureBlob":
        ctype = _get(p, "AZURE_BLOB_CREDENTIALTYPE", "AZURE_BLOB_CREDENTIAL_TYPE")
        need = [
            ("AZURE_BLOB_ACCOUNT_NAME",),
            ("AZURE_BLOB_CONTAINER_NAME",),
            ("AZURE_BLOB_CREDENTIALTYPE", "AZURE_BLOB_CREDENTIAL_TYPE"),
            ("AZURE_BLOB_ACCOUNT_ENDPOINT_SUFFIX",),
        ]
        need += {
            "accesskey": [("AZURE_BLOB_ACCOUNT_KEY",)],
            "serviceprincipal": [
                ("AZURE_BLOB_SP_TENANT_ID",),
                ("AZURE_BLOB_SP_CLIENT_ID",),
                ("AZURE_BLOB_SP_CLIENT_SECRET_KEY",),
            ],
            "userassignedidentity": [("AZURE_BLOB_USER_MI_CLIENT_ID",)],
            "sastoken": [("AZURE_BLOB_SAS_TOKEN",)],
        }.get(ctype.lower(), [])
    missing += [keys[0] for keys in need if not _get(p, *keys)]
    if not prov:
        out.append(
            Finding(
                "BAK001",
                Severity.FAIL,
                "BACKUP_STORE_PROVIDER is not set",
                "Set it to FileSystem, AmazonS3 or AzureBlob, then the properties that "
                "provider needs.",
            )
        )
    elif prov not in PROVIDERS.values():
        out.append(
            Finding(
                "BAK001",
                Severity.FAIL,
                f"Unknown backup store provider {prov!r}",
                "Use FileSystem, AmazonS3 or AzureBlob.",
                {"provider": prov},
            )
        )
    if missing:
        out.append(
            Finding(
                "BAK001",
                Severity.FAIL,
                f"Required properties missing: {', '.join(missing)}",
                "The WebGISDR tool cannot run an export without them.",
                {"missing": missing},
            )
        )
    elif prov in PROVIDERS.values():
        out.append(Finding("BAK001", Severity.OK, f"Properties complete for {prov}"))

    # BAK002 the portal URL the tool connects to
    url = _get(p, "PORTAL_ADMIN_URL")
    if url:
        if not url.lower().startswith("https://"):
            out.append(
                Finding(
                    "BAK002",
                    Severity.FAIL,
                    "PORTAL_ADMIN_URL is not HTTPS",
                    "Use the portal machine's HTTPS admin URL, e.g. "
                    "https://portal.example.com:7443/arcgis.",
                    {"url": url},
                )
            )
        elif not re.match(r"https://[^/]+:7443/", url + "/"):
            out.append(
                Finding(
                    "BAK002",
                    Severity.WARN,
                    "PORTAL_ADMIN_URL does not point at a portal machine on port 7443",
                    "Esri's format is https://<portal machine FQDN>:7443/arcgis. The tool connects "
                    "to the machine directly; a web adaptor or load balancer URL may not work.",
                    {"url": url},
                )
            )

    # BAK003 backslashes in paths must be doubled
    for key in PATH_KEYS:
        raw = s.raw.get(key, "")
        if re.search(r"(?<!\\)\\(?!\\)", raw.replace("\\\\", "")):
            out.append(
                Finding(
                    "BAK003",
                    Severity.FAIL,
                    f"{key} has single backslashes",
                    f"The properties format drops them: this path reads as {p.get(key)!r}. "
                    "Double every backslash, e.g. \\\\\\\\fileserver\\\\backups.",
                    {"property": key},
                )
            )

    # BAK004 secrets stored in plain text, and credential choices
    pairs = [
        ("PORTAL_ADMIN_PASSWORD", "PORTAL_ADMIN_PASSWORD_ENCRYPTED"),
        ("S3_SECRETKEY", "S3_ENCRYPTED"),
        ("AZURE_BLOB_ACCOUNT_KEY", "AZURE_BLOB_ACCOUNT_KEY_ENCRYPTED"),
        ("AZURE_BLOB_SP_CLIENT_SECRET_KEY", "AZURE_BLOB_SP_CLIENT_SECRET_KEY_ENCRYPTED"),
        ("AZURE_BLOB_SAS_TOKEN", "AZURE_BLOB_SAS_TOKEN_ENCRYPTED"),
        ("PORTAL_CLIENT_CERTIFICATE_PASSWORD", "PORTAL_CLIENT_CERTIFICATE_PASSWORD_ENCRYPTED"),
    ]
    plain = [secret for secret, flag in pairs if _get(p, secret) and not _true(p.get(flag, ""))]
    if plain:
        out.append(
            Finding(
                "BAK004",
                Severity.WARN,
                f"Stored in plain text: {', '.join(plain)}",
                "WebGISDR encrypts these the first time it runs with the file. Run it once (or "
                "check that it has run), and keep the file readable only by the account that "
                "runs backups.",
                {"properties": plain},
            )
        )
    if prov == "AmazonS3" and _get(p, "S3_CREDENTIALTYPE").lower() == "accesskey":
        out.append(
            Finding(
                "BAK004",
                Severity.INFO,
                "S3 is reached with an access key",
                "On EC2, S3_CREDENTIALTYPE = IAMRole uses the instance role instead of a "
                "long-lived key in a file.",
            )
        )
    if (
        prov == "AzureBlob"
        and _get(p, "AZURE_BLOB_CREDENTIALTYPE", "AZURE_BLOB_CREDENTIAL_TYPE").lower() == "sastoken"
    ):
        out.append(
            Finding(
                "BAK004",
                Severity.WARN,
                "Azure Blob is reached with a SAS token",
                "SAS tokens usually expire on a schedule; Esri does not recommend them for "
                "automated backups. Use a managed identity or service principal.",
            )
        )

    # BAK005 mode
    mode = _get(p, "BACKUP_RESTORE_MODE").lower() or "backup"
    if mode not in MODES:
        out.append(
            Finding(
                "BAK005",
                Severity.FAIL,
                f"Unknown BACKUP_RESTORE_MODE {mode!r}",
                "Use backup, full or incremental.",
            )
        )
    elif mode == "incremental":
        out.append(
            Finding(
                "BAK005",
                Severity.INFO,
                "Incremental mode",
                "Incremental backups need ArcGIS Data Store's scheduled relational backups with "
                "point-in-time recovery on, and a separate properties file running full mode. "
                "An incremental backup is only as good as the full one before it.",
            )
        )

    # BAK006 shared location
    if not _get(p, "SHARED_LOCATION") and url:
        out.append(
            Finding(
                "BAK006",
                Severity.INFO,
                "SHARED_LOCATION is blank",
                "Required when a federated ArcGIS Server is at 12.0 or earlier. Leave it blank "
                "only if every federated server is newer.",
            )
        )

    # BAK007 what a WebGISDR backup does not contain
    out.append(
        Finding(
            "BAK007",
            Severity.INFO,
            "Not in a WebGISDR backup: map and tile caches, referenced data, spatiotemporal store",
            "Back up arcgiscache directories, file and database data sources behind services, and "
            "the spatiotemporal big data store (backupdatastore) separately."
            + (
                " INCLUDE_OBJECT_STORE_CACHES is true: every backup carries all scene caches."
                if _true(p.get("INCLUDE_OBJECT_STORE_CACHES", ""))
                else ""
            ),
        )
    )
    return out


def evaluate(s: BackupSnapshot, now: datetime, t: Thresholds = DEFAULTS) -> list[Finding]:
    out = _lint(s) if s.properties else []

    # BAK010 newest backup against the recovery point objective
    if s.backups is not None:
        good = [b for b in s.backups if b.size > 0]
        empty = [b.name for b in s.backups if b.size == 0]
        if empty:
            out.append(
                Finding(
                    "BAK010",
                    Severity.WARN,
                    f"{len(empty)} empty backup file(s)",
                    ", ".join(empty[:5]) + ". A failed or interrupted export leaves these.",
                    {"files": empty},
                )
            )
        if not good:
            out.append(
                Finding(
                    "BAK010",
                    Severity.FAIL,
                    "No backup files found",
                    f"No .webgissite files in {s.backups_dir}. Nothing to restore from.",
                    {"folder": s.backups_dir},
                )
            )
        else:
            newest = max(good, key=lambda b: b.modified)
            hours = (now - newest.modified).total_seconds() / 3600
            sev = (
                Severity.FAIL
                if hours > t.rpo_hours * t.fail_multiple
                else Severity.WARN
                if hours > t.rpo_hours
                else Severity.OK
            )
            fulls = [b for b in good if mode_from_name(b.name) in ("full", "backup")]
            detail = (
                ""
                if sev == Severity.OK
                else f"Older than the {t.rpo_hours:g}-hour recovery point objective: a restore "
                f"today loses everything since {newest.modified:%Y-%m-%d %H:%M} UTC. Check the "
                "scheduled task that runs webgisdr --export."
            )
            if any(mode_from_name(b.name) == "incremental" for b in good) and fulls:
                last_full = max(fulls, key=lambda b: b.modified)
                detail = (detail + " " if detail else "") + f"Newest full backup: {last_full.name}."
            out.append(
                Finding(
                    "BAK010",
                    sev,
                    f"Newest backup {_age(hours)} old ({newest.name}, "
                    f"{newest.size / 1024**3:.1f} GB)",
                    detail,
                    {
                        "file": newest.name,
                        "modified": newest.modified.isoformat(),
                        "rpo_hours": t.rpo_hours,
                    },
                )
            )

    # BAK011 the last runs, from the --output files
    for r in sorted(s.runs, key=lambda r: r.written or datetime.min.replace(tzinfo=UTC))[-1:]:
        failed = [c for c in r.components if c.status != "success"]
        when = f" at {r.written:%Y-%m-%d %H:%M} UTC" if r.written else ""
        if r.status == "success" and not failed:
            out.append(
                Finding(
                    "BAK011",
                    Severity.OK,
                    f"Last WebGISDR run succeeded{when} ({r.elapsed or 'time not recorded'})",
                    "",
                    {"output": r.path, "backupLocation": r.backup_location},
                )
            )
        else:
            names = ", ".join(
                f"{c.name}{f' ({c.store_type})' if c.store_type else ''}" for c in failed
            )
            msgs = " ".join(
                m.rstrip(".") + "." for m in [r.messages, *(c.messages for c in failed)] if m
            )
            out.append(
                Finding(
                    "BAK011",
                    Severity.FAIL,
                    f"Last WebGISDR run failed{when}" + (f": {names}" if names else ""),
                    (msgs or "No message recorded.")
                    + " Fix the component and run the export again; the newest backup file may "
                    "not be complete.",
                    {"output": r.path, "failed": [c.name for c in failed]},
                )
            )
        if s.backups is not None and r.backup_location and r.status == "success":
            name = re.split(r"[\\/]", r.backup_location)[-1]
            if name and not any(b.name == name for b in s.backups):
                out.append(
                    Finding(
                        "BAK011",
                        Severity.WARN,
                        f"The last run's backup {name} is not in {s.backups_dir}",
                        "It was moved, deleted or written somewhere else. A restore from this "
                        "folder will take the newest file that is there.",
                        {"file": name},
                    )
                )

    for e in s.errors:
        out.append(Finding("BAK009", Severity.WARN, "Part of the check could not run", e))
    return out


def safe_properties(props: dict) -> dict:
    """Properties with every secret value replaced, for --json output."""
    return {
        k: ("<set>" if v and SECRET.search(k) and "ENCRYPTED" not in k else v)
        for k, v in props.items()
    }

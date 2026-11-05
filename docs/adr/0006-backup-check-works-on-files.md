# 0006. backup-check works on files, offline, and never repeats a secret

Status: accepted (2026-11-04)

## Context

ArcGIS Enterprise backups are made by the WebGISDR tool, which runs on the portal machine
with a `webgisdr.properties` file and writes a `.webgissite` file to a file share or to
cloud storage. There is no Administrator API resource that reports when the last WebGISDR
backup ran. What exists is on disk: the properties file, the backup files, and an
optional JSON output file the tool writes when run with `--output`.

The properties file holds the portal administrator password and, depending on the store,
cloud keys. WebGISDR encrypts them the first time it runs with the file; until then they
are plain text.

## Decision

- `backup-check` reads files only: the properties file, a backup folder, and any number of
  WebGISDR output files. It makes no network calls and needs no credentials.
- It lints the properties against Esri's documented keys for each store provider, checks
  path escaping, notes plain-text secrets, and scores the newest backup's age against a
  recovery point objective (`--rpo-hours`, default 24).
- "Newest" is the file with the latest modified time, because that is the one Esri says a
  folder restore picks. The name is only used to recognize full and incremental backups.
- Secret values are read only to know whether they are set. They never appear in a
  finding, and `--json` replaces them with `<set>`. A test checks the output of every
  fixture for Esri's example passwords.
- Esri's page spells some things two ways (`Filesystem` and `FileSystem`,
  `AZURE_BLOB_CREDENTIALTYPE` and `AZURE_BLOB_CREDENTIAL_TYPE`). Both are accepted, as in
  ADR 0004.

## Consequences

- Backups in S3 or Azure Blob are checked through the output files, or by pointing
  `--backups` at a synced copy; the tool does not list buckets (ADR 0002: standard library
  only).
- Run it on a schedule after the WebGISDR task, with `--output-file` pointing at that
  task's output, and the exit code says whether last night's backup is good.

# Changelog

## 0.5.0 (2026-11-04)

- `egisops stack-compat`: Portal, the hosting server and every ArcGIS Data Store on one
  release (FAIL when mixed, with Esri's upgrade order); the RDS for PostgreSQL geodatabase
  through rdsops `compat`; ArcGIS Pro against the companion version; and with `--target`,
  an upgrade plan: direct or interim path, backup first, order, features retired at 12.0
  (including the tile cache data store), and whether the geodatabase is supported at the
  target. Live from the server, or offline with `--server-version`.
- Optional extra `egisops[stack]` installs rdsops. Without it, the database side reports
  STK009 and the rest runs.
- ADR 0007: stack-compat uses rdsops for the database, and does not copy its matrix.

## 0.4.0 (2026-11-04)

- `egisops backup-check`: offline check of a WebGISDR setup. Lints `webgisdr.properties`
  (required keys for FileSystem, AmazonS3 and AzureBlob, portal URL, doubled backslashes,
  secrets still in plain text, access keys and SAS tokens, mode, shared location), scores
  the newest `.webgissite` against `--rpo-hours` (WARN past it, FAIL past three times it),
  and reads the JSON from `webgisdr --output` for the last run's per-component result.
- Secret values never appear in output; `--json` shows `<set>`.
- ADR 0006: backup-check works on files, offline, and never repeats a secret.

## 0.3.0 (2026-11-04)

- `egisops portal-health`: portal health check, site and license, each machine's
  readiness (one of two down warns, all down fails), soonest expiring user type or other
  entitlement, member license capacity and full user types, TLS certificate, federated
  server validation with a hosting server present, search index against stored content,
  version.
- `egisops datastore`: finds the managed ArcGIS Data Store items on the hosting server and
  runs the documented `validate` on each. Reads the machine list rather than trusting the
  overall health line; standby, registration and server connection, newest backup age
  (`--backup-days`, default 7), spatiotemporal cluster status. `--machine` when the data
  item does not list one.
- ADR 0005: Portal tokens travel in the `X-Esri-Authorization` header; data store machine
  names come from the item or `--machine`.
- Certificate findings shared between server-health and portal-health.
- Stopped tracking the `build/` directory.

## 0.2.0 (2026-11-04)

- `egisops services`: every folder's services report; services configured STARTED but
  not running (FAIL), stopped on purpose (info), saturated instance pools (WARN at all
  busy, info at 80%). `--folder` to narrow.
- `egisops logs`: SEVERE entries over a window, paged by `endTime` as documented, grouped
  by source and code with counts, latest message and machines. FAIL at 50 of one group.
- ADR 0004: where Esri's docs are ambiguous (report `parameters` format, log time units),
  use the documented default or accept both.

## 0.1.0 (2026-11-04)

- `egisops server-health`: health check, licensed, machine states, soonest license
  expiry, TLS certificate expiry and trust (from the handshake), version.
- Standard-library client: `generateToken` with `client=referer`, tokens in POST bodies,
  Esri error bodies raised, no password option, no way to turn off TLS verification.
- Tests on documented response shapes, a real local TLS server, and a portability test
  for the evaluators.

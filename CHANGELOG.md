# Changelog

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

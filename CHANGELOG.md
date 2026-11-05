# Changelog

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

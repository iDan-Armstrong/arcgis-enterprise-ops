# Changelog

## 0.1.0 (2026-11-04)

- `egisops server-health`: health check, licensed, machine states, soonest license
  expiry, TLS certificate expiry and trust (from the handshake), version.
- Standard-library client: `generateToken` with `client=referer`, tokens in POST bodies,
  Esri error bodies raised, no password option, no way to turn off TLS verification.
- Tests on documented response shapes, a real local TLS server, and a portability test
  for the evaluators.

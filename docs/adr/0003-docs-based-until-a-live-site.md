# 0003. Built from the documentation until a live site is available

Status: accepted (2026-11-04)

## Context

There is no ArcGIS Enterprise site available to develop against. ArcGIS Location
Platform does not include ArcGIS Enterprise; a development license would come from an
Esri program such as the ArcGIS Developer Bundle.

## Decision

Requests and response shapes follow Esri's published Administrator API documentation.
Tests answer with responses shaped from the documented examples, each fixture listing its
source page. The README says plainly that the tool has not been run against a live site.

## Consequences

- The tests prove the logic and the handling of documented shapes, not that every real
  site answers exactly as documented. Where Esri's documentation does not give a clear
  format (for example, SSL certificate validity on ArcGIS Server), the tool reads the
  value from a standard source instead (the TLS handshake).
- When a live site becomes available: run each command, capture real responses
  (scrubbed), add them as fixtures beside the documented ones, and record any
  differences here.

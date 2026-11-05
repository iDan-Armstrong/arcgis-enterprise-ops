# 0004. Where the documentation is ambiguous, use the documented default or accept both

Status: accepted (2026-11-04)

## Context

ADR 0003 commits this tool to Esri's published documentation. Two places in the pages
used by v0.2 are not precise enough to code against with confidence:

- The services report takes a `parameters` filter (`description | status | instances |
  iteminfo | properties`) but the documentation does not show how the list is formatted
  in a request.
- The log query says `startTime` and `endTime` are epoch milliseconds, while its sample
  request uses ten-digit values that are seconds.

## Decision

- Do not send what is not shown. The services report is requested without `parameters`,
  which the documentation says returns every property. The response is larger; the
  request is known to be valid.
- Accept both where both are plausible. Times read back from the log query are treated as
  seconds below 10^11 and milliseconds above. Requests send milliseconds, as documented.
  A test fixture deliberately uses seconds.

## Consequences

- No guessed request formats; a live site can only disagree with the documentation, not
  with an invention of ours.
- When a live site is available (ADR 0003), confirm both points and narrow the code.

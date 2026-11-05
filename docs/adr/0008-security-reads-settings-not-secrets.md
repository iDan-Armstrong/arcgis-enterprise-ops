# 0008. security reads settings, never secrets; incident playbooks print

Status: accepted (2026-11-05)

## Context

The settings Esri's serverScan and portalScan check live in Administrator API resources
that also hold secrets. `security/tokens` returns the token shared key. `security/config`
can return `portalSecretKey` and `webgisServerTrustKey`. Portal's `security/config` also
returns `webgisServerTrustKey`. A tool that keeps the whole response, or prints it with
`--json`, hands those to whoever reads its output.

For incidents, rds-geodatabase-ops already decided that playbooks print and never act
(its ADR 0008), for the same reasons: during an incident the order of changes decides
what can still be learned, and automation that changes a site at 3 a.m. can make things
worse.

## Decision

- The parsers read named fields only. A response is never stored whole, so a secret
  cannot reach the snapshot, the findings or `--json`. Tests check all three with marked
  placeholder secrets in the fixtures.
- Findings carry the scanner check ID in `evidence.esri`, so they can be compared with a
  scan report. Scanner checks with no documented setting to read are listed with
  `--verbose` as not checked (ESC099) instead of being reported as passing.
- `egisops incident` prints a playbook and runs nothing. Steps are REST operations or
  instructions. No step contains a token, password or key; where a new secret is needed
  the step says so and the person supplies it.
- Cutting access comes first for a compromised admin account (an administrator can clear
  the logs) and for an exposed service. Saving logs comes before anything that rotates,
  resets, rebuilds or restores. Tests enforce both.

## Consequences

- The tool cannot detect a weak shared key, because it never looks at it.
- The playbooks match rdsops in shape, phases and the federal notification step, so a
  site and its geodatabase can be handled with one process.

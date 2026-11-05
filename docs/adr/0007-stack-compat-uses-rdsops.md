# 0007. stack-compat uses rdsops for the database, and does not copy its matrix

Status: accepted (2026-11-04)

## Context

`stack-compat` answers whether a whole stack belongs together: Portal, the hosting server,
ArcGIS Data Store, the RDS for PostgreSQL geodatabase and ArcGIS Pro. The database part
(which RDS majors, certified minors and PostGIS versions each ArcGIS release supports)
already exists in rds-geodatabase-ops as `rdsops compat`, backed by a dated support matrix
with an Esri source URL on every entry.

ADR 0002 keeps egisops on the standard library. rdsops depends on boto3 and psycopg.

## Decision

- The database side calls `rdsops.compat.check` and reads ArcGIS Pro companion versions
  from rdsops's matrix. Its findings keep their CMP codes, so a CMP001 means the same
  thing from either tool.
- rdsops is an optional extra: `pip install 'egisops[stack]'`. egisops imports it only
  when `stack-compat` runs. Without it, the database side reports STK009 and the rest of
  the command still runs; every other command is unchanged.
- The Enterprise-side rules (one release across the base deployment, one Data Store release
  per server, Esri's direct-upgrade table and upgrade order, features retired at 12.0) are
  in egisops, with sources in docs/SCOPE.md.

## Consequences

- One support matrix to keep current, in one repository.
- The evaluator takes the rdsops check as an argument, so it stays pure and SIMServo runs
  both tools' code together in the browser.

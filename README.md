# arcgis-enterprise-ops

![CI](https://github.com/iDan-Armstrong/arcgis-enterprise-ops/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

Operations checks for ArcGIS Enterprise, written against the ArcGIS REST Administrator
API. Each check reads the site, scores what it found with stable finding codes, and says
what to do about it. Standard library only.

It is the ArcGIS Enterprise counterpart to
[rds-geodatabase-ops](https://github.com/iDan-Armstrong/rds-geodatabase-ops), which
covers the PostgreSQL database underneath, and it feeds the same
[SIMServo](https://idan-armstrong.github.io/simservo/) training game.

**Status:** v0.3: `egisops server-health`, `services`, `logs`, `portal-health` and `datastore`. [docs/SCOPE.md](docs/SCOPE.md) has the plan.

## How this was built, and what that means

There is no ArcGIS Enterprise site behind this repository. The requests, response shapes
and error handling follow Esri's published Administrator API documentation, and the
tests answer with responses shaped from the documented examples (sources in
[tests/fixtures/README.md](tests/fixtures/README.md)). The tool has not yet been run
against a live site. [ADR 0003](docs/adr/0003-docs-based-until-a-live-site.md) explains
the approach and what would change with one.

## server-health

```bash
pip install -e .
egisops server-health --url https://gis.example.com/arcgis --user siteadmin
```

```
server-health  https://gis.example.com/arcgis  ArcGIS Server 11.5.0

  [ok  ] SRV001  Health check: success
  [ok  ] SRV002  Server is licensed
  [ok  ] SRV003  Machine MACHINE.EXAMPLE.COM is running
  [FAIL] SRV003  Machine MACHINE2.EXAMPLE.COM should be running but is STOPPED
               Configured STARTED, real-time not. Services on this machine are not serving. Check the ArcGIS Server service on the host.
  [WARN] SRV004  License Data Interoperability expires in 19 days
               Request the renewal from My Esri now; an expired license stops services.
  [ok  ] SRV005  TLS certificate for gis.example.com expires in 300 days
  [WARN] SRV006  gis.example.com presents a self-signed certificate
               Browsers, ArcGIS Pro and federation need a certificate they trust. Replace it with a CA-signed one (the default self-signed certificate is for setup only), or install the private CA on every client.
  [ok  ] SRV007  ArcGIS Server 11.5.0
```

(Produced by the test site: documented example responses, one machine set to stopped,
one license set to expire in 19 days, and a self-signed certificate.)

| Code | Check | Source |
| --- | --- | --- |
| SRV001 | `/rest/info/healthcheck` returns HTTP 200 and `success: true` | the endpoint load balancers use |
| SRV002 | `isServerLicensed` on the admin root | `/admin` |
| SRV003 | Each machine's real-time state against its configured state | `/admin/machines`, `.../status` |
| SRV004 | The soonest expiring license item (epoch-millisecond `expiration`) | `/admin/system/licenses` |
| SRV005 | TLS certificate expiry, read from the handshake | the URL you gave |
| SRV006 | Whether that certificate is trusted by this machine | verified handshake |
| SRV007 | Version against the releases this tool targets (11.5, 12.0, 12.1) | `/admin` |
| SRV000 | A part of the check that could not run (for example, no token) | |

Exit code is 0 when clean, 1 on warnings, 2 on failures. `--json` gives the same
findings for other tools. `--no-login` runs only the public checks.

## services

Walks every folder's services report and compares each service's configured state with
its real-time state, and its busy instances with its maximum.

```
services  https://gis.example.com/arcgis  6 service(s)

  [info] SVC000  4 service(s) running in 4 folder(s)
  [WARN] SVC003  Maps/Stormwater.MapServer: all 4 instances busy
               New requests wait for an instance and can time out. Raise the maximum instances per machine if the machines have memory to spare, or move the service to a dedicated pool.
  [FAIL] SVC001  Maps/Sewer.FeatureServer should be running but is STOPPED
               Configured STARTED, real-time not: requests to it fail. Check the logs for the service, then POST services/Maps/Sewer.FeatureServer/start.
  [info] SVC003  Maps/Parcels.MapServer: 4 of 5 instances busy
               Close to the pool limit. Watch it at peak hours.
  [info] SVC002  1 service(s) stopped on purpose
               Maps/OldBasemap.MapServer
```

| Code | Meaning |
| --- | --- |
| SVC000 | How many services are running, in how many folders |
| SVC001 | Configured STARTED but not running: requests to it fail |
| SVC002 | Stopped on purpose (configured STOPPED) |
| SVC003 | All instances busy (WARN), or at 80% or more (info) |
| SVC009 | A folder's report could not be read; the rest still ran |

## logs

Queries SEVERE entries for a window (default 24 hours), follows the documented paging,
and groups them by source and code, so twenty identical errors read as one problem.

```
logs  https://gis.example.com/arcgis  SEVERE and worse, last 24 hours, 4 entries read

  [WARN] LOG001  4 SEVERE log entries in the last 24 hours
               Grouped by source and code below. Fix the largest group first.
  [WARN] LOG002  Maps/Sewer.FeatureServer: code 8252 x3
               Latest: Failed to create the service.
               Machines: MACHINE.EXAMPLE.COM (2), MACHINE2.EXAMPLE.COM (1)
  [WARN] LOG002  Maps/Parcels.MapServer: code 10837 x1
               Latest: Error performing query operation.
               Machines: MACHINE.EXAMPLE.COM (1)
```

| Code | Meaning |
| --- | --- |
| LOG001 | Total SEVERE entries in the window |
| LOG002 | One group: source, code, count, latest message, machines. FAIL at 50 or more |
| LOG003 | Stopped at the page limit; more entries exist |
| LOG009 | The query could not run |

(Both outputs come from the test site, built from Esri's documented response shapes with
made-up services and log messages.)

## portal-health

Points at the portal (`.../portal`, or the machine on port 7443). Signs in through
`sharing/rest/generateToken` and reads the Portal Administrator API.

```bash
egisops portal-health --url https://gis.example.com/portal --user portaladmin
```

```
portal-health  https://gis.example.com/portal  Portal for ArcGIS 11.5.0.0

  [ok  ] PTL001  Portal health check: success
  [ok  ] PTL002  Portal is licensed
  [WARN] PTL003  Portal machine machine1.example.com (standby) is not ready
               Machine is not available. The machine status call did not return success. The site is running on its other machine, without a standby.
  [ok  ] PTL003  Portal machine machine2.example.com (primary) is ready
  [WARN] PTL004  Portal license userType creatorUT expires in 19 days
               Get the renewed portal license from My Esri and import it before then; members with an expired user type lose access.
  [ok  ] PTL005  70 of 1400 member licenses in use
  [ok  ] PTL006  TLS certificate for gis.example.com expires in 210 days
  [ok  ] PTL008  3 federated server(s) validated, hosting server machine3.esri.com:6443
  [WARN] PTL009  Search index does not match the portal content
               search: 16451 stored, 16000 indexed. Members will not find some content. If indexing is not running, reindex from portaladmin/system/indexer/reindex.
  [ok  ] PTL010  Portal for ArcGIS 11.5.0.0
```

(From the test site: Esri's documented responses, with the standby machine's status set
to an error, one user type set to expire in 19 days, and the search index 451 items short.)

| Code | Check | Source |
| --- | --- | --- |
| PTL001 | HTTP 200 and `status: success` | `portaladmin/healthCheck` |
| PTL002 | Site initialized and licensed | `portaladmin` root |
| PTL003 | Each machine ready; one down of two is WARN, all down FAIL; a single machine is noted | `machines`, `machines/status/<machine>` |
| PTL004 | Soonest expiring user type, app bundle, app, extension or capability | `license` |
| PTL005 | Member licenses in use, and user types with every license assigned | `license` |
| PTL006, PTL007 | TLS certificate expiry and trust, read from the handshake | the URL you gave |
| PTL008 | Federated servers: a hosting server exists, and each validates | `federation/servers`, `.../validate` |
| PTL009 | Search index counts match the stored counts | `system/indexer/status` |
| PTL010 | Version against the releases this tool targets | `portaladmin` root |
| PTL000 | A part of the check that could not run | |

## datastore

Points at the hosting ArcGIS Server. Finds the data stores ArcGIS Data Store manages for
it and runs Esri's `validate` health check on each, then reads the result more strictly
than its summary line: Esri's own example reports `Healthy` while listing a machine as
unavailable.

```bash
egisops datastore --url https://gis.example.com/server --user siteadmin
```

```
datastore  https://gis.example.com/arcgis  2 data store(s)

  [ok  ] DST000  2 data store(s) validated (relational, tile cache)
  [info] DST003  Relational data store ds_d0hv9sqh has no standby machine
               If its machine fails, hosted feature layers are down until it is restored from backup. A standby machine takes over on its own.
  [WARN] DST005  Relational data store ds_d0hv9sqh: newest backup 9.0 days old
               Older than the 7-day target. Check that scheduled backups are on and the backup location has space.
  [WARN] DST002  Tile cache data store tcs_abcdef8x: 1 of 3 machine(s) unavailable
               MACHINE3.EXAMPLE.COM. The data store answered without them. Check the machines and the ArcGIS Data Store service on each.
```

(From the test site: Esri's documented relational and tile cache `validate` examples,
evaluated nine days after the example's last backup.)

| Code | Meaning |
| --- | --- |
| DST000 | How many data stores were validated, or none registered (WARN) |
| DST001 | The data store's own overall health is not `Healthy` |
| DST002 | A machine is unreachable, stopped, unhealthy or not accepting connections (FAIL for the primary), or listed as unavailable |
| DST003 | Relational data store with no standby machine |
| DST004 | Not registered with the server, or no valid connection to it |
| DST005 | Age of the newest backup against `--backup-days` (default 7), or no backup recorded |
| DST006 | Spatiotemporal cluster status (YELLOW warns, RED fails) and unassigned shards |
| DST009 | A data store could not be found or validated; the rest still ran |

The validate call needs one data store machine name per store. It comes from `--machine`
or from the data item; [ADR 0005](docs/adr/0005-portal-tokens-and-data-store-machines.md)
explains why both.

## Credentials and TLS

- A token from `EGISOPS_TOKEN`, or a user (`--user` or `EGISOPS_USER`) with
  `EGISOPS_PASSWORD` or an interactive prompt. There is no password option.
- Tokens are requested with `client=referer` and never go in URLs: in POST bodies for
  ArcGIS Server, and in the `X-Esri-Authorization` header for Portal's GET resources
  ([ADR 0005](docs/adr/0005-portal-tokens-and-data-store-machines.md)).
- TLS verification cannot be turned off. A site on a private CA takes `--ca-file`.
- Esri returns many errors as HTTP 200 with an error body; those are raised, not parsed
  as data.

## Design

- **Gather and evaluate are separate.** `gather` talks to the site; `evaluate` is a pure
  function over a snapshot. A test imports the evaluators with the network stack blocked,
  which is what lets SIMServo run them in a browser.
- **Direct REST, standard library.** No ArcGIS API for Python
  ([ADR 0002](docs/adr/0002-direct-rest-standard-library.md)).
- **Where the docs are ambiguous, take the documented default or accept both.**
  ([ADR 0004](docs/adr/0004-ambiguous-docs.md))
- **Partial failure is a finding.** A call that fails (missing token, one machine
  unreachable) becomes SRV000 and the rest of the check still runs.

## How it is tested

| Test | What it proves |
| --- | --- |
| `tests/test_client.py` | Token request shape; token in the body not the URL; Esri error bodies with HTTP 200; non-JSON responses |
| `tests/test_server.py` | Every finding and band against the documented response shapes; partial failure |
| `tests/test_services.py` | Folder walk, stopped and saturated services, one failing folder not stopping the rest |
| `tests/test_logs.py` | Paging by `endTime`, the documented filter, grouping, milliseconds and seconds both accepted |
| `tests/test_certificate.py` | Reading a real self-signed certificate from a local TLS server |
| `tests/test_portal.py` | Every PTL finding and band; token in the header, never the URL; HTML health check; uninitialized site; federation failures named by server and role; public-only run without a token |
| `tests/test_datastore.py` | Esri's validate examples, including "Healthy" with an unavailable machine; primary vs standby; backup age in ms or s; missing machine names ask for `--machine` |
| `tests/test_cli.py` | JSON output, token from the environment, and no password or no-verify options |
| `tests/test_portable.py` | Evaluators import with `socket`, `ssl` and `urllib` blocked |

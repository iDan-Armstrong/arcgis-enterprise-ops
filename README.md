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

**Status:** v0.6: `egisops server-health`, `services`, `logs`, `portal-health`, `datastore`, `backup-check`, `stack-compat`, `security` and `incident`. [docs/SCOPE.md](docs/SCOPE.md) has the plan.

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

## stack-compat

Do the pieces belong together? Portal, the hosting server and every ArcGIS Data Store must
be on one release; the RDS for PostgreSQL geodatabase must be supported by that release;
ArcGIS Pro should be the companion version. With `--target`, it lays out the upgrade.

The database part is [rdsops](https://github.com/iDan-Armstrong/rds-geodatabase-ops)
`compat` and its dated Esri support matrix, so its findings keep their CMP codes
([ADR 0007](docs/adr/0007-stack-compat-uses-rdsops.md)). Install it with
`pip install -e '.[stack]'`.

```bash
egisops stack-compat --url https://gis.example.com/server --user siteadmin \
    --portal-version 11.5 --engine-version 16.8 --postgis 3.5.2 --pro-version 3.5 --target 12.1
```

```
stack-compat  Portal for ArcGIS 11.5.0, ArcGIS Server (hosting) 11.5.0  RDS for PostgreSQL 16.8

  [ok  ] STK001  2 component(s) on ArcGIS Enterprise 11.5
  [ok  ] CMP001  PostgreSQL 16 is supported by ArcGIS Enterprise 11.5 / Pro 3.5
  [ok  ] CMP002  RDS 16.8 is the certified minor
  [ok  ] CMP003  PostGIS 3.5.2 is not on the blocked list
  [ok  ] CMP004  Support data for 11.5 checked 2026-11-04 (0 days ago)
  [ok  ] STK004  ArcGIS Pro 3.5 is the companion
  [WARN] STK005  Upgrade plan: 11.5 to 12.1
               11.5 upgrades directly to 12.1. Take a WebGISDR backup before upgrading any component. Order: Portal for ArcGIS, Web Adaptor for Portal, the hosting server, Web Adaptor for ArcGIS Server, ArcGIS Data Store, other federated servers. ArcGIS Web AppBuilder, ArcGIS Configurable Apps, Map Viewer Classic, the tile cache data store, ArcGIS Insights and other features were retired at 12.0: migrate away on 11.5 first. At 12.1 the geodatabase needs attention: CMP002 RDS 16.8 is below the certified minimum 16.11. Companion ArcGIS Pro for 12.1: 3.7.
```

(Run offline with `--server-version 11.5.0` on 2026-11-04.)

| Code | Meaning |
| --- | --- |
| STK001 | Base deployment components on one release (FAIL when mixed, with the upgrade order) |
| STK002 | Every data store on the server at the same Data Store release |
| CMP001-CMP004 | The geodatabase against the Esri matrix, from rdsops `compat` |
| STK003 | No database versions given (info) |
| STK004 | ArcGIS Pro against the companion version for the release |
| STK005 | Upgrade plan to `--target`: direct or interim, backup, order, retired features, the geodatabase at the target |
| STK009 | rdsops not installed, or a part of the check that could not run |

## backup-check

Checks an ArcGIS Enterprise backup setup from its files, with no network calls: the
`webgisdr.properties` file, the folder the `.webgissite` backups land in, and the JSON
that `webgisdr --export --output <file>` writes. Run it after the scheduled backup and
the exit code says whether last night's backup is good.

```bash
egisops backup-check --properties webgisdr.properties --backups \\fileserver\wgbackups \
    --output-file last-run.json --rpo-hours 24
```

```
backup-check  webgisdr.properties  backups in /backups  RPO 24h

  [ok  ] BAK001  Properties complete for FileSystem
  [WARN] BAK004  Stored in plain text: PORTAL_ADMIN_PASSWORD
               WebGISDR encrypts these the first time it runs with the file. Run it once (or check that it has run), and keep the file readable only by the account that runs backups.
  [info] BAK007  Not in a WebGISDR backup: map and tile caches, referenced data, spatiotemporal store
               Back up arcgiscache directories, file and database data sources behind services, and the spatiotemporal big data store (backupdatastore) separately.
  [WARN] BAK010  Newest backup 34.0 hours old (20261103-020000-EST-BACKUP.webgissite, 5.8 GB)
               Older than the 24-hour recovery point objective: a restore today loses everything since 2026-11-03 02:00 UTC. Check the scheduled task that runs webgisdr --export.
  [FAIL] BAK011  Last WebGISDR run failed at 2026-11-04 07:00 UTC: ArcGIS Data Store (relational)
               Failed to back up one or more components. Unable to connect to the ArcGIS Data Store machine. Fix the component and run the export again; the newest backup file may not be complete.
```

(Esri's FileSystem example properties file, two made-up backup files 34 and 58 hours old,
and Esri's sample output with the relational Data Store component set to failed, written
five hours earlier; clock fixed at 2026-11-04 12:00 UTC.)

| Code | Meaning |
| --- | --- |
| BAK001 | Required properties for the store provider are set |
| BAK002 | `PORTAL_ADMIN_URL` is HTTPS and points at a portal machine on 7443 |
| BAK003 | A path with single backslashes, which the properties format drops |
| BAK004 | Passwords or keys still in plain text; S3 access keys (info); Azure SAS tokens (WARN) |
| BAK005 | Unknown mode (FAIL); incremental mode and what it depends on (info) |
| BAK006 | `SHARED_LOCATION` blank: required with federated servers at 12.0 or earlier |
| BAK007 | What a WebGISDR backup does not contain |
| BAK010 | Newest backup by modified time (the one a folder restore picks) against the RPO; none, or empty files |
| BAK011 | The last run's status and failed components; its backup missing from the folder |
| BAK009 | A file could not be read |

Secrets in the properties file are read only to see whether they are set and encrypted.
They never appear in output ([ADR 0006](docs/adr/0006-backup-check-works-on-files.md)).

## security

Reads the settings Esri's own scanners (serverScan.py and portalScan.py) look at, through
the Administrator API, and puts the scanner's check ID on each finding.

```bash
egisops security --url https://gis.example.com/server --user siteadmin
egisops security --url https://gis.example.com/portal --portal --user portaladmin
```

```
security  https://gis.lakeshore.example/server  (server, against Esri's serverScan checks)

  [FAIL] ESC001  Protocol is HTTP_AND_HTTPS
               Tokens and credentials can cross the network in clear text. Set the protocol to HTTPS in security/config/update; HTTP calls are then redirected.
  [WARN] ESC001  Old TLS versions enabled: TLSv1.1
               TLS 1.2 and 1.3 are the defaults. Remove the old versions from httpsProtocols unless a named client still needs them.
  [ok  ] ESC002  Standardized queries enforced
  [FAIL] ESC003  Tokens can be requested with GET
               Usernames and passwords then appear in URLs, proxy logs and browser history. Set allowHttpGet to false in security/tokens.
  [WARN] ESC004  The REST services directory is browsable
               It lists every service to anyone who can reach the site. Turn it off in production (system/handlers/rest/servicesdirectory/edit, enabled=false).
  [WARN] ESC004  Cross-domain requests are allowed from any site
               Set allowedOrigins to the web apps that need this server.
  [ok  ] ESC005  Web Adaptors registered over HTTPS
  [info] ESC005  Administrators can still reach the server directly
               allowDirectAccess is true, so the admin API answers on the server port as well as through the Web Adaptor. Set it to false, or limit allowedAdminAccessIPs, if every administrator can go through the Web Adaptor.
  [info] ESC005  Output, job and input directories do not require sign-in
               With virtualDirsSecurityEnabled false, files written to arcgisoutput, arcgisjobs and arcgisinput can be fetched by URL. Turn it on if secured services write there.
  [WARN] ESC006  The primary site administrator account is enabled
               It cannot be locked out and is not in the identity store. Disable it once another administrator works (security/psa/disable); it can be re-enabled from the machine if needed.
  [ok  ] ESC007  TLS certificate for gisserver.lakeshore.example expires in 200 days
  [WARN] ESC007  gisserver.lakeshore.example presents a self-signed certificate
               Browsers, ArcGIS Pro and federation need a certificate they trust. Replace it with a CA-signed one (the default self-signed certificate is for setup only), or install the private CA on every client.
```

(Evaluated on settings for a deliberately misconfigured lab server, clock fixed at
2026-11-05 12:00 UTC; with `--url` they come from the site.)

| Code | Meaning | Esri check |
| --- | --- | --- |
| ESC001 | HTTPS only; old TLS versions; HSTS | SS01 |
| ESC002 | Standardized queries; the legacy URL parser | SS02 |
| ESC003 | Token requests with GET or with credentials in the query string | SS03, SS04 |
| ESC004 | Services directory browsable; cross-domain from any origin | SS07, SS08 |
| ESC005 | Web Adaptors over HTTPS; direct admin access; unsecured output directories | SS10 |
| ESC006 | Primary site administrator enabled | SS11 |
| ESC007 | Server certificate expiry and trust | SS14 |
| ESC011 to ESC016 | Portal: HTTPS only, services directory, anonymous access, cross-domain, automatic accounts, certificate | PS04, PS03, PS06, PS09, PS08 |
| ESC099 | With `--verbose`: scanner checks this tool does not read | |

`security/tokens` holds the token shared key, and `security/config` can hold the portal
secret and trust keys. Only named fields are read, so they never reach the output or
`--json` ([ADR 0008](docs/adr/0008-security-reads-settings-not-secrets.md)).

## incident

Contingency playbooks for a security incident on the site: `admin-account`, `token`,
`exposed-service`, `content` and `host`. Same phases as `rdsops incident` (NIST SP 800-61
Rev. 3), the CISA one-hour notification right after triage with `--federal`, and logs
saved before anything rotates, resets, rebuilds or restores. It prints and runs nothing.

```bash
egisops incident --kind admin-account --server https://gis.nwsa.example/server \
    --portal-url https://gis.nwsa.example/portal --account gisadmin2 --psa-enabled \
    --federal --backup-age-hours 18
```

```
incident  admin-account: An administrator account on the server or portal is in the wrong hands
  server https://gis.nwsa.example/server  portal https://gis.nwsa.example/portal  federal

  [ok  ] INC101  Newest webgisdr backup is 18 hours old
  [WARN] INC102  The primary site administrator is enabled
               If its password is known to the attacker, they keep admin access through any identity store change. It is disabled in the playbook.
  [WARN] INC105  Federal system: CISA notification due within one hour of identification
               The clock starts when the agency's CSIRT, SOC or IT department identifies the incident, not when the investigation ends.

  Playbook (nothing here has been run)

  Triage
   1. Open an incident record and name one incident lead
      Start a timeline now (UTC). Every action from here on goes in it with who and when.
   2. Scope: which site, which machines, which data
      > Site https://gis.nwsa.example/portal. List the federated servers, the registered data stores and the enterprise geodatabases behind them.
      A compromise of the site reaches every database registered with it.

  Notify
   3. Report to CISA within one hour of identification
      > https://www.cisa.gov/report
      CISA's Federal Incident Notification Guidelines: federal Executive Branch civilian agencies notify CISA within one hour of the incident being identified by the agency's top-level CSIRT, SOC or IT department. Report what is known; update later. Contractors report through the agency and their contract terms.
   4. Tell the agency SOC and the system owner
      Follow the agency incident response plan, including privacy officials if personal data may be involved.

  Contain
   5. Disable the portal account gisadmin2
      $ POST https://gis.nwsa.example/portal/sharing/rest/community/users/gisadmin2/disable f=json
      Disabling blocks new sign-ins and keeps the account and its content for the investigation. Do not delete it. Access is cut before the logs are saved because an administrator can clear them.
   6. Invalidate tokens already issued
      > Update the token shared key (server: security/tokens/update; portal: its token settings). You enter a new random key; it is never written here.
      A disabled account's tokens stay valid until they expire. Changing the key ends them all, so every user signs in again.
   7. Limit admin access while you work
      $ POST https://gis.nwsa.example/server/admin/security/config/update allowedAdminAccessIPs=<incident team addresses> f=json
      Keeps the admin API to the people responding. Undo at the end.

  Preserve
   8. Save the server logs before anything changes
      $ POST https://gis.nwsa.example/server/admin/logs/query level=FINE startTime=<now ms> endTime=<epoch ms of the last known good time> pageSize=10000 f=json
      Server logs roll over and the log level may be low; save them now, page by page, into the incident record. Raise the level to FINE for the duration.
   9. Save the portal logs
      $ POST https://gis.nwsa.example/portal/portaladmin/logs/query level=FINE startTime=<now ms> endTime=<epoch ms of the last known good time> f=json
      Portal logs show sign-ins, sharing changes and administrative actions.
  10. Save the web server and load balancer access logs
      They hold source addresses that ArcGIS logs do not. Copy them off the machines.
  ...
```

(The first part of a real run; the rest lists what the account did, removes what was
added, resets the credentials it could read, disables the primary site administrator,
recovers the account with MFA, and ends with `egisops security` and a review.)

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
| `tests/test_backup.py` | Esri's three example properties files; escaping; secrets absent from all output; RPO bands; newest by modified time, not name; incremental and full; Esri's output file, success and failure |
| `tests/test_stack.py` | One release across components; mixed Data Stores; the geodatabase through the real rdsops; direct and interim upgrade paths; a database minor that is too old for the target; the tile cache store at 12.0; running without rdsops |
| `tests/test_security.py` | Documented example responses; every scanner mapping; marked placeholder secrets absent from the snapshot and from `--json`; unreadable parts reported, not assumed |
| `tests/test_incident.py` | Every playbook's shape; federal notification right after triage; logs saved before anything destroys evidence; export before import; disk capture before a machine leaves the site; no secrets in any step |
| `tests/test_cli.py` | JSON output, token from the environment, and no password or no-verify options |
| `tests/test_portable.py` | Evaluators import with `socket`, `ssl` and `urllib` blocked |

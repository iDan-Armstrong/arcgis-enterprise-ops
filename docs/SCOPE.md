# Scope

Agreed 2026-11-04. Targets ArcGIS Enterprise 11.5 and 12.x.

## Releases

| Release | Command | What it checks |
| --- | --- | --- |
| v0.1 (released) | `server-health` | Health check, licensed, machine states, license expiry, TLS certificate expiry and trust, version |
| v0.2 (released) | `services`, `logs` | Stopped services, service pools at max instances, SEVERE log entries grouped by service |
| v0.3 (released) | `portal-health`, `datastore` | Portal health, machines, license and member capacity, TLS certificate, federated server validation, search index; Data Store validation, machines, standby, server connection, backup age |
| v0.4 (released) | `backup-check` | `webgisdr` properties lint (provider keys, escaping, plain-text secrets, mode, portal URL), newest `.webgissite` against an RPO target, last run's output file |
| v0.5 (released) | `stack-compat` | Portal, hosting server and Data Store on one release; the RDS geodatabase through rdsops `compat`; ArcGIS Pro companion; upgrade plan to `--target` |

## Facts the design rests on (checked 2026-11-04)

| Fact | Source |
| --- | --- |
| `/rest/info/healthcheck` returns HTTP 200 and `{"success": true}` when the machine can take requests; meant for load balancers | [Health Check](https://developers.arcgis.com/rest/services-reference/enterprise/health-check/) |
| Admin root `/admin` returns `isServerLicensed`, `currentVersion`, `fullVersion` | [Server Administrator Root](https://developers.arcgis.com/rest/enterprise-administration/server/site/) |
| `/admin/machines` lists `machineName` and `adminURL`; `.../status` returns `configuredState` and `realTimeState`, and the real-time state is the one to use | [Machines](https://developers.arcgis.com/rest/enterprise-administration/server/machines/), [Status](https://developers.arcgis.com/rest/enterprise-administration/server/status/) |
| `/admin/system/licenses` items carry `canExpire` and `expiration` in epoch milliseconds | [Licenses](https://developers.arcgis.com/rest/enterprise-administration/server/licenses/) |
| `generateToken` is a POST with `username`, `password`, `client` (`referer`, `ip`, `requestip`) | [Generate Token](https://developers.arcgis.com/rest/enterprise-administration/server/generatetoken/) |
| `/admin/services` lists `folders`; each folder's `report` returns `reports` with `status` (`configuredState`, `realTimeState`) and `instances` (`max`, `busy`, `free`, ...) | [Services/Root Folder](https://developers.arcgis.com/rest/enterprise-administration/server/services/), [Report](https://developers.arcgis.com/rest/enterprise-administration/server/servicesreport/) |
| `/admin/logs/query`: `startTime` is the newest time and `endTime` the oldest; when `hasMore`, the response `endTime` is the next `startTime`; `filterType=json` and `filter` are required; default level WARNING | [Query - Logs](https://developers.arcgis.com/rest/enterprise-administration/server/logsquery/) |
| Portal `healthCheck` returns HTTP 200 and `{"status": "success"}`; an unavailable machine returns something other than 200, possibly HTML even with `f=json` | [Health Check (Portal)](https://developers.arcgis.com/rest/enterprise-administration/portal/health-check-portal/) |
| Portal root returns `isPortalLicensed`, `version`, `currentbuild`; at 12.1 an uninitialized site returns an error body with code 209000 | [Portal Administrator Root](https://developers.arcgis.com/rest/enterprise-administration/portal/portal-administration-root/) |
| Portal `license` lists user types, app bundles, apps, extensions and capabilities with `expiration` in epoch ms, plus current and maximum registered members | [License](https://developers.arcgis.com/rest/enterprise-administration/portal/license/) |
| `federation/servers/validate` returns `status` and `serversStatus` (`success`, `success with warnings`, `failure`, `undetermined`) with messages; the hosting server's messages cover its managed data store | [Validate - Servers](https://developers.arcgis.com/rest/enterprise-administration/portal/validate-servers/) |
| `system/indexer/status` gives database and index counts for users, groups and search; a mismatch after indexing finishes means reindex | [Status - Indexer](https://developers.arcgis.com/rest/enterprise-administration/portal/indexer-status/) |
| Data Store `validate` returns `datastore.overallhealth`, per-machine reachability, status, role and `db.isAccepting`, `unavailableMachines`, registration, server connection and `datastore.lastbackup` (epoch ms); Esri's own example reports `Healthy` with a machine unavailable | [Validate (Data Store)](https://developers.arcgis.com/rest/enterprise-administration/server/validatedatastore/) |
| `data/findItems` with `parentPath=/enterpriseDatabases&types=egdb`; items carry `info.isManaged` | [Find Data Items](https://developers.arcgis.com/rest/enterprise-administration/server/finddataitems/), [Data Item](https://developers.arcgis.com/rest/enterprise-administration/server/dataitem/) |
| `webgisdr.properties` keys per store provider (FileSystem, AmazonS3, AzureBlob); backslashes in paths must be doubled; passwords and keys are encrypted the first time the tool runs | [WebGISDR tool properties file](https://doc.esri.com/en/arcgis-enterprise/latest/administer/populate-webgisdr-tool-properties-file.html) |
| `webgisdr --output` writes JSON with `status`, `backupLocation`, `elapsedTime` and per-component `results` | [WebGISDR tool output file](https://doc.esri.com/en/arcgis-enterprise/latest/administer/webgisdr-tool-output-file.html) |
| A folder restore takes the newest `.webgissite` by last-modified time; backup files are named `<timestamp>.webgissite` | [WebGISDR tool properties file](https://doc.esri.com/en/arcgis-enterprise/latest/administer/populate-webgisdr-tool-properties-file.html), [Create an ArcGIS Enterprise backup](https://doc.esri.com/en/arcgis-enterprise/latest/administer/create-web-gis-backup.html) |
| Not in a WebGISDR backup: map and tile caches, referenced data, the spatiotemporal big data store; incremental mode needs Data Store scheduled backups with point-in-time recovery | [ArcGIS Enterprise backups](https://doc.esri.com/en/arcgis-enterprise/latest/administer/overview-backup-restore-web-gis.html) |
| All base ArcGIS Enterprise components must use the same software version; all data stores registered to one ArcGIS Server site must run the same ArcGIS Data Store release | [Upgrade ArcGIS Data Store](https://doc.esri.com/en/arcgis-enterprise/latest/deploy/upgrade-data-store.html) |
| Direct upgrades: 11.0 to 12.0 go to 12.1; 10.8 to 10.9.1 to 11.5; 10.7 to 10.7.1 to 11.3; 10.5 to 10.6.1 to 10.9.1. Order: Portal, its Web Adaptor, hosting server, its Web Adaptor, Data Store, other federated servers. Back up first. Web AppBuilder, Configurable Apps, Map Viewer Classic, the tile cache data store and others retired at 12.0 | [Upgrade ArcGIS Enterprise](https://doc.esri.com/en/arcgis-enterprise/latest/deploy/upgrade-arcgis-enterprise.html) |
| `webgisdr` backs up Portal items, hosted layers, federated server settings and Data Store data, not map or tile caches | [Create an ArcGIS Enterprise backup](https://doc.esri.com/en/arcgis-enterprise/latest/administer/create-web-gis-backup.html) |

## Out of scope

Changing anything on the site. Every command reads; the fix is printed for a person to run.

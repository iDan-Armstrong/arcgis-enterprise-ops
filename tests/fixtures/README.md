# Test fixtures

These JSON files are shaped from the example responses in Esri's ArcGIS REST API
documentation, not captured from a live site (see ADR 0003). Version numbers are set to
11.5. The license `expiration` value is the placeholder from Esri's example; tests replace
it with dates relative to the test clock.

| File | Source |
| --- | --- |
| `admin_root.json` | [Server Administrator Root](https://developers.arcgis.com/rest/enterprise-administration/server/site/) |
| `machines.json` | [Machines](https://developers.arcgis.com/rest/enterprise-administration/server/machines/) |
| `machine_status_*.json` | [Status - Machine](https://developers.arcgis.com/rest/enterprise-administration/server/status/) |
| `licenses.json` | [Licenses](https://developers.arcgis.com/rest/enterprise-administration/server/licenses/) |
| `generate_token.json` | [Generate Token](https://developers.arcgis.com/rest/enterprise-administration/server/generatetoken/) |
| `healthcheck_ok.json` | [Health Check](https://developers.arcgis.com/rest/services-reference/enterprise/health-check/) |
| `services_root.json` | [Services/Root Folder](https://developers.arcgis.com/rest/enterprise-administration/server/services/) (a `Maps` folder added) |
| `report_*.json` | [Services Report](https://developers.arcgis.com/rest/enterprise-administration/server/servicesreport/). Esri's example is not valid JSON as printed (missing quotes and commas); these use its keys in valid JSON. Service names and counts are made up. |
| `logs_page*.json` | [Query - Logs](https://developers.arcgis.com/rest/enterprise-administration/server/logsquery/). Page 2 uses seconds instead of milliseconds on purpose, because Esri's own sample does; the parser must accept both. Messages and codes are illustrative. |
| `error_token_required.json` | The `{"status": "error", "messages": [...]}` error form the Administrator API uses. The message text is illustrative. |

## Portal for ArcGIS (v0.3)

| File | Source |
| --- | --- |
| `portal_health_ok.json` | [Health Check (Portal)](https://developers.arcgis.com/rest/enterprise-administration/portal/health-check-portal/). The unhealthy case has no JSON example; Esri says an unavailable machine returns a non-200 and may return HTML. |
| `portal_root.json`, `portal_root_not_initialized.json` | [Portal Administrator Root](https://developers.arcgis.com/rest/enterprise-administration/portal/portal-administration-root/), success and the 12.1 "not initialized" error. Version set to 11.5 in the success case. |
| `portal_machines.json`, `portal_machine_status.json` | [Machines](https://developers.arcgis.com/rest/enterprise-administration/portal/machines/), [Status - Machine](https://developers.arcgis.com/rest/enterprise-administration/portal/status/) |
| `portal_license.json` | [License](https://developers.arcgis.com/rest/enterprise-administration/portal/license/). Tests replace the `expiration` values with dates relative to the test clock. |
| `portal_federation_servers.json` | [Servers](https://developers.arcgis.com/rest/enterprise-administration/portal/servers/), three of the five example servers. Esri's example has a stray `/` and a triple slash in one entry; fixed here. |
| `portal_federation_validate.json` | [Validate - Servers](https://developers.arcgis.com/rest/enterprise-administration/portal/validate-servers/), the same three servers. Message text is Esri's, including its spelling. |
| `portal_indexer_status.json` | [Status - Indexer](https://developers.arcgis.com/rest/enterprise-administration/portal/indexer-status/) |
| `portal_generate_token.json` | [Generate Token (sharing)](https://developers.arcgis.com/rest/users-groups-and-items/generate-token/) |

## ArcGIS Data Store (v0.3)

| File | Source |
| --- | --- |
| `validate_relational.json` | [Validate (Data Store)](https://developers.arcgis.com/rest/enterprise-administration/server/validatedatastore/), example one, verbatim. |
| `validate_tilecache_unavailable.json` | Same page, example three: overall health "Healthy" while one machine is listed in `unavailableMachines`. Esri's example is missing commas; fixed here. |
| `validate_bigdata.json` | Same page, example four, commas fixed. |
| `find_items_egdb.json` | [Find Data Items](https://developers.arcgis.com/rest/enterprise-administration/server/finddataitems/). The first item follows Esri's example. The second, a managed `AGSDataStore_ds_` item with `isManaged: true` and an `info.machines` list, is constructed: Esri's example shows only unmanaged items, and the `machines` list is not documented (ADR 0005). |
| `find_items_nosql.json` | Constructed the same way, for a tile cache data store. |

## WebGISDR backups (v0.4)

| File | Source |
| --- | --- |
| `webgisdr_filesystem.properties`, `webgisdr_s3.properties`, `webgisdr_azure.properties` | The three examples on [WebGISDR tool properties file](https://doc.esri.com/en/arcgis-enterprise/latest/administer/populate-webgisdr-tool-properties-file.html), verbatim, including their example passwords. Esri's Azure example sets no credential type. |
| `webgisdr_output_success.json` | [WebGISDR tool output file](https://doc.esri.com/en/arcgis-enterprise/latest/administer/webgisdr-tool-output-file.html), verbatim. It describes a backup but says `"operation": "restore"`; the check does not rely on that field. |
| `webgisdr_output_failure.json` | The same sample with the relational Data Store component failed. The failure messages are illustrative. |

## Security (v0.6)

| File | Source |
| --- | --- |
| `security_config.json` | [Security Configuration](https://developers.arcgis.com/rest/enterprise-administration/server/securityconfig/), its documented keys. Secret values replaced with marked placeholders (`...-DO-NOT-PRINT`) that tests look for in output. |
| `security_tokens.json` | [Tokens](https://developers.arcgis.com/rest/enterprise-administration/server/tokens/), Esri's example including its sample `sharedKey` (quoted here; Esri's example is not valid JSON). |
| `security_psa.json` | The `disabled` flag of the primary site administrator resource. |
| `system_properties.json` | Empty properties: the documented defaults apply (standardized queries on). |
| `servicesdirectory.json`, `webadaptors.json` | The `enabled` and `allowedOrigins` keys of the services directory handler, and `webAdaptors` with `webAdaptorURL`. Values are illustrative. |
| `portal_security_config.json`, `portal_self.json` | Portal `security/config` and `portals/self` keys used by the check. Values are illustrative; the trust key is a marked placeholder. |


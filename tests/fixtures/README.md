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
| `error_token_required.json` | The `{"status": "error", "messages": [...]}` error form the Administrator API uses. The message text is illustrative. |

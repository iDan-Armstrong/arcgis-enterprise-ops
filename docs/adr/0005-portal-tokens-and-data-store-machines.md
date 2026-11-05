# 0005. Portal tokens travel in a header; data store machine names come from the item or a flag

Status: accepted (2026-11-04)

## Context

v0.3 adds `portal-health` (Portal Administrator API) and `datastore` (the hosting
server's data items). Two things in the documentation do not fit the rules the tool
already follows.

1. **Tokens.** ADR 0002 keeps tokens out of URLs. The Server Administrator API takes
   POSTs, so the token goes in the form body. The Portal Administrator resources used
   here (`healthCheck`, the root, `machines`, `machines/status/<machine>`, `license`,
   `federation/servers`, `federation/servers/validate`, `system/indexer/status`) are
   documented as GET. Esri's
   [HTTP authorization headers](https://developers.arcgis.com/documentation/security-and-authentication/reference/http-authorization-headers/)
   page documents `Authorization: Bearer` and the Esri-defined `X-Esri-Authorization:
   Bearer`, the second for deployments that also use web-tier authentication.
2. **Data store machine names.** The documented health check for ArcGIS Data Store is
   `data/items/<item>/machines/<machine>/validate`. One call returns every machine in
   that data store, so one name is enough. But no documented response lists the
   machine names: Esri's `findItems` example shows only unmanaged databases, and the
   data item page lists `info` fields without machines.

## Decision

1. Portal GET requests carry the token in `X-Esri-Authorization: Bearer <token>`. It
   works with and without web-tier authentication, and nothing goes in the query string.
   Portal tokens come from `sharing/rest/generateToken` (POST, `client=referer`), as
   documented.
2. The machine name comes from `--machine` when given. Otherwise from the first
   `info.machines[].name` on the data item, when the item has one. This field is not in
   the documentation. If neither is available, the store is not validated; a DST009
   finding names the item and asks for `--machine`. No name is guessed.
3. `findItems` and `validate` are sent as POSTs with the token in the body, like every
   other Server admin call in this tool. `findItems` is documented as GET; the Server
   Administrator API documents that POST requests carry the token in the body.

## Consequences

- Nothing in this release puts a token in a URL.
- On a site whose data items do not list machines, `datastore` needs `--machine`. That
  is visible in the output, not a silent skip.
- To confirm on a live site (ADR 0003): Portal's handling of `X-Esri-Authorization` on
  `portaladmin`, whether managed data items list their machines, and `findItems` over
  POST.

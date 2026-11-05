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

**Status:** v0.1, `egisops server-health`. [docs/SCOPE.md](docs/SCOPE.md) has the plan.

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

## Credentials and TLS

- A token from `EGISOPS_TOKEN`, or a user (`--user` or `EGISOPS_USER`) with
  `EGISOPS_PASSWORD` or an interactive prompt. There is no password option.
- Tokens are requested with `client=referer` and travel in POST bodies, never in URLs.
- TLS verification cannot be turned off. A site on a private CA takes `--ca-file`.
- Esri returns many errors as HTTP 200 with an error body; those are raised, not parsed
  as data.

## Design

- **Gather and evaluate are separate.** `gather` talks to the site; `evaluate` is a pure
  function over a snapshot. A test imports the evaluators with the network stack blocked,
  which is what lets SIMServo run them in a browser.
- **Direct REST, standard library.** No ArcGIS API for Python
  ([ADR 0002](docs/adr/0002-direct-rest-standard-library.md)).
- **Partial failure is a finding.** A call that fails (missing token, one machine
  unreachable) becomes SRV000 and the rest of the check still runs.

## How it is tested

| Test | What it proves |
| --- | --- |
| `tests/test_client.py` | Token request shape; token in the body not the URL; Esri error bodies with HTTP 200; non-JSON responses |
| `tests/test_server.py` | Every finding and band against the documented response shapes; partial failure |
| `tests/test_certificate.py` | Reading a real self-signed certificate from a local TLS server |
| `tests/test_cli.py` | JSON output, token from the environment, and no password or no-verify options |
| `tests/test_portable.py` | Evaluators import with `socket`, `ssl` and `urllib` blocked |

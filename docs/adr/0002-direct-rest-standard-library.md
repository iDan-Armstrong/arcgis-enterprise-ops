# 0002. Call the REST Administrator API directly, standard library only

Status: accepted (2026-11-04)

## Context

The ArcGIS API for Python wraps the Administrator API and handles tokens. It is also a
large install with many dependencies, and it hides the requests an administrator needs
to understand when something breaks.

## Decision

Use `urllib` from the standard library against the documented REST resources. Write the
token handling (`generateToken`, `client=referer`, token in the POST body) explicitly.

## Consequences

- No dependencies to install or audit; the package runs anywhere Python 3.11 does.
- Every request is visible in `client.py` and can be checked against Esri's docs.
- Features the Python API adds (OAuth, PKI, IWA) are not covered. Sites that require
  them are out of scope until an ADR adds them.

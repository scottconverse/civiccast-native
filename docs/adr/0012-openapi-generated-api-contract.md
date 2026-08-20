# ADR 0012: OpenAPI-generated API contract artifacts

Date: 2026-05-12

## Status

Accepted for v0.4 Slice 2.

## Context

CivicCast currently has FastAPI/Pydantic API models and separate
hand-maintained operator TypeScript API shapes. That split allows backend
fields, route additions, and enum-like value sets to drift from the operator
frontend and API documentation.

The project also needs a durable staff/public API reference. A hand-written API
reference would carry the same drift risk.

## Decision

FastAPI OpenAPI is the source of truth for API contract artifacts.

`scripts/generate-openapi-artifacts.py` imports `civiccast.app:create_app`,
reads `app.openapi()`, and writes:

- `civiccast/apps/portal-operator/src/types/api.generated.ts`
- `docs/API-REFERENCE.md`

Operator UI type modules may keep small wrapper aliases and display metadata,
but API row/request/response shapes should come from the generated OpenAPI
types wherever practical.

CI runs the generator in `--check` mode from `ci-docs`, and local pytest covers
the same drift gate.

## Consequences

- Backend API changes must update generated TypeScript types and API reference
  docs in the same change.
- Closed API vocabularies must use `Literal[...]` annotations in Pydantic
  models so OpenAPI exposes enum values instead of broad strings.
- The implementation uses a local Python generator instead of a new npm
  OpenAPI package, keeping the operator frontend supply chain unchanged for
  this substrate.

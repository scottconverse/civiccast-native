# OpenAPI Check Scope

Command artifact:

- `docs/releases/gauntletgate/v3.0.0-beta1-final-all-20260623/artifacts/openapi-check-final.txt`

Result:

- Exit code: `0`
- Scope: schema generation and committed artifact freshness
- Store mode: ephemeral in-memory staff stores only

The ephemeral-store warnings are expected for this schema-only gate. They do not
exercise durable installer-managed storage; durable runtime behavior is covered
by the host WSL2 installer proof and final runtime snapshot under
`host-wsl2-installer-proof-20260623/`.

# Security Policy

## Reporting a vulnerability

Please **do not open public GitHub issues** for security vulnerabilities. Public disclosure before a fix is shipped puts every CivicCast deployment — including school boards, HOA boards, public access TV stations, and small nonprofits running broadcast infrastructure — at risk.

### How to report

Email security reports to: **sconverse@gmail.com**

Subject line prefix: `[CivicCast Security]`

Include in the report:

- A description of the vulnerability and its impact.
- Steps to reproduce, or a proof-of-concept if one exists.
- The version (or commit SHA) you tested against.
- The deployment configuration if it's relevant (Mode A standalone, Mode B alongside CivicSuite, Tier 1 Streaming reference build, etc.).
- Whether you intend to publish a write-up, and if so, your preferred timeline.

### What to expect

- **Acknowledgement** within 72 hours.
- **Initial assessment** within 7 days, including whether we accept the report as a vulnerability and an estimated fix timeline.
- **Coordinated disclosure.** We will work with you on a disclosure timeline. Default is 90 days from initial acknowledgement, faster if a fix is ready, longer if the vulnerability is exceptionally severe and a coordinated patch across deployments is needed.
- **Credit.** You will be credited in the security advisory and the CHANGELOG entry unless you request anonymity.

### Scope

In scope:

- Code in this repository (all `civiccast.*` modules).
- Default deployment configurations.
- Documented installation procedures.
- The reference Windows + WSL2 installer.

Out of scope:

- Vulnerabilities in upstream dependencies (report to the dependency's maintainer; we will track CVEs and patch).
- Operator-side misconfiguration that the documentation explicitly warns against.
- Third-party syndication targets (YouTube, Facebook, etc.) — report to them directly.
- Denial-of-service via raw bandwidth exhaustion against a publicly-reachable origin (mitigation is operational, not in-code).

## Known posture: staff routes require bearer-token auth

Phase 1 hardening adds first-party bearer-token authentication to every
`/api/staff/*` endpoint (upload, schedule create/cancel, asset metadata edit,
live-room operation, caption review, translated-caption proof, summary review,
transcript CSV export, signed-record export/verification, publish
approval/preflight/retry, podcast episode generation, subscriber dispatch
proof, and installer first-run proof). Missing or invalid bearer tokens must
receive `401 Unauthorized`; reports of bypasses are vulnerabilities.

Bearer-token auth is not the whole deployment story. Public deployments must
still:

- Bind FastAPI to `127.0.0.1` only, OR
- Front it with an authenticating reverse proxy (nginx, Traefik, Caddy, mTLS, OIDC, etc.).

Configure `CIVICCAST_STAFF_TOKENS` before enabling staff routes. The runtime
app logs a startup warning until you acknowledge your network protection
posture by setting `CIVICCAST_AUTH_ACK=1`; that variable only suppresses the
warning and does not mint tokens, configure TLS, or configure proxy auth. The
full guidance lives at
[docs/ops/staff-route-protection.md](docs/ops/staff-route-protection.md).

## Security working group

There is no formal security working group yet. Until one exists, security reports are handled by the project maintainer. As the project grows, this section will be updated with the WG roster and contact channel.

## Encryption

If you need to encrypt the report, request a public key in a brief unencrypted email and one will be returned out-of-band.

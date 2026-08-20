# ADR 0020 — CDN providers: add Fastly + Akamai (S3-compatible)

**Status:** Accepted
**Date:** 2026-07-07
**Deciders:** Scott Converse (human director)
**Related rung:** 0.2.0 — Live Delivery at Scale
**Related spec section:** §10.5 CDN tier; 0.2.0 scope §Deliverables 4
**Supersedes:** N/A
**Amends:** ADR 0006 (CDN provider) — promotes Fastly from "future option" to shipped, and adds Akamai.

---

## Context

ADR 0006 shipped **BunnyCDN** (v1 default) and **Cloudflare R2** (DDoS-protection alternate), and registered **Fastly** in spec §10.5 as a *future* option — deliberately deferred on egress cost for Phase-0 pilots. The 0.2.0 scope (§Deliverables 4) names **Bunny / Fastly / Akamai** as the peer set the provisioning layer should be structured for.

The director decided (2026-07-07) to promote **Fastly** and **Akamai** from "future peers" to **shipped CDN providers now**, so a station can choose any of the four supported CDNs at setup time. ADR 0006's cost rationale still stands as *operator guidance* (Fastly is premium-priced; stations choose per cost vs. reach) — but the platform no longer withholds the option.

Both target providers are **S3-compatible object storage**, verified against their 2026 docs:

| Provider | S3 endpoint | Auth |
| :--- | :--- | :--- |
| Fastly Object Storage | `https://<region>.object.fastlystorage.app` | S3 key pair, SigV4 |
| Akamai (Linode) Object Storage | `https://<region>.linodeobjects.com` | S3 key pair, SigV4 |

Because both speak the S3 API, they fit the existing **push/upload** `CDNAdapter` model (0.2.0 scope §Architecture: "push … reuses the R2/Bunny adapters") without a new transport.

## Decision

Ship **Fastly Object Storage** and **Akamai (Linode) Object Storage** as CDN providers through a single generic **`S3CompatibleCDNAdapter`** (`civiccast.stream.cdn.s3_compatible`, boto3). The factory selects them via `CIVICCAST_CDN_PROVIDER = fastly | akamai` and builds each endpoint from the operator's region. Both are operator-enterable in the setup wizard with live **Test Connection** validation.

Cloudflare R2 keeps its own `CloudflareR2Adapter` (its endpoint is derived from an account id, not a region); it was not refactored onto the generic adapter to avoid churning tested code.

## Alternatives considered

**Option A — one generic `S3CompatibleCDNAdapter` (selected).** Both providers differ only by endpoint URL; one adapter parameterized by `endpoint_url` + region covers them and any future S3-compatible CDN (a new provider is a factory line, not a new class). Minimal code, maximal extensibility.

**Option B — a dedicated adapter class per provider (`FastlyAdapter`, `AkamaiAdapter`).** Mirrors the existing Bunny/R2 one-class-per-provider shape, but duplicates identical boto3 logic twice with no behavioural difference. Rejected as needless duplication.

## Consequences

### Positive
- Four supported CDNs (Bunny, R2, Fastly, Akamai), all operator-enterable + connection-tested from the setup wizard.
- The generic adapter makes any future S3-compatible CDN a one-line factory addition.

### Negative
- Fastly + Akamai require the `s3-cdn` optional extra (boto3); R2 keeps its own equivalent `cloudflare-r2` extra. BunnyCDN remains SDK-free for the default install.
- Fastly's egress is materially higher than Bunny/R2 (ADR 0006 §Alternatives, Option C). This is now the **operator's** cost/reach choice; the setup card and USER-MANUAL note it.

## Compliance
- Fastly + Akamai go through the `CDNAdapter` protocol (`upload_file`, `delete_file`, `public_url`, `health_check`); no direct provider HTTP calls outside `civiccast.stream.cdn`.
- Selected via `CIVICCAST_CDN_PROVIDER` and validated at startup by the same factory as the other providers; the setup wizard's Test Connection calls `health_check`.
- `docs/ops/cdn-and-providers.md` documents the new env variables and endpoint formats.

## References
- ADR 0006 — CDN provider (BunnyCDN default; this ADR amends its "Fastly not implemented at v1" stance)
- ADR 0007 — HLS packager design (CDN-agnostic local-directory output)
- docs/spec/0.2.0-scope.md §Deliverables 4
- [Fastly Object Storage docs](https://www.fastly.com/documentation/guides/platform/object-storage/)
- [Akamai/Linode Object Storage docs](https://techdocs.akamai.com/cloud-computing/docs/object-storage)

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*

# ADR 0006 — CDN provider: BunnyCDN as v1 default

**Status:** Accepted
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** 0.2 — Streaming origin
**Related spec section:** §10.5 CDN tier
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

Spec §10.5 requires a CDN to serve HLS segments and manifests from the streaming origin. ADR 0007 (HLS packager design) established that the packager writes to a local output directory; the CDN upload step is a separate adapter — so the CDN choice is isolated to one module and swappable by config post-1.0.

The v1.0 target deployment is sub-5000 concurrent viewers. Stations in this bracket care about:

1. **Operator simplicity.** A civic-media volunteer or city IT generalist sets this up. API key + pull-zone hostname is the ceiling of acceptable complexity for v1.
2. **Egress cost.** Most CivicCast stations are unfunded or minimally funded. Per-GB costs must stay in the sub-cent range.
3. **License / vendor posture.** No proprietary SDKs, no lock-in at the data layer. The adapter must be swappable without migrating stored assets (HLS segments are ephemeral — a re-encode populates any new CDN).
4. **DDoS resilience.** High-stakes meetings (budget votes, contentious zoning decisions) can attract coordinated traffic. Not every station needs DDoS protection, but the architecture must not *prevent* stations from choosing a provider that offers it.

Three providers are in scope per spec §10.5:

| Provider | Egress | Notes |
| :--- | :--- | :--- |
| BunnyCDN | $0.005/GB | HTTP pull-zone, REST upload API, global PoPs. No DDoS protection at base tier. |
| Cloudflare R2 + CDN | $0.005–0.01/GB | R2 object storage + Cloudflare's network; inherits Cloudflare's DDoS mitigation by default. More moving parts (R2 bucket + cache rules). |
| Fastly | $0.12–0.19/GB | Premium SLA, real-time purge, advanced routing. Overkill for Phase 0 pilot scale. |

D16 (default CDN provider, listed in spec §22) resolves at rung 0.2. This is that resolution.

## Decision

**BunnyCDN** is the documented v1 default CDN. The `civiccast.stream.cdn` adapter ships with a `BunnyCDNAdapter` implementation. **Cloudflare R2 + CDN** is documented in `USER-MANUAL.md` as the "DDoS-protection mode" alternate — operators swap it in by changing one config key; no code change required.

## Alternatives considered

**Option A — BunnyCDN.** HTTP pull-zone model: CivicCast uploads segments to BunnyCDN's storage zone via REST API; the pull-zone hostname is the public HLS origin URL. API key + zone hostname is the entire credential set. No SDK required — standard HTTP. Egress at $0.005/GB means a 60-minute 720p meeting (~2 GB) costs $0.01. Simple operator story, honest price point, no proprietary protocol. **Selected as v1 default.**

**Option B — Cloudflare R2 + CDN.** R2 is S3-compatible object storage; segments upload via standard `boto3` / `httpx`-based S3 client. Cloudflare's CDN fronts the R2 bucket and provides DDoS mitigation, bandwidth protection, and rate limiting as part of the standard tier — material for stations that face coordinated traffic during high-stakes meetings. More credential surface (R2 access key + secret + account ID + bucket name + public hostname) and more setup steps than BunnyCDN. Slightly higher egress when Cloudflare CDN-to-origin charges apply. **Selected as the documented DDoS-protection-mode alternate in USER-MANUAL.md.** The adapter interface is designed so a `CloudflareR2Adapter` can be contributed without modifying the packager.

**Option C — Fastly.** Real-time purge, sub-second cache invalidation, advanced routing rules. Correct choice for a large municipality streaming 200+ concurrent peak viewers with SLA commitments. Wrong for Phase 0 pilots: 24–38× the egress cost of Options A and B, plus enterprise onboarding overhead. Registered in spec §10.5 as a future option; not implemented at v1.

## Consequences

### Positive

- **Minimal operator credential surface.** BunnyCDN requires two values: Storage Zone API key and CDN hostname. One `civiccast config set` command per value. The pre-flight checklist verifies connectivity automatically.
- **No proprietary SDK.** The `BunnyCDNAdapter` uses standard HTTP (`httpx`). Audit-able, dependency-minimal, replaceable.
- **Swappable without asset migration.** HLS segments are re-generated from source on re-encode. Changing CDN providers is a config change + re-encode; no data migration.
- **DDoS-protection path documented.** Stations facing coordinated traffic have a clear upgrade path (Cloudflare R2 + CDN) with no code changes required. USER-MANUAL.md covers this explicitly.
- **Price appropriate for target audience.** $0.005/GB egress means a 30-segment 60-minute meeting at 720p (typical sub-5000-viewer scenario) costs cents, not dollars.

### Negative

- **No DDoS protection at the default tier.** BunnyCDN's base pull-zone does not include L7 DDoS mitigation. Stations expecting adversarial traffic should follow the Cloudflare alternate path.
- **BunnyCDN storage zone is not object-storage standard.** The upload API is BunnyCDN-specific (not S3-compatible). The adapter is a thin wrapper, but it's not interchangeable at the wire level with an S3 client. Mitigation: the `CDNAdapter` protocol in `civiccast.stream.cdn` is the interface all adapters implement; swapping is a config key, not a code change.
- **Single active adapter at v1.** Only `BunnyCDNAdapter` ships in the codebase at v1. `CloudflareR2Adapter` is documented as a community-contribution target; the adapter interface is designed to receive it.

### Risks

- **BunnyCDN pricing or API changes post-1.0.** Mitigation: the adapter isolation means a pricing event triggers a config migration, not a code rewrite. The USER-MANUAL.md Cloudflare alternate gives operators an immediate fallback path.
- **Pull-zone misconfiguration exposes segments publicly without CDN caching.** Mitigation: `civiccast doctor` checks CDN reachability and cache-header behavior on a probe object at setup time; misconfigurations are surfaced at the pre-flight checklist stage, not in production.
- **Cache invalidation at segment boundaries.** Short segment TTL (default: HLS segment duration × 2) limits stale-segment risk. VOD manifests use a separate longer TTL. Configured in `civiccast.stream.cdn.bunny` constants.

## Compliance

- `civiccast.stream.cdn` defines a `CDNAdapter` protocol (`upload_file`, `delete_file`, `public_url`). All CDN code goes through this protocol. Direct HTTP calls to BunnyCDN's API outside of `civiccast.stream.cdn.bunny` are forbidden; a lint comment in the module enforces this.
- The `CDN_PROVIDER` config key selects the active adapter. `civiccast config set cdn.provider bunny` (default) or `civiccast config set cdn.provider cloudflare_r2` (documented alternate).
  - *Addendum (2026-06-09, audit sprint Stage C):* the config key landed as the `CIVICCAST_CDN_PROVIDER` environment variable (`off`/`bunny`/`cloudflare_r2`/`stub`; the planned `civiccast config` command was never built). Selection is validated at app startup and `civiccast doctor` resolves through the same factory. See `docs/ops/cdn-and-providers.md`.
- `civiccast doctor` reports the active CDN provider, checks connectivity to the configured zone, and warns if the test probe returns a cache miss on second fetch (indicates CDN is not fronting properly).
- The broken-media regression suite (Sprint 0.2 exit criterion) runs against a local stub adapter so CDN credentials are not required in CI.

## References

- CivicCastUnifiedSpec-v2.md §10.5 CDN tier
- CivicCastUnifiedSpec-v2.md §22 Open Decisions — D16
- CivicCast-ReleasePlan-0.1-to-1.0.md — rung 0.2, "Decisions that resolve during the ladder"
- ADR 0007 — HLS packager design (establishes CDN-agnostic local-directory output; this ADR names the first adapter)
- [BunnyCDN Storage API docs](https://docs.bunny.net/reference/storage-api)
- [Cloudflare R2 S3-compatible API docs](https://developers.cloudflare.com/r2/api/s3/api/)

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*

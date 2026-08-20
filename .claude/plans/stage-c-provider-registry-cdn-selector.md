# Stage C — Provider Registry/Factory Seams + Config-Driven CDN Selector

> Sprint plan stage 3 (`.claude/plans/audit-sprint-1.md`). Scope per plan:
> "add provider registry/factory seams and config-driven CDN selector."
> Mocks stay the defaults (sprint rule); real external provider adapters are
> explicitly out of scope. Includes the standing CDN/trusted-proxy
> reconciliation follow-up from Stage A.

**Goal:** Every external-provider touchpoint resolves through a config-driven
seam instead of a hard-instantiated class: a `ProviderRegistry` (mock defaults,
env-selected, unknown names fail fast) for IA / NAS / YouTube / mail / webhook,
and a CDN factory that reads `CIVICCAST_CDN_PROVIDER` to select
bunny / cloudflare_r2 / stub / off — replacing the CLI's hard-instantiated R2
probe. CAPABILITIES rows updated honestly in the same commit.

**Architecture:** `civiccast/stream/cdn/factory.py` (CdnSettings.from_env +
build_cdn_adapter) and `civiccast/platform/providers.py` (ProviderRegistry,
default registrations = today's mocks). `publish/service.approve_publish`
resolves ia/nas/youtube through the registry; `subscribe/service` keeps its
injection seam but defaults route through the registry; the CLI doctor gains a
provider-aware CDN check including the trusted-proxy reconciliation warning;
`create_app()` validates `CIVICCAST_CDN_PROVIDER` fail-fast and exposes a lazy
`app.state.resolve_cdn_adapter`.

## Tasks (TDD: each red first)

### C1: CDN factory

- Test: `tests/stream/test_cdn_factory.py`
  - default (unset / `off`) → settings.provider == "off", build → None
  - `stub` → StubCDNAdapter
  - `bunny` + `CIVICCAST_BUNNY_{STORAGE_ZONE,ACCESS_KEY,CDN_HOSTNAME}` →
    BunnyCDNAdapter; missing creds → ValueError naming the variables
  - `cloudflare_r2` + the five `CIVICCAST_R2_*` vars → CloudflareR2Adapter
    (skip-gated if boto3 extra absent); missing creds → ValueError
  - invalid value → ValueError listing valid providers
- Implement: `civiccast/stream/cdn/factory.py`; update `cdn/__init__.py`
  docstring (env key, not the never-built `civiccast config` command).

### C2: Provider registry

- Test: `tests/platform/test_provider_registry.py`
  - default resolution: internet_archive→MockInternetArchiveClient,
    local_nas→MockLocalNasArchiveClient, youtube→MockYouTubeClient,
    mail→LocalMailbox, webhook→LocalWebhookClient
  - env switch `CIVICCAST_PROVIDER_YOUTUBE=mock` explicit OK; unknown name →
    ProviderConfigurationError listing registered names for that kind
  - register() extension point: a custom factory becomes resolvable
- Implement: `civiccast/platform/providers.py` with
  `ProviderRegistry`, `default_registry()` (module-level, env-read at build),
  env keys `CIVICCAST_PROVIDER_{INTERNET_ARCHIVE,LOCAL_NAS,YOUTUBE,MAIL,WEBHOOK}`.

### C3: Resolve through the seams

- Test: publish service builds its clients from an injected registry
  (sentinel registry observed); default behavior unchanged (mock outputs
  byte-identical to today's deterministic proofs).
- Implement: `approve_publish(..., registry: ProviderRegistry | None = None)`;
  `subscribe/service` default mail/webhook from registry.

### C4: App + CLI wiring

- Test: `create_app()` with `CIVICCAST_CDN_PROVIDER=banana` raises ValueError;
  with `stub` boots and `app.state.resolve_cdn_adapter()` returns a
  StubCDNAdapter.
- Implement in `app.py` (validate at startup beside the other fail-fast
  checks); CLI doctor `_doctor_check_cdn()` replaces the R2-only probe:
  reports selected provider, constructs via factory, health-checks where the
  adapter supports it, and warns when a CDN is selected while
  `CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS` is empty (Stage A reconciliation:
  behind a CDN, visitor IPs arrive via X-Forwarded-For from the CDN edge, so
  the analytics rate limiter must trust the CDN ranges or it keys on edge IPs).

### C5: Docs + truth

- `docs/ops/cdn-and-providers.md`: selector + registry env reference, per-CDN
  credential variables, and the **trusted-proxy reconciliation** section.
- Link from `docs/technical-ops-reference.md`; note in ADR 0006 that the
  config key landed as `CIVICCAST_CDN_PROVIDER` (dated addendum).
- `CAPABILITIES.md`: CDN row note — selector now config-driven; upload
  pipeline wiring still pending (honest). Mocks row note — registry seam
  exists; adapters still mock-only.
- CHANGELOG `[Unreleased]` entries.

### C6: Gate + result file + commit

- Full pytest (with `CIVICCAST_POSTGRES_TEST_URL`), ruff/format/mypy scoped,
  OpenAPI artifact check (no API change expected), `git diff --check`.
- Result file `<ts>-local-stage-c-provider-registry.md`.
- Commit: `feat(platform): config-driven CDN selector and provider registry seams refs #98`

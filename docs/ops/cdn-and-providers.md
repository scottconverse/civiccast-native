<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# CDN Selector and Provider Registry

How CivicCast selects its CDN adapter and external-provider clients
(Stage C of the audit sprint). Both are environment-driven and fail fast at
app startup on invalid values — a typo can never silently fall back.

## CDN selector

```
CIVICCAST_CDN_PROVIDER = off (default) | bunny | cloudflare_r2 | fastly | akamai | stub
```

| Provider | Credential variables |
|---|---|
| `off` | none — no CDN configured; the resolver hands out nothing. |
| `bunny` (ADR 0006 v1 default choice) | `CIVICCAST_BUNNY_STORAGE_ZONE`, `CIVICCAST_BUNNY_ACCESS_KEY` (Storage Zone API key), `CIVICCAST_BUNNY_CDN_HOSTNAME` (pull-zone host, e.g. `myzone.b-cdn.net`) |
| `cloudflare_r2` | `CIVICCAST_R2_ACCOUNT_ID`, `CIVICCAST_R2_ACCESS_KEY_ID`, `CIVICCAST_R2_SECRET_ACCESS_KEY`, `CIVICCAST_R2_BUCKET`, `CIVICCAST_R2_PUBLIC_BASE_URL` (requires the `cloudflare-r2` optional extra) |
| `fastly` (ADR 0020) | `CIVICCAST_FASTLY_REGION` (e.g. `us-east`), `CIVICCAST_FASTLY_ACCESS_KEY_ID`, `CIVICCAST_FASTLY_SECRET_ACCESS_KEY`, `CIVICCAST_FASTLY_BUCKET`, `CIVICCAST_FASTLY_PUBLIC_BASE_URL`. Fastly Object Storage (S3-compatible); endpoint `https://<region>.object.fastlystorage.app`; requires the `s3-cdn` optional extra. |
| `akamai` (ADR 0020) | `CIVICCAST_AKAMAI_REGION` (e.g. `us-east-1`), `CIVICCAST_AKAMAI_ACCESS_KEY_ID`, `CIVICCAST_AKAMAI_SECRET_ACCESS_KEY`, `CIVICCAST_AKAMAI_BUCKET`, `CIVICCAST_AKAMAI_PUBLIC_BASE_URL`. Akamai/Linode Object Storage (S3-compatible); endpoint `https://<region>.linodeobjects.com`; requires the `s3-cdn` optional extra. |
| `stub` | `CIVICCAST_CDN_STUB_ROOT` — local directory, `file://` URLs; tests/proofs only |

Missing credentials for the selected provider stop the app at startup with the
exact variable names. `civiccast doctor` reports the selected provider and
constructs the adapter through the same factory. Every adapter implements a
`health_check` connectivity probe; the setup wizard's **Test connection** action
and `civiccast doctor` use it to confirm the entered credentials actually reach
the provider before publishing depends on them.

The selector makes the adapter available (`app.state.resolve_cdn_adapter`),
and the recording finalization worker publishes through it: after a session's
recording is packaged for playback, the worker uploads the HLS tree to the
selected CDN under `live/<live_session_id>/…` — segments first, manifest
last — and sets the asset's `manifest_url` to the CDN public URL only after
the upload succeeds. When both are configured, the CDN URL takes precedence
over `CIVICCAST_LIVE_MANIFEST_BASE_URL`. A failed upload is a classified,
retryable finalization failure (`cdn.upload_failed`) visible on the operator
finalization panel; the local package is never deleted. The same selection
applies to the external worker process (`python -m
civiccast.live.finalization_worker`), which reads `CIVICCAST_CDN_PROVIDER`
from its own environment.

### R2 concierge: paste-one-token CDN provisioning

The five `CIVICCAST_R2_*` / `cloudflare-r2` setup-wizard fields above are the
adapter's contract, not the operator's entry point. PEG stations and schools
do not arrive holding a Cloudflare account id, an R2 keypair, a bucket name,
and a public URL. `POST /api/staff/installer/cdn-concierge/r2` (`setup_admin`
role, same gate as the provider-credentials routes) collapses that to one
pasted Cloudflare API token (scoped to R2 Edit):

```
operator          CivicCast                              Cloudflare API
   |  paste token     |                                          |
   |----------------->|  GET  /user/tokens/verify (Bearer token) |
   |                  |----------------------------------------->|
   |                  |<-- {success, result:{id, status}} -------|
   |                  |  GET  /accounts                          |
   |                  |----------------------------------------->|
   |                  |<-- {result:[{id, name}, ...]} -----------|
   |                  |  POST /accounts/{id}/r2/buckets           |
   |                  |----------------------------------------->|
   |                  |<-- created (or "already exists") --------|
   |                  |  PUT  .../buckets/{b}/domains/managed     |
   |                  |----------------------------------------->|
   |                  |<-- {result:{domain: "pub-<hash>.r2.dev"}}-|
   |                  |  derive S3 keypair (see below)            |
   |                  |  save via existing provider-credential    |
   |                  |  store, then run the existing             |
   |                  |  health_check test-connection             |
   |<-- ok / failed --|                                           |
```

Implementation: `civiccast.installer.r2_concierge.provision_r2` (pure
function, an injected `httpx.Client` so tests never hit the network) does
the five Cloudflare calls and returns a `ConciergeResult`; the router
endpoint stores the result via the existing `save_provider_credentials` /
`ProviderCredentialSetupRequest` path and re-runs
`cdn_bridge.check_provider_connection("cloudflare-r2")` before responding —
the same live health check the manual "Test connection" button uses.

**S3 keypair derivation.** Cloudflare documents that an R2-scoped API
token's own `id` (from `/user/tokens/verify`) doubles as the S3
`access_key_id`, and the S3 `secret_access_key` is the lowercase hex
SHA-256 of the token *value*. One pasted token therefore yields the whole
R2 S3 keypair with no second minting step. The pasted token is used
in-memory only for the Cloudflare calls above and is never logged, stored,
or echoed back in any response — only the derived keypair and ids are
persisted, through the same credential store every other provider uses.

**Error states** (`R2ConciergeResponse.error_code`), each operator-readable
and distinct so the UI can render the right next step:

| Code | Meaning | Operator next step |
|---|---|---|
| `invalid_token` | Cloudflare rejected the token, or it couldn't be reached to verify. | Create a new token scoped to R2 Edit and paste it again. |
| `r2_not_enabled` | Cloudflare error 10042 — the account has never turned on R2. | Follow the returned `deep_link` (`https://dash.cloudflare.com/?to=/:account/r2`) to enable it one time, then Retry. Free tier available; Cloudflare may still ask for a payment method at $0. |
| `no_account` | The token sees zero accounts, or more than one (ambiguous — pass an explicit account). | Check the token's account scope, or provision again for a specific account. |
| `bucket_error` | Bucket creation failed for a reason other than "already exists" (which is treated as idempotent success). | Retry, or check the token's R2 Edit scope. |
| `domain_error` | Enabling the bucket's managed `pub-<hash>.r2.dev` domain failed. | Retry; if it persists, enable the domain manually from the R2 dashboard. |

**Honesty note:** the exact Cloudflare error code for "bucket already
exists" is not published in Cloudflare's docs as of this writing; the
concierge matches on the error message substring instead of a specific code
so idempotent re-provisioning is robust regardless. This path, and the
`r2_not_enabled` guided state, have not yet been exercised against a live
Cloudflare account with R2 turned on — verify against the real API before
relying on this in production (`tests/installer/test_r2_concierge.py`
covers every branch against a mocked transport, not a live one).

### VOD local-serve (stock install, `off` / no provider)

With `CIVICCAST_CDN_PROVIDER=off` (the default) and no
`CIVICCAST_LIVE_MANIFEST_BASE_URL` set, the worker does **not** leave
`manifest_url` null. It points recordings at the app's own
`civiccast.stream.media_router` mount (`GET /media/vod/{asset_id}/...`),
which serves the packaged HLS tree straight off local disk with immutable
long-TTL caching on segments and correct `.m3u8`/`.ts` content-types — so a
resident's browser has something to actually play on a stock install, no CDN
or manual config required. The default base URL is
`http://127.0.0.1:8000` (the README's documented `uvicorn` run command);
override it with `CIVICCAST_LOCAL_MEDIA_BASE_URL` if the app is fronted by a
reverse proxy or a different bind address. Plain `http://` on a loopback host
(`127.0.0.1` / `localhost` / `::1`) is exempted from the `manifest_url`
https-only rule for this reason — see
`civiccast.vod.models._is_loopback_http_url`. A real external
`CIVICCAST_CDN_PROVIDER` or `CIVICCAST_LIVE_MANIFEST_BASE_URL` still take
precedence over local-serve, per the ordering above.

### Live local-serve (stock install, `hls` egress sink configured)

The live channel has its own local-serve path, parallel to VOD but resolved
differently: a channel's `GET /api/public/live/current` response only
defaults `manifest_url` to a local URL when that channel has an `hls` egress
sink configured (**Channels → Egress → Sinks** or
`POST /api/staff/egress/channels/{id}/config`, sink `kind: "hls"`, `uri` a
local directory path). When configured, the persistent ffmpeg egress
encoder tees a rolling live HLS manifest + segments (`civiccast.egress.sinks
.HlsSink`: 2-second segments, a 6-segment/12-second sliding window,
`-hls_flags delete_segments+append_list` so ffmpeg itself prunes old
segments — no separate cleanup process) into that directory, and
`civiccast.stream.media_router`'s `GET /media/live/{channel_id}/...` mount
serves it straight off local disk (short-TTL manifest caching so a resident's
player re-polls promptly; long-TTL immutable segment caching, same as VOD).
An explicit `manifest_url` query param on `/api/public/live/current` (a
deployer's own CDN or reverse-proxy URL) still overrides the local default.
A channel with no `hls` sink configured still reports `on_air` correctly —
`manifest_url` stays `null`, matching the VOD "nothing configured yet"
posture rather than erroring.

## Trusted-proxy reconciliation (Stage A follow-up)

The public analytics ingest hardening (Stage A) resolves visitor IPs for rate
limiting and trusts `X-Forwarded-For` hops only from
`CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS`. **If your CDN fronts the public
portal**, visitor requests reach CivicCast from CDN edge IPs:

- Without the CDN's egress ranges in
  `CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS`, rate limits key on the CDN edge
  IPs — a busy edge node can exhaust the per-visitor budget for everyone
  behind it, and abuse attribution is wrong.
- With the ranges configured, the limiter sees real visitor IPs from the
  forwarded chain.

`civiccast doctor` warns when a CDN provider is selected while the
trusted-proxy list is empty. Source the ranges from your CDN's published IP
list and keep them current. If the CDN only serves media (not the portal/API),
no reconciliation is needed — but say so deliberately, don't discover it.

## Provider registry

External-provider clients resolve through
`civiccast.platform.providers.default_registry()`:

```
CIVICCAST_PROVIDER_INTERNET_ARCHIVE = mock (default) | real
CIVICCAST_PROVIDER_LOCAL_NAS        = mock (default) | real
CIVICCAST_PROVIDER_YOUTUBE          = mock (default) | real
CIVICCAST_PROVIDER_MAIL             = mock (default) | real
CIVICCAST_PROVIDER_WEBHOOK          = mock (default) | real
```

The deterministic mock/local clients remain the defaults; real adapters ship
for Internet Archive, YouTube, mail (Beta sprint B5), subscriber webhooks
(issue #111), and the local-NAS archive copy (issue #112). Selecting `real`
without that provider's credentials fails fast with the exact variable names;
selecting a name that isn't registered fails fast listing the registered
options. A mock is never a silent fallback.

| Provider (`real`) | Credential / config variables |
|---|---|
| `internet_archive` | `CIVICCAST_IA_ACCESS_KEY`, `CIVICCAST_IA_SECRET_KEY` (archive.org S3 keys); optional `CIVICCAST_IA_COLLECTION` (default `opensource_movies`), `CIVICCAST_IA_ITEM_PREFIX` (default `civiccast`). Uploads via the S3-like API (`s3.us.archive.org`). |
| `youtube` | `CIVICCAST_YOUTUBE_CLIENT_ID`, `CIVICCAST_YOUTUBE_CLIENT_SECRET`, `CIVICCAST_YOUTUBE_REFRESH_TOKEN` (OAuth obtained out-of-band); optional `CIVICCAST_YOUTUBE_MEDIA_ROOT` (recordings directory for asset-id VOD uploads), `CIVICCAST_YOUTUBE_PRIVACY` (`unlisted` default). |
| `mail` | `CIVICCAST_SMTP_HOST`, `CIVICCAST_SMTP_FROM`; optional `CIVICCAST_SMTP_PORT` (587), `CIVICCAST_SMTP_USERNAME` + `CIVICCAST_SMTP_PASSWORD` (must be set together), `CIVICCAST_SMTP_STARTTLS` (`1` default; set `0` only for a loopback/test relay). |
| `webhook` | No credentials (each subscription carries its own sealed signing secret). Optional `CIVICCAST_WEBHOOK_TIMEOUT_SECONDS` (30 default). Delivery: POST of the canonical JSON payload with `X-CivicCast-Signature: sha256=<hmac>`; failures queue durably and the webhook retry worker re-delivers with backoff (`CIVICCAST_WEBHOOK_RETRY_WORKER=inline\|off`, `CIVICCAST_WEBHOOK_RETRY_POLL_SECONDS` 60, `CIVICCAST_WEBHOOK_RETRY_BACKOFF_SECONDS` 120, `CIVICCAST_WEBHOOK_RETRY_MAX_ATTEMPTS` 8; see `docs/ops/background-workers.md`). |
| `local_nas` | `CIVICCAST_NAS_ARCHIVE_PATH` — the mounted archive directory (local mount or UNC path; the OS mount is the transport, covering SMB/NFS appliances). No credentials. Each publish approval writes `archive/{asset_id}` (canonical, overwritten on republish) plus `snapshots/{asset_id}/{timestamp}` (write-once per run); each copy is fsynced and independently sha256 read-back verified — no proof is minted on a mismatch. |

Full-media publishing: when the publish approval can resolve the asset's
local recording file (live recordings via the finalization job), the real
Internet Archive and YouTube adapters receive the actual media
(`upload_path` / `upload_vod_path`). When no local media resolves, the
deterministic verification payload is sent instead — the proofs stay honest
either way. A real-provider delivery failure marks only that surface
`failed` (retryable from the publish dashboard); it never fails the whole
approval.

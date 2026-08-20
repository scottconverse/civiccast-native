# SPDX-License-Identifier: Apache-2.0
# 1.2 - CivicCast Internal Hardening

## Purpose

v1.2 is the first post-public-availability hardening line after the v1.1.1
public patch release. The goal is to close the highest-value operational and
architectural deferrals without moving the immutable v1.1.0 or v1.1.1 tags.

**Release claim:** CivicCast v1.2.0 strengthens the public v1.1 line with
staff-token lifecycle controls, real first-run test-and-verify flows,
app-factory-scoped stores, required NATS JetStream broker traffic, required
local-CA mTLS identity for all installs, default-off ActivityPub federation
that works when explicitly enabled, and credential-gated proof lanes for RTX,
air-gapped, and external-provider evidence when the required hardware or
secrets are available.

Runtime implementation proceeds through a scoped Agent Pipeline run. Proof lanes
that require unavailable hardware or credentials stay blocked with explicit
status instead of being treated as passed.

## 1.2.1 - Operator First-Mile Success

The v1.2.1 hardening line proves: CivicCast transitions from auditor-proof technical preview to operator-first beta by pairing usable onboarding with safe production defaults and real-boundary proof.

Required modules for this line are `civiccast.auth`, `civiccast.subscribe`,
`civiccast.schedule`, `civiccast.summary`, `civiccast.installer`,
`civiccast.apps.installer`, `civiccast.apps.portal-operator`,
`civiccast.apps.portal-public`, `docs`, and `tests`.

- Remove hardcoded CivicCast subscription token and encryption secrets from production defaults.
- Fix or explicitly deprecate staff environment-token fallback when Postgres token store is enabled.
- Show operators how to verify Windows installer release assets.
- Rewrite the README, FAQ, user manual, API guide, landing page, and discussion seeds around operator tasks.
- Add tactile hover, active, and focus affordances to installer and operator portal controls.
- Add real-boundary smoke tests beside existing mocked state-coverage tests.
- Fix public subscription rate limiting, async upload blocking, past coming-up events, summary review N+1, airgap path handling, Playwright retries, and stale mock literals where feasible.
- Move generated audit packages to a deliberate tracked docs/audits location or out of the repo.
- Run cleanroom validation before v1.2.1 release.

Exit criteria:

- A non-technical operator path is the first path in README/docs.
- Production startup rejects unsafe generated-secret posture or creates durable local secrets with a documented migration/rotation path.
- Focused tests prove security/auth, subscription, schedule, summary, installer/operator UX, and real-boundary smoke behavior.
- Generated docs/manual/API artifacts are current and version-consistent.
- Policy, full test suite, frontend lint/build/e2e/a11y, Docker/Postgres gates where available, cleanroom validation, and CI pass.

## Scope

### Audit Findings Carried Into v1.2

The v1.2 line must close or explicitly reclassify every finding below before a
v1.2 tag:

| ID | Required v1.2 outcome |
| --- | --- |
| BOOT-001 | Offline model bundle CLI emits real SHA-256 hashes from actual bundle files or fails actionably. |
| TEST-001 | Release verification runs policy against the active release run id, not the historical v1.1 run id. |
| DOC-001 | Internal handoff state is updated before each branch handoff; stale handoff text is not used as release authority. |
| DOC-002 | Current-facing v1.1 evidence copy no longer describes the published line as a release candidate. |
| SEC-001 | Staff tokens have issuance, hashing, revocation, rotation, audit, and fail-closed semantics. |
| ENG-001 | Router module-scope store singletons are removed in favor of app-factory-scoped state. |
| ENG-002 | ADR 0001 is resolved by a broker contract implementation or a superseding ADR. |
| BOOT-002 | First-run wizard target checks are real test-and-verify flows or explicit credential/hardware stop states. |

### Staff Token Lifecycle

- Add explicit staff token issuance, listing, revocation, and rotation flows
  through `civiccast token issue/list/revoke/rotate`.
- Store token material as salted hashes; never store or log bearer tokens in
  plaintext after issuance.
- Record operator id, display name, scopes, issued-at, last-used-at,
  revoked-at, and revocation reason.
- Ensure staff-route auth fails closed when no valid token configuration or
  token database exists.
- Bind every staff-route audit event to the verified operator identity.
- Keep OS credential-store integration for local operator CLI token storage.
- Preserve the environment-token compatibility path only as a legacy fallback
  when the database-backed lifecycle store is not configured.
- Add tests for issuance, hash verification, revocation, rotation, audit-log
  identity, missing-token 401s, and revoked-token 401s.

### First-Run Wizard Test-And-Verify

- Promote the v1.1 first-run wizard contracts into real E2E flows.
- Cover CDN, syndication, Internet Archive, NAS, staff token, model download,
  public portal, and publish-target test-and-verify steps.
- Each target gets a clear operator-facing success state, recoverable error
  state, retry action, and durable proof artifact.
- Credential-required steps must stop as `credential_or_secret_required`
  instead of silently passing with deterministic proof.
- No secret values are committed, logged, screenshotted, or uploaded.

### Module-Scope Store Singleton Refactor

- Inventory router-level `_default_store`, `_DEFAULT_*_STORE`, and equivalent
  module-scope store singletons across `civiccast/`.
- Move default store ownership into the app factory and `app.state`.
- Add a typed store bundle accepted by `create_app()` for production and tests.
- Rewrite dependency functions to read request-scoped app state.
- Tests inject stores through FastAPI dependency overrides or the app factory,
  not by mutating router module globals.
- Acceptance: a repo-wide grep for module-scope router store singletons returns
  zero matches, and cross-test state leakage tests pass.

### NATS JetStream And Internal mTLS Foundation

NATS JetStream and internal mTLS are required v1.2 foundations, not optional
posture notes.

- Production broker configuration requires a NATS JetStream adapter.
- Development and unit tests may keep the in-process adapter by explicit
  configuration, but release proof paths must not silently fall back to it.
- NATS stream and subject setup must be installer-managed and reported by
  `civiccast doctor` or the installer readiness summary in operator language.
- Required modules for this foundation are `civiccast.platform`,
  `civiccast.installer`, and `civiccast.certs`.
- mTLS local CA creation and certificate rotation are implemented and tested.
- Every install has CivicCast local-CA mTLS identity material for internal
  services; single-host installs may bind services to loopback, but the
  certificate posture still exists and is checked.
- Internal service certificates rotate on the documented 90-day cadence through
  `civiccast cert rotate` or an equivalent installer-owned command path.
- Installer readiness reports NATS and mTLS state with actionable operator
  language.

### ADR 0001 Resolution

ADR 0001 remains accepted and must stop drifting from the implementation.
v1.2 resolves it in one of two explicit ways:

- Required: implement `civiccast.platform.broker` with a `BrokerClient`
  Protocol, a concrete NATS JetStream adapter, and an explicitly test/dev-only
  in-process adapter. Wire at least one clean seam, such as publish or captions,
  through the broker contract.

The v1.2 plan does not permit ADR 0001 to remain accepted-but-unimplemented
without a concrete NATS JetStream adapter.

### RTX Caption Proof

- When the RTX runner is available, run faster-whisper `whisper-large-v3` INT8
  against the release fixture set.
- Capture runtime tag, model digest or model source hash, GPU/VRAM evidence,
  WER result, and comparison against the v1.1 baseline.
- If hardware is unavailable, keep implementation ready and mark the proof lane
  blocked as `hardware_unavailable`, not passed.

### Air-Gapped VM Proof

- Build a VM cleanroom that installs CivicCast from release candidate
  artifacts with no network access.
- Install the offline model bundle and verify all required model hashes.
- Exercise the installer, staff-token setup, model availability check, public
  portal launch, and a minimal signed-record export.
- Record VM base image, network isolation method, artifact hashes, command log,
  and pass/fail evidence.

### External Provider Proofs

External proof work is credential-gated. Missing credentials stop the run as
`credential_or_secret_required`; deterministic provider proof does not satisfy
this lane.

- Internet Archive controlled test item upload.
- YouTube Live private or unlisted ingest proof.
- YouTube VOD private or unlisted upload proof.
- Local NAS rsync hash-verified copy.
- Local NAS ZFS snapshot/send proof unless explicitly deferred again.
- Email double opt-in: signup, confirmation send, token click, and publish
  notification delivery.
- Webhook delivery to a controlled HTTPS endpoint with HMAC verification.
- Public podcast RSS validation from the test portal.

### ActivityPub Federation Scoped Amendment

This amendment was expanded by the scoped run
`2026-05-21-activitypub-full-federation` after the NATS and mTLS foundation
landed on main. It proves: CivicCast keeps federation disabled by default, but
enabled deployments have a signed, durable ActivityPub station actor with
Mastodon-style controls.

Required modules for this amendment are `civiccast.activitypub`,
`civiccast.subscribe`, and `civiccast.publish`.

- Add a station actor with WebFinger, actor discovery, inbox, outbox,
  followers, and local NodeInfo-style discovery endpoints.
- Require explicit public base URL and generated station key material before
  enabled federation routes advertise the actor.
- Verify inbound HTTP Signatures and Digest headers for inbox traffic.
- Sign outbound Accept and Create deliveries with the station key.
- Persist followers, outbox activities, and delivery attempts.
- Provide open, limited, approval-only, disabled, blocklist, allowlist, and
  authorized-fetch controls.
- Convert local meeting-publish events into signed ActivityPub Create/Note
  delivery attempts for accepted followers.
- Add tests for actor discovery, WebFinger, signed Follow, approval-only
  queueing and approval, disabled mode, blocklist rejection, limited-mode
  allowlist rejection, authorized fetch, rate limiting, durable persistence,
  and outbound signature verification.
- Update docs and release evidence so ActivityPub is described as default-off
  but fully implemented when enabled.
  and moderation review exist.

### Cable File Package Scoped Amendment

This amendment is activated by the scoped run
`2026-05-19-v1.2-cable-file-package` after the ActivityPub station-actor
surface landed on main. It proves: CivicCast has a local cable file-package
output surface for PEG/headend handoff, while NDI, SDI, DeckLink, and live
cable delivery proof remain deferred.

Required modules for this amendment are `civiccast.cable` and
`civiccast.publish`.

- Add a file-package builder that copies real local source media and a caption
  sidecar into a package directory, writes `manifest.json`, writes
  `SHA256SUMS`, and emits a ZIP package with a package-level SHA-256 proof.
- Add `civiccast cable package` for integrators who need to produce a PEG or
  headend handoff package from local files.
- Add an optional `cable-file-package` publish surface. It succeeds only when
  the local media path, caption sidecar folder, and cable output folder are
  configured; otherwise it fails with operator-actionable next steps and does
  not block archive verification.
- Update docs and evidence so file-package output is implemented, while NDI
  output, SDI/DeckLink output, live headend delivery, and station proof remain
  deferred.

### NDI Output Scoped Amendment

This amendment is activated by the scoped run
`2026-05-19-v1.2-ndi-output` after the cable file-package and air-gapped
wheelhouse proof landed on main. It proves: CivicCast has an NDI output
planning and runtime-readiness surface for local media handoff through
FFmpeg, while live NDI receiver proof, SDI/DeckLink output, live cable
headend delivery, and station proof remain deferred.

Required modules for this amendment are `civiccast.cable`, `civiccast.cli`,
and `docs.releases`.

- Add an NDI output planner that builds the exact FFmpeg argument list for
  local-file-to-NDI output with a named channel, explicit frame rate, video
  size, pixel format, and NDI muxer.
- Add an NDI runtime-readiness check that uses the existing FFmpeg wrapper to
  detect an installed NDI-capable FFmpeg muxer and reports actionable blocked
  states when FFmpeg or NDI muxer support is missing.
- Add `civiccast cable ndi-plan` and `civiccast cable ndi-check` CLI commands
  for integrators preparing an NDI proof lane.
- Update docs and evidence so NDI output planning/readiness is implemented,
  while live NDI receiver proof, SDI/DeckLink output, live headend delivery,
  and station proof remain deferred.

### Windows Installer And NDI Sender Proof Scoped Amendment

This amendment is activated by the scoped run
`2026-05-20-windows-installer-ndi-sender` after the NDI output planning
surface landed on main. It proves: CivicCast has a Windows double-click
installer artifact path and NDI sender proof path for local operator testing.

Required modules for this amendment are `civiccast.apps.installer`,
`scripts`, `civiccast.cable`, `civiccast.cli`, and `docs.releases`.

- Package the existing Tauri-compatible installer walkthrough into a Windows
  desktop installer artifact or fail with precise missing-tool evidence.
- Keep Windows services inside WSL2 Ubuntu per ADR 0003; this amendment does
  not introduce a native Windows service runtime.
- Extend release artifact generation so the Windows installer artifact is
  hashed and recorded when it exists, without substituting placeholder bytes.
- Attempt the cleanest NDI sender path first: detect or install an FFmpeg
  build with NDI output support compatible with the installed NDI runtime.
- If a prebuilt NDI-capable FFmpeg path is not available, record the exact
  build/runtime blocker and either keep `civiccast cable ndi-check`
  fail-closed or provide a clearly labeled internal lab sender that uses
  FFmpeg rawvideo plus the local NDI runtime without claiming a public
  redistributable FFmpeg+NDI binary.
- Update docs and evidence so Windows installer packaging and NDI sender
  readiness distinguish package/build proof from clean-machine install proof
  and live receiver proof.

### Air-Gapped VM Proof Scoped Amendment

This amendment is activated by the scoped run
`2026-05-19-v1.2-airgap-vm-proof` after the cable file-package output landed
on main. It proves: CivicCast has a repeatable WSL2 VM air-gap proof runner
that verifies release artifact hashes, verifies all three offline model bundle
artifacts from real bytes, and removes the VM default route during bundle
verification, while full no-network application install remains blocked until
release-candidate artifacts include an offline Python dependency wheelhouse.

Required modules for this amendment are `scripts`, `civiccast.installer`, and
`docs.releases`.

- Add `scripts/run_airgap_vm_proof.py` to run host artifact checks, WSL2 target
  checks, network-isolated model bundle verification, and durable evidence
  writing.
- Require the proof runner to report a blocked state when the release candidate
  lacks an offline dependency wheelhouse, rather than pretending the app can be
  installed from a single wheel with no network access.
- Add regression tests for release artifact hash mismatch, missing model bundle
  files, missing wheelhouse detection, evidence writing, and Windows-to-WSL path
  conversion.
- Update v1.2 evidence so the model-bundle-in-VM proof is recorded, and the
  remaining full app install requirement is explicitly tied to a future
  wheelhouse artifact.

### Air-Gapped Wheelhouse Proof Scoped Amendment

This follow-up amendment is activated by the scoped branch
`hardening/v1.2-airgap-wheelhouse-proof`. It proves: CivicCast has a Linux
CPython 3.12 offline dependency wheelhouse and a WSL2 proof runner that removes
the VM default route, installs CivicCast from the release-candidate application
wheel plus wheelhouse, imports the installed application, and verifies all
three offline model bundle artifacts from real bytes.

Required modules for this amendment are `scripts`, `civiccast.installer`, and
`docs.releases`.

- Extend `scripts/build_release_artifacts.py` with a `--wheelhouse` lane that
  exports locked runtime dependencies, downloads Linux x64 wheels, adds Linux
  marker dependencies that a Windows host export would otherwise skip, copies
  the application wheel, and writes `WHEELHOUSE-MANIFEST.json` with SHA-256
  values.
- Extend `scripts/run_airgap_vm_proof.py` so the wheelhouse manifest is
  hash-verified and the VM proof performs a network-isolated install from the
  local wheelhouse before import/version/model-hash checks.
- Add regression tests for wheelhouse hash mismatch, wheelhouse hash success,
  full proof pass conditions, and release-builder wheelhouse manifest contents.
- Keep live NDI receiver proof, SDI/DeckLink, and live cable-delivery proof
  outside this air-gap lane.

## Explicit Non-Goals

- Do not move, recreate, or retag v1.1.0 or v1.1.1.
- Do not claim real station pilot evidence.
- Do not claim five or more station adoption.
- Do not claim seated governance body operation.
- Do not claim TSA or legal signing authority proof.
- Do not claim production deployment proof.
- Do not start ActivityPub, cable add-on, or Mode B implementation unless a
  separate v1.2 amendment explicitly adds it.
- Do not broaden the v1.2 branch into a general UI redesign.

## Documentation And UX Requirements

- README, changelog, docs index, credential matrix, user manual, API reference,
  and release evidence must be updated with each implemented v1.2 scope item.
- Operator-facing copy must stay actionable and avoid API jargon.
- Every changed operator or public UI surface requires desktop and mobile
  browser evidence, loading/success/empty/error/partial-state review where
  applicable, keyboard/focus checks, axe zero serious or critical violations,
  and browser-console evidence before commit.
- Any remaining operator-copy risk must be listed in a v1.2 known-minor-risks
  evidence file before release approval.

## Verification Gates

- `scripts/verify-release.sh` passes.
- Full pytest, ruff check, ruff format check, mypy, and policy checks pass.
- Operator and public portal build and a11y gates pass.
- veraPDF PDF/A-3B validation remains green.
- Staff-token lifecycle tests pass against in-memory and database-backed paths.
- Store singleton regression tests prove isolated app instances do not share
  mutable router state.
- Broker contract tests pass, or the superseding ADR gate is approved.
- First-run wizard E2E proves recoverable success and failure states for each
  configured target.
- RTX, air-gapped VM, and external provider lanes either pass with durable
  evidence or stop with the correct blocked status and no false proof claim.
- No GitHub-hosted runners are introduced.

## Release Evidence Status

Produced by PR #76 and PR #77:

- `docs/releases/v1.2-internal-hardening-verification.md`
- `docs/releases/spec-alignment-ledger-v1.2.md`
- `docs/releases/evidence/v1.2-first-run-gates.md`
- `docs/releases/evidence/v1.2-store-isolation-proof.md`
- `docs/releases/evidence/v1.2-broker-contract.md`
- `docs/releases/evidence/v1.2-release-artifacts-proof.md`
- `docs/releases/evidence/v1.2-browser-qa.md`
- `docs/releases/v1.2-nats-mtls-foundation.md`
- `docs/installer/nats-mtls-readiness.md`
- `docs/ops/nats-jetstream.md`
- `docs/ops/local-ca-mtls.md`

Updated by the scoped new-box RTX proof lane:

- `docs/releases/evidence/v1.2-rtx-caption-proof.md`

Updated by the scoped new-box proof-consolidation lane:

- `docs/releases/evidence/v1.2-new-box-handoff-validation.md`

Remaining blocked or conditional proof surfaces:

- Staff-token lifecycle release evidence exists through PR #76 tests and docs;
  add a dedicated `v1.2-staff-token-lifecycle-proof.md` only if the v1.2 tag
  gate requires a standalone evidence file.
- RTX caption proof passed on the new-box RTX 5070 Ti with real
  faster-whisper `whisper-large-v3` INT8 CUDA evidence, approved synthetic
  fixture provenance, and WER `14.29%`.
- Isolated air-gapped VM proof has a WSL2 network-isolated app install proof
  from release-candidate artifacts, the offline dependency wheelhouse, and the
  offline model bundle.
- Package-local NDI Studio Monitor source discovery has been recorded for the
  internal lab sender; CivicCast media-package-to-NDI receiver proof, public
  redistributable FFmpeg+NDI, SDI/DeckLink, live headend delivery, and station
  proof remain deferred.
- Package-local Windows installer GUI launch has been recorded; clean-machine
  Windows installation proof remains a separate lane.
- External provider proof remains blocked until credentials and controlled
  targets are available.
- `docs/releases/evidence/v1.2-known-minor-risks.md` is required only if a
  v1.2 tag candidate carries known minor operator-copy risks.

## Kickoff Checklist

1. Create the implementation run from this plan and scope-lock the branch.
2. Re-read ADR 0001, the v1.1 spec ledger, staff-auth docs, installer docs,
   and provider credential matrix before planning code.
3. Write failing tests for one workstream at a time.
4. Keep credential-required proof lanes blocked until Scott supplies the
   required local secrets or hardware.
5. Run release verification before every push.
6. Open the v1.2 PR with the exact evidence state: passed, blocked, or
   deferred, never implied.

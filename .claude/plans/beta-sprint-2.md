# Beta Sprint 2 — Product Decisions → Shippable Beta

Sprint branch: `work/beta-sprint-2` (stacked on `work/audit-sprint-1` / PR #124)
Final deliverable: a high-quality, stable, end-to-end-working **double-click
Windows beta installer**, proven on the remote clean machine.

Scott's decisions (2026-06-10, final — implement, do not re-litigate):

| # | Decision | Choice |
|---|---|---|
| 1 | Live caption tap | **A — egress audio fork** feeding the caption worker (live captions are a launch capability) |
| 2 | Retention auto-purge | **A — stay flag-only**; fix the "auto-purges sooner" UI copy to match |
| 3 | Operator repair surfaces | **A — retry/replay endpoints + operator console buttons** (terminal finalizations, AP dead letters) |
| 4 | Trim | **A — repackage on trim update**; published video honors operator trims |
| 5 | Recording provenance | **A — stamp the recording target on the session at go-on-air**; worker stops guessing |
| 6 | Real providers | **Internet Archive first, YouTube second, real SMTP third**; mocks stay defaults without credentials |
| 7 | CDN | **A — wire packaged recordings to upload through the selected CDN** at finalization |

## Stages (each: per-stage plan if non-trivial, TDD, stage gate, result file, commit)

- **B1 (quick wins):** #2 copy truth + #5 provenance migration/stamping.
- **B2:** #3 repair surfaces — `POST /api/staff/live/sessions/{id}/finalization/retry`
  (409 if running/completed; resets attempts + requeues),
  `POST /api/staff/activitypub/delivery-retries/{id}/replay`
  (dead_letter → pending); live-room post-end finalization panel with retry
  button (also closes the UX-001 "silence after End" gap); AP screen
  dead-letter list + replay.
- **B3:** #4 — packaged-trim bookkeeping on the job (migration), worker
  re-renders when the asset's trim differs from what was packaged
  (manifest-exists idempotency becomes trim-aware), repackaging visible in
  status, trim editor enabled for `recorded` assets.
- **B4:** #7 — after local packaging, upload the HLS tree through
  `app.state`-selected CDN adapter; `manifest_url` = CDN public URL
  (manifest honesty preserved: only set after verified upload); stub-CDN
  end-to-end test; runbook updates.
- **B5:** #6 — real `InternetArchiveClient` (IA S3-like API),
  real `YouTubeClient` (OAuth-credential-gated), real `SmtpMailbox`;
  registered under `real` names in the provider registry; selected only via
  `CIVICCAST_PROVIDER_*` + credentials; contract tests + recorded fixtures
  (no live external calls in CI).
- **B6:** #1 — egress audio fork (rolling WAV segments) → supervised caption
  tap worker (hybrid lifecycle pattern) → cues into the durable review queue
  + live caption surface; settle on the smallest honest live-caption path.
- **B7:** beta packaging (release artifacts / double-click installer), remote
  clean-machine install proof (full install → broadcast → finalize → portal
  flow on a clean Windows machine), final validation, sprint summary, PR.

  Concrete B7 plan (2026-06-10):
  1. Version bump 2.0.10 → **2.1.0** across the release-identity surfaces
     (`check_release_identity` green), CHANGELOG `[2.1.0]` beta section,
     `docs/releases/v2.1.0-verification.md`.
  2. Build artifacts locally with `scripts/build_release_artifacts.py
     --python --wheelhouse --windows-installer` → NSIS setup exe + windows
     tester package + clean-windows proof kit + manifest. This machine has
     no MSVC; the build uses the rustup `stable-x86_64-pc-windows-gnu`
     toolchain (portable, no system installers).
  3. Transfer the proof kit to the remote MSI tester via git only: orphan
     branch with <90 MB chunks + SHA256SUMS (pushing branches is the
     authorized channel; no external services). Branch is deleted after the
     proof to keep the repo lean.
  4. Post `LATEST-TEST-DIRECTIVE.md` on `tester/v2.0.1-clean-windows-proof`
     (nonce + reassembly + the kit's own `VERIFY-AND-LAUNCH.ps1` +
     `proof-directive.md` flow), poll for the MSI result commit.
  5. Final full local gate on the version bump, sprint result file, PR
     `work/beta-sprint-2` → main (Scott merges).

## Rules

Unchanged from sprint 1: Hard Rule 11 plans, failing-test-first, same-commit
CAPABILITIES truth, tiered stage gate with cited full-suite counts
(`scripts/run_stage_gate.ps1`, real Postgres via `CIVICCAST_POSTGRES_TEST_URL`),
result files per stage, signed-off commits `type(scope): … refs #N`.
Safety: no WSL changes, no reboots of THIS machine, no app-state deletion,
no secrets in the repo. The remote clean machine is authorized for the
install proof (B7); local-first for everything else.

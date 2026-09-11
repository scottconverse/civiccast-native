# Consolidated beta repair self-audit - 2026-09-11

Baseline delta audit: engineering PASS after independent root hashes of original
build mirror, staging and safe copies (48608252), and earlier candidate (044a9c8b).
Only the stale baseline index pin and matching historical documentary values
change. UX unchanged; tests use the existing Gate A contract checks; docs carry
provenance and explicitly qualify current GitHub metadata as mutable. QA PASS:
source/build/installer/version pins stay unchanged, and no old bytes are modified.

Post-push delta audit: headend run34621294908 on88935dccb9ece46d3b7e8b7e210fb128257382d3
reported RUF036. The correction only moves None last in one type union.
Engineering/UX/tests/docs/QA PASS for this annotation-only delta; no executable
logic or user copy changes. Local lint/format/type gates validate syntax/types;
prior native behavioral evidence remains applicable. Required new-head CI is
still needed. The initial audit below is retained as its historical checkpoint.

Scope: actual local diff from b2593a50, plus whole branch against main d77b634e.
This records source acceptance for the next PR update. It is not release,
installer or sustained-soak acceptance. No new push has occurred.

- Engineering: PASS. Preparation futures return data; the owner loop alone
  resumes launch/reload after queued commands. Stop cancels pending work and
  process/config identity invalidates stale completion. Reload admission is
  separate from settlement. Old-leg flush precedes NULL without unlinking a
  live producer. Actual native execution confirms the repaired retirement path.
- UX: PASS for changed caption surfaces. FAIL, blocker, timestamp, stale marker
  and next action are visible. The two adjacent screen expectations use the
  same unverified caption label. Underlying caption production remains a soak
  check; the UI does not promise a successful proof.
- Tests: PASS for local source acceptance. Behavioral tests cover blocked
  preparation across three channels, Stop precedence, explicit future programme
  selection, accepted/applied separation and retirement order. The seven
  native checks ran with the bundled runtime, separately from portable skips.
  Counts and limits are in VERIFICATION.md; receipts are archived alongside it.
- Docs: PASS for this checkpoint. README, CHANGELOG, HANDOFF, PROJECT-STATUS and
  verification note distinguish local repair from outstanding candidate gates.
  The PR body is staged locally for the proposed consolidated update. Existing
  F1 CI records remain historical proof anchors, not proof of this new source.
- QA: PASS for this checkpoint. Current main and remote PR head were read live:
  d77b634e and 8653b56f respectively. Old 795cdab5 kit remains blocked. No new
  version/tag/asset or candidate acceptance is claimed. Whole-branch changes are
  the intended F1/F2/F3/F5 repair, related tests, prior CI fixes and evidence.

Artifact-state: source checkpoint passes; post-push SHA and CI propagation is
pending the actual authorized push. There are no new database models/migrations
or finding-ledger Closed claims. Existing historical anchors are intentionally
retained. Current commit identity is recorded in the external review receipt,
avoiding a tracked file trying to self-cite its own hash.

Known limits stay bounded: candidate schedule publication, actual captions
ON/OFF, reload-abort visibility, memory growth and dropped-frame observations.
These do not authorize speculative hardening or another testing programme.

# F-1 local implementation verification

Status: independent local implementation review accepted; release acceptance open.
Recorded 2026-09-10, Mountain time.

Post-push correction: PR #219's first CI cycle is red. The local evidence below
remains scoped as recorded, but does not establish branch-wide acceptance.
The pre-push audit missed stale claims-registry bindings. See `CI-RESULT.md`
for that omission, the two additional CI issues, exact runs and next actions.
The later local CI repairs at `59ef1be6498e5a4eced081d7c412df1176fefdb0` are
recorded in `../f1-ci-repair-2026-09-10/VERIFICATION.md`. They have not been
pushed; the earlier proof and failed remote CI retain their separate identities.

## Source and authority

- Base main: `d77b634e3685de8fb077956b8099fc92c3927243`.
- Implementation/proof anchor: `7a468cd2e9018775926d384ac1b25ebe07ebd18d`.
  A following documentation-only checkpoint records this anchor. This avoids
  making a tracked file self-cite a commit hash that changes when the file does.
- Branch: `fix/f1-reload-readiness-20260910`.
- Scott explicitly authorized GO after the read-only takeover and repair proposal.
- No push/PR, merge, tag, publication, station-service start, Gate A or sandbox soak.
- Existing kit: `795cdab5065e3b1b1d9df69c6fc06658f481c8d4`, unchanged, blocked.
- Current public release remains `v1.0.0-beta.5`; source version remains beta.6.

## Contract and blast radius

The engine may retire the old A/V leg only after all replacement streams have
produced their first buffers for the same reload transaction. Held file legs
remain held through retirement; immediate and clock-timed legs are observed
without blocking or rebasing them. Delayed readiness and timeout callbacks carry
the transaction ID, and repeated hold callbacks cannot substitute for another
stream. Deferred commit normally waits for the outgoing boundary; the existing
defer watchdog may force that boundary after its timeout, but still cannot bypass
the current transaction's all-stream readiness requirement.

The daemon treats a clean exit in ON_AIR or TRANSITIONING as a fault. Existing
crash pacing and escalation apply. Queued Stop/Drain and an active drain suppress
relaunch for either exit code, including an already-pending restart. The finite
FALLBACK_SLATE EOS policy remains separate. Exit logs and recovery errors describe
what happened; successful resumed air may clear the transient last_error.

Blast radius: immediate/deferred program reloads, live clocked replacement,
worker restart, Stop/Drain races, and prepared-plan/PID cleanup. A mistake can
leave a stream waiting, switch prematurely, or restart against operator intent.
The deterministic tests, real-worker tests and independent review target those
paths; installer and sustained-operation evidence remain separate.

## Executed evidence

- Lead required egress/live/policy gate: **2106 passed, 72 skipped, 263.70 s**,
  exit code 0, saved in `egress-live-results.txt` and `egress-live-exit.txt`.
  Command: `uv run --frozen --no-sync pytest tests/egress tests/live tests/policy/test_reload_preroll_log_contract.py -p no:randomly -q -o faulthandler_timeout=120`.
  `UV_PROJECT_ENVIRONMENT=.venv312`, Python 3.12.10. This broad run intentionally
  had no native-runtime environment configured; the skips include native media
  checks, unavailable Docker-backed real-Postgres tests, and platform-specific
  tests. The separate native runs below supply targeted real-media coverage;
  they do not erase the broad run's skips or prove real-Postgres integration.

- Lead red baseline: `engine-red.txt`, four failures against unchanged engine
  source: no-preroll commit, stale held/non-held readiness, duplicate hold.
  Command: `uv run --frozen --no-sync pytest tests/egress/test_gst_engine_reload_commit_ordering.py -k f1 -p no:randomly -q`.
  The committed text transcript has trailing whitespace removed; its original
  captured output is retained in the sibling scratch directory and proof anchor.
- Luna reported daemon red baseline: 3 failed, 143 deselected, using
  `uv run --frozen pytest tests/egress/test_daemon.py -q -k "cleanly_on_air or queued_operator_stop_or_drain"`.
  This result was worker-reported; the lead independently executes integration checks.
- Native runtime result: `native-results.txt`: **4 passed, 22 deselected, 89.20 s**.
  Command: `uv run --frozen --no-sync pytest tests/egress/test_gst_engine_wsl.py -k "reload_never_buffers_recovers or superseding_a_held_deferred_reload or repeated_deferred_rollovers_retire_complete" -p no:randomly -q --basetemp=work/f1-native-runtime`.
  Environment: `UV_PROJECT_ENVIRONMENT=.venv312`, Python 3.12.10;
  `CIVICCAST_GSTREAMER_RUNTIME_ROOT=C:\CivicCastTester\candidates\795cdab5065e3b1b1d9df69c6fc06658f481c8d4\candidate\trust-bridge-install\runtime`.
  The imported engine source was verified to be this worktree. Only runtime
  dependencies came from the old candidate; the kit was not modified or tested
  as a fixed release candidate.
- Six saved `worker.log` files: **21 commits**, every commit passed the new
  transaction-specific preroll grader. The three production-shaped captioned
  workers each completed six reloads, each with 77 elements; held supersession
  also committed with 77. The two simpler dead-port recovery graphs committed
  with 15 elements. Healthy count is topology-specific, never hardcoded to 146.
- Native tests checked worker survival, teardown, TS continuity and A/V output;
  the three-worker test also checked caption-tap output. This is a short local
  runtime check, not the required two-hour soak or physical headend acceptance.
- Additional native coverage for the reviewed unheld paths:
  `native-unheld-results.txt`: **3 passed, 23 deselected, 15.82 s**.
  Same Python/runtime environment, command:
  `uv run --frozen --no-sync pytest tests/egress/test_gst_engine_wsl.py -k "content_reload_continuity_av or content_reload_to_live_udp_ingest_continuity or deferred_rollover_switches_at_the_boundary_without_eos" -p no:randomly -q --basetemp=work/f1-native-unheld`.
  Immediate A/V, live UDP replacement and deferred-boundary output all passed.
  Each of their three saved worker logs contains one correctly graded commit.
  Across both native runs: **7 tests passed, 24 commits graded across 9 logs**.
- Exact checked code/test hashes are in `SOURCE-SHA256SUMS.txt`. Generated media
  and intermediate outputs were moved after testing to the sibling
  `work/f1-local-scratch` directory; committed text evidence is retained here.

## Log grading

`uv run --frozen python scripts/ops/check_reload_preroll.py <worker.log> --expected-elements <healthy-count>`

The grader rejects missing/stale/reused preroll proof, missing completed holds
for held legs, unexpected element counts, and logs with no commits. Live and
immediate unheld legs require the all-stream first-buffer proof, not a fabricated
hold message. Worker exits reset transaction IDs. It grades F-1 commits only:
unexpected exits, schedule accuracy, stalls and captions require separate checks.
Policy tests reject the historical bare undersized commit signature.

## Team and review

OpenAI-only native delegation: lead owns engine and integration; Luna
`gpt-5.6-luna` owns the initial daemon implementation; Terra `gpt-5.6-terra`
independently reviews. Luna's original submission is preserved outside the repo
in `work/f1-daemon-submission.patch`. Lead corrections add final exit logging,
clean-exit last_error and terminal-intent handling for nonzero exits.
Luna was not accepted on the first pass; focused review corrections were needed.
Usage/cost and precise worker-vs-coordination elapsed time are unknown.

Independent review identified missing nonblocking audio readiness and nonzero
exit/queued-stop handling. Both were corrected and accepted. Terra personally
ran the focused engine/daemon/policy suite under Python 3.12.10: **208 passed in
10.10 s**. Its broad-suite tool stream detached and lost the final result; that
run is not claimed as a pass. The lead's durable broad run is a separate check.
Terra's final implementation and documentation verdict was **ACCEPTED**, after
the hold-vs-unheld acceptance wording was corrected.

Lead repository-wide locked checks passed: `uv run --frozen --no-sync mypy civiccast`
(675 source files), `uv run --frozen --no-sync ruff check .`, and
`uv run --frozen --no-sync ruff format --check .` (1541 files).

## Remaining gates and evidence limitations

F-1 is not release-closed. Local egress/live checks and independent review passed,
with the explicit skips and scope above. A new exact-source candidate still needs
the section 5 two-hour sandbox proof, short graded sandbox runs, full Gate A and
real-hardware tester soaks with captions ON/OFF under the owner's gate order.
No candidate build, soak, Gate A or release has been run for this change.
F-2 remains unstarted; other release findings still require disposition.

The callback race is reproduced deterministically. Its contribution to each
archived beta.5 death remains an inference, since those logs lack transaction
identity. The historical clean-machine verification note also overcounts
`elements=33`: direct archive counting found two such commits and four clean
exits, not four commits. The original archive and note are preserved unchanged.

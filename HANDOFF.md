# Current handoff: station operations (2026-10-13)

Current branch: `codex/station-operations-1-0`, based on
`431585942c9ced93e730b1e6b506c707a6adecb8` (corrected Beta 15).
Owner authorizes push and merge after green CI; no tag or production cutover.

The four selected source goals are implemented: station backup/restore,
network access, staff/session administration, and restricted service identity.
See [current implementation and evidence](docs/ops/station-operations-goal.md).
Actual restricted SCM migration, healthy PostgreSQL/API startup and encrypted
backup passed in an isolated guest; the guest is closed and the host is unchanged.
Pre-push type declarations and manual text were reconciled. PR #245 is open:
https://github.com/scottconverse/civiccast-native/pull/245
Its first CI run found operator form lint, a missing login version label, and
clean-machine service-SID ACL failures. Its review also identified backup-state,
retry and destination-overlap defects; a Linux network test fixture used a
Windows-only path. Focused corrections pass; merge awaits corrected-head CI.
See `.agent-runs/native-windows/station-operations-1-0/evidence/pr245-ci-corrections.md`.
Published Beta 15 remains unchanged. Current PR/CI
identity is recorded on the pull request.

## Historical Beta 14 publication handoff

The following is retained history, not the current station or work status.

Beta 14 is published: https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.14
Published 2026-10-12 10:25:01 UTC. All 26 assets passed name/size and SHA-256
digest verification. Six actual public downloads matched SHA-256; the
downloaded installer has a Valid Scott Converse Authenticode signature.

Signed source: `44525c14265d21ae461c2435d4d5a9a6acd58af3`; build `38217950172`.
Release target / merged PR 240: `ed2f5069004abb6c3c6b4375ac82a07fcabe9a7b`.
Installer SHA: `e22d1cb9ae064841c45bed64a37e8ce9bd1e5176e0ff80945edccc362447082f`.
Bookkeeping branch: `codex/beta14-publication-record`.

All 28 requested product goals have focused evidence in
[task completion](docs/ops/beta14-task-completion.md). Exact package passed
fresh offline Sandbox installation, five three-channel observations and
installed Help inspection. Sandbox closed. Same installer ran once on host,
exited 0, and passed component verification and two three-channel observations.
Host remains running: Whistle primary, H.264/AAC, advancing HLS and captions.
No extended Beta 14 soak requested or claimed. Original observer failures are
preserved; corrections did not rerun setup or rebuild the signed application.
Final receipt: `outputs/beta14-work/host-runtime-final/consumer-evidence-receipt.json`.
Raw pre-install snapshot was not retained; account/schedule rows not compared.
Historical R9 TSDuck cause and one unavailable recording segment cause remain
unknown; focused current fixes are evidenced separately.

D: kit: `D:\CivicCast-Beta14-Kit-44525c14`, 19 members, 26,916,076,058 bytes.
Assembly and USB receipts alongside; both installation prompts name Beta 14.
Assembly SHA: `2338fddc987b4cb73bfbea4947901899a11ef0338231b24772f2a756604f77a4`.
Redundant closed Sandbox expansion and twelve uploaded archive parts removed;
evidence/component manifest and working C:/D: kits retained. C: free 403.9 GB.

Goal ACTIVE until this final record lands and live Pages verification finishes.
Only owner may pause. Publisher session 8097 finished; do not restart/build.
Next: land reconciliation, verify live landing page, then mark goal complete.
72-hour/three-channel/99.78% result remains Beta 11 history.
Live release-truth alarm has 17 absent historical releases, none Beta 14.
Preserve unrelated `ops/beta10-oversight/evidence/`.

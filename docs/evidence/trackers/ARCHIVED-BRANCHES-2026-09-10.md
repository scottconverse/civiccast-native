# Disk-only branches archived to GitHub, 2026-09-10

On 2026-09-10 these 20 branches existed **only on the owner's machine** — they had commits not
on `main` and no branch on `origin`. They were pushed as `backup/2026-09-10/<original-name>`
so nothing is lost if that machine is.

They are **unreviewed and unmerged**. Treat this as an archive, not a work queue. Several are
almost certainly dead ends from earlier sessions. Check each against `main` before reviving one.

| commits ahead of main | archived as |
|---|---|
| 14 | `backup/2026-09-10/docs/release-beta5-work` |
| 2 | `backup/2026-09-10/feat/publish-staged-kit` |
| 3 | `backup/2026-09-10/feat/s7-watch-folder-daemon` |
| 17 | `backup/2026-09-10/feat/sandbox-soak-lane-followup` |
| 5 | `backup/2026-09-10/fix/beta5-claims-rebind-20260908` |
| 1 | `backup/2026-09-10/fix/ffmpeg-pack-lock-repin-33094460301` |
| 1 | `backup/2026-09-10/fix/gate-a-busy-guard-orphan` |
| 2 | `backup/2026-09-10/fix/gate-a-contract-repo-root` |
| 2 | `backup/2026-09-10/fix/gate-a-teardown-drain` |
| 6 | `backup/2026-09-10/fix/gst-worker-runtime-death-wt` |
| 1 | `backup/2026-09-10/fix/gui-acquisition-sequential-blocking` |
| 1 | `backup/2026-09-10/fix/lifecycle-transcode-defaults` |
| 3 | `backup/2026-09-10/fix/operator-card-and-offline-copy` |
| 2 | `backup/2026-09-10/fix/provision-port-reservation` |
| 2 | `backup/2026-09-10/fix/setup-nonce-handoff` |
| 2 | `backup/2026-09-10/fix/setup-recovery-code-feedback` |
| 3 | `backup/2026-09-10/pr154` |
| 7 | `backup/2026-09-10/pr199-round2` |
| 58 | `backup/2026-09-10/test/beta5-44a02308-directives` |
| 58 | `backup/2026-09-10/test/beta5-e23-support-20260908` |

Fetch one with:

```bash
git fetch origin 'refs/heads/backup/2026-09-10/*:refs/remotes/origin/backup/2026-09-10/*'
```

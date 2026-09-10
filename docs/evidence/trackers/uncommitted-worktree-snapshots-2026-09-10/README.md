# Uncommitted worktree edits, snapshotted 2026-09-10

Three worktrees on the owner's machine had **uncommitted** edits at 11:20 AM on 2026-09-10. They
predate the 2026-09-09/10 fix work and belong to earlier sessions. They are captured here as plain
`git diff HEAD` patches so the content survives the loss of that machine.

**Nothing in those worktrees was modified to produce these.** No commit, no stash, no checkout —
the working trees were read, not touched. That was deliberate: committing another session's
half-finished edits, or checking out around them, risks destroying exactly the work this is meant
to preserve.

| patch | worktree | branch | files |
|---|---|---|---|
| `cc-summary-fix.patch` | `C:\Users\scott\Desktop\Code\cc-summary-fix` | `fix/ai-summary-cpu-generation` | 25 |
| `cc-testfix.patch` | `C:\Users\scott\Desktop\Code\cc-testfix` | `mainprobe` | 2 (plus an untracked `pnpm-lock.yaml`, not captured) |
| `fix-upload-asset-ffprobe-error.patch` | `civiccast-native\.claude\worktrees\fix-upload-asset-ffprobe-error` | `fix/upload-asset-ffprobe-error` | 2 |

Apply one with:

```bash
git apply docs/evidence/trackers/uncommitted-worktree-snapshots-2026-09-10/<name>.patch
```

against the branch named above. Check what it is before reviving it — these may well be abandoned.

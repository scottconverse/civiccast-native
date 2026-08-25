# ADR 0024 — Watch-folder daemon: processed-file disposition, degraded state, delete-safety

**Status:** Accepted
**Date:** 2026-08-25
**Deciders:** Coder (Claude, active coder seat) — implemented as the deferred half of PR #19,
  per the owner's task instruction naming the design decisions below explicitly
**Related rung:** S7 media lifecycle & readiness (build step 12, `feat/s7-watch-folder-daemon`)
**Related spec section:** `docs/spec/3.0/sections/S7-media-lifecycle-and-readiness.md` §6
  ("Watch-folder monitor (background daemon)") and §10.5 (D13, SMB resilience)
**Supersedes:** none
**Superseded by:** none

---

## Context

PR #19 built S7's `WatchFolderConfig` data model, CRUD API, and settings UI, and explicitly
deferred the poll daemon itself — nothing on disk listed `monitor_path`, checked write-completion,
or called into ingest. The S7 spec's §6 describes the daemon's shape (5s poll default, settle-window
write-completion detection, "copies to upload_dir asynchronously ... queues ingest") but does not
resolve several decisions the daemon build needs to make concrete:

1. What happens to the source file in `monitor_path` after a successful ingest — is it deleted,
   moved, or left in place?
2. What happens when `monitor_path` becomes unreachable (USB unplugged, NAS/SMB share down) —
   is that visible to the operator, or does the daemon just silently stop finding files?
3. How many folders can the daemon work on at once, and how much work within one folder happens
   at once?
4. What "delete-safety posture" applies to watch-folder source files specifically? CLAUDE.md's
   own "Archival behavior (§4.6)" pointer, on inspection, is about the three-tier archive
   verification gate (portal + IA + NAS), not watch-folder source-file handling — there is no
   pre-existing §4.6 text to follow here.

Per CLAUDE.md's "Open decisions" policy, these are not picked silently; this ADR is that record.
The task that authorized this build stated the intended shape for (1), (2), and (4) directly
("moves-or-marks processed files per config", "unreachable paths as a visible degraded state",
"never delete source") — this ADR formalizes that direction against the actual data model and
worker implementation, and resolves (3), which was left open.

## Decision

### 1. Processed-file disposition: two operator-selectable modes, neither ever deletes the source

`WatchFolderConfig.processed_file_mode` (new column, migration `0080_watch_folder_daemon`) is one
of:

- **`leave_with_ledger`** (default). The file stays exactly where it was in `monitor_path`. The
  new `WatchFolderFileState` table (the "ledger") is the durable record that this path was
  already ingested, keyed by `(config_id, file_path)` — so the daemon's next poll recognizes it
  as already-handled and does not re-ingest it, without needing to move or mark the file itself.
- **`move_to_subfolder`**. After a successful ingest, the daemon moves the file to
  `processed_subfolder_name` (new column, default `"processed"`) under `monitor_path`, creating
  it if absent. Purely for operator tidiness (a folder that visibly empties out as it's consumed);
  functionally the ledger already tracks ingest state either way. The daemon never recurses into
  this subfolder when listing candidates, both because §6 describes flat monitor_path listing and
  because recursing would immediately rediscover a just-moved file as "new."

**Neither mode ever deletes the source file.** A move failure (permission denied, a still-open
file handle) is logged and the file is left in place — the ledger already marked it ingested, so
nothing is re-ingested or lost; the file just doesn't get tidied away this time.

### 2. Unreachable path: a visible, per-config degraded state — never silent

`WatchFolderConfig` gains `health_status` (`ok` | `degraded` | `unknown`), `degraded_reason`,
`degraded_since`, `last_poll_at`, and `last_ingest_at`. When a poll cannot list `monitor_path` at
all (missing mount, permission error, unreachable SMB share — anything surfacing as `OSError`),
the config flips to `degraded` with the exception text as `degraded_reason` and `degraded_since`
set to the first poll that failed. The moment a subsequent poll succeeds, the config flips back to
`ok` and both fields clear. `unknown` is the state before the daemon's first poll of a config.

This state is operator-visible: the settings screen (`MediaLifecycleSettingsScreen.tsx`) renders a
status column per watch folder showing health, last-poll time, last-ingest time, and — when
degraded — the reason, with `role="alert"` so it's announced by assistive tech, not just colored
text. **A NAS share going down must be something an operator discovers on the settings screen, not
something they discover three weeks later when a recording never showed up.**

### 3. Concurrency: per-folder serialization, global concurrency cap, bounded per-file

Not addressed by the spec text. Resolved as:

- **Per-folder serialization.** All files within one `WatchFolderConfig`'s pass are scanned and
  (if due) ingested one at a time, in listing order, inside a single call to
  `WatchFolderWorker._scan_one_folder`. Two files in the same folder are never ingested
  concurrently with each other.
- **Global concurrency cap across folders.** Different configs' folders MAY be scanned
  concurrently, bounded by `WatchFolderWorkerSettings.max_concurrent_folders` (default 4,
  `CIVICCAST_WATCH_FOLDER_MAX_CONCURRENT_FOLDERS`), via a `ThreadPoolExecutor`. This mirrors
  `MediaLifecycleWorkerSettings.max_transcode_dispatch_per_pass`'s "batch cap per pass" idiom —
  bound the concurrent work, not the total work — just applied to folders instead of transcode
  jobs.
- **Bounded per-file.** `max_files_ingested_per_pass_per_folder` (default 25) caps how many
  settle-confirmed files one config's pass will hand to ingest — success or failure both count —
  so one folder full of files (or one folder full of permanently-broken files) can't monopolize a
  pass indefinitely. Leftovers are picked up on the next due poll.

### 4. Delete-safety posture: never delete the watch-folder source file

There is no pre-existing "§4.6 delete-safety" text for watch folders specifically — CLAUDE.md's
own §4.6 citation is about the archive-verification gate. The posture this build establishes,
consistent with the broader codebase's existing "never delete, only flag/copy" pattern (the
retention worker never auto-deletes expired assets; the media-integrity worker only flags missing
files for operator action), is: **the watch-folder daemon never deletes a source file, in any mode,
for any reason.** The daemon only ever *copies* a source file into the managed upload tree
(`shutil.copy2`, never a move, for the actual ingest step) and, only in `move_to_subfolder` mode,
relocates the original within the operator's own watch folder — never off of it, never to a
temp/trash location, never removed.

## Consequences

- A station running `move_to_subfolder` mode accumulates files in the processed subfolder
  indefinitely; disk-space management for that subfolder is an operator/ops concern (same as the
  rest of this codebase's "never auto-delete" posture for retention-expired assets), not something
  this daemon does automatically.
- `leave_with_ledger` mode means `monitor_path` itself never empties out on its own; an operator
  who wants a clean drop folder should use `move_to_subfolder` instead.
- The `WatchFolderFileState` ledger is now the durable source of truth for "was this file already
  ingested," "is it currently mid-settle-window," and "which asset did it become" — losing that
  table (a manual `DELETE FROM watch_folder_file_state` or a downgrade past migration `0080`)
  makes every already-ingested file look new again on the next poll, which under `leave_with_ledger`
  mode would attempt to re-ingest every historical file in the watch folder. This is a real
  operational footgun worth calling out to operators in station documentation, not something the
  daemon code can protect against — it has no way to distinguish "genuinely new file" from
  "ledger row lost."
- Reprocess-on-change (a file at an already-ingested path later changes) applies the SAME
  replace-source path an operator uses (`MediaLifecycleStore.apply_replace_source`, now accepting
  a `source_kind` parameter so watch-folder-originated replaces are provenance-tagged
  `"watch_folder"` rather than the default `"http_upload"`) against the SAME `asset_id` the ledger
  already associated with that path — never creating a duplicate asset for the same watch-folder
  location.

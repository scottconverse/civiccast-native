# CivicCast project status

> **2026-10-02 current: `v1.0.0-beta.10` is the owner-held unpublished
> candidate.** This is the one current status page. `v1.0.0-beta.7` is still
> the published release (2026-09-15); `v1.0.0-beta.8` and `v1.0.0-beta.9` were
> never published and their work is folded into beta.10. Source is branch
> `release/beta10`. When published, beta.10 will be a GitHub pre-release (a
> beta candidate), not a production release.
>
> Push, merge, tag and release are owner actions: nothing in this file, and no
> earlier dated authorization in the history files, publishes beta.10. The
> coordinator's working handoff, with the current decisions and rules, is
> [`ops/beta10-oversight/HANDOFF-2026-10-01.md`](ops/beta10-oversight/HANDOFF-2026-10-01.md).
>
> Evidence that exists: an eight-hour watched run on a three-channel lab
> station (2026-10-01 16:30 to 2026-10-02 00:30): one service process for the
> whole run, no slate or filler after startup, 40 of 41 verify checks OK (one
> raw FAIL adjudicated as a sampling blip), loudness 16 of 16 windows, 50
> program changes scored with no holes. See
> [`docs/releases/v1.0.0-beta.10-verification.md`](docs/releases/v1.0.0-beta.10-verification.md)
> and `ops/beta10-oversight/verdicts/`.
>
> Known limits: live-caption audio can be dropped under heavy load (13
> catch-up discard events in the run, about 160 seconds of audio on a quiet
> machine; the fix is the next work item); two aborted program-change first
> attempts that recovered in about 3 seconds; one single-frame video drop.
>
> Not done: no beta.10 installer has been built or signed, Gate A has not been
> run for it, it is not published, and no human field tester has signed off.
> Required next: CI build, Gate A on the exact candidate, publication through
> the release script, then the caption-priority fix and a whole-repo audit.

## Where the history went

The earlier dated status entries and handoff notes (beta.5 through beta.8
preparation, kit-server commands, local paths, the old task list and standing
rules from that period) are kept for the record, and are not current guidance:

- [`docs/history/PROJECT-STATUS-2026-09.md`](docs/history/PROJECT-STATUS-2026-09.md)
- [`docs/history/HANDOFF-2026-09.md`](docs/history/HANDOFF-2026-09.md)

Release state of record: [`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml).
Deferred work: [`next-cleanup.md`](next-cleanup.md).

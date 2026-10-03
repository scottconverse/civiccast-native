# CivicCast project status

> **2026-10-02 current: `v1.0.0-beta.10` is the current published release,
> published 2026-10-02** as a GitHub pre-release (a beta candidate), not a
> production release. This is the one current status page.
> [Release page](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.10);
> the tag points at commit `b652084707367d45913807ed2a525f15a9a1e4a4` (build
> run 37039304786). `v1.0.0-beta.7` (published 2026-09-15) is superseded;
> `v1.0.0-beta.8` and `v1.0.0-beta.9` were never published and their work is
> inside beta.10. Source is branch `release/beta10`.
>
> Push, merge, tag and release are owner actions; the owner (Scott) authorized
> them for beta.10 on 2026-10-02, and nothing in this file publishes anything.
> The coordinator's working handoff, with the current decisions and rules, is
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
> Release assets: a signed `setup.exe` (242,367,640 bytes), five runtime packs,
> `SHA256SUMS.txt` and `setup.exe.sidecar.json`. The roughly 21 GB AI-model
> `station\` bundle is not a release asset; the installer finds or downloads
> the large AI components during installation.
>
> Gate A (automated station acceptance) for beta.10: the clean-install lane
> passed, 10 of 10 criteria, run locally in Windows Sandbox on 2026-10-02
> against exactly this build. The cross-version (upgrade) lane and the
> download-only lane were not run; the owner waived them for this publication,
> so upgrade over beta.7 is not proven for beta.10. The human/station
> acceptance pass has not been done; beta.10 is still a beta candidate and no
> human field tester has signed off.
> Required next: the caption-priority fix and a whole-repo audit.

## Where the history went

The earlier dated status entries and handoff notes (beta.5 through beta.8
preparation, kit-server commands, local paths, the old task list and standing
rules from that period) are kept for the record, and are not current guidance:

- [`docs/history/PROJECT-STATUS-2026-09.md`](docs/history/PROJECT-STATUS-2026-09.md)
- [`docs/history/HANDOFF-2026-09.md`](docs/history/HANDOFF-2026-09.md)

Release state of record: [`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml).
Deferred work: [`next-cleanup.md`](next-cleanup.md).

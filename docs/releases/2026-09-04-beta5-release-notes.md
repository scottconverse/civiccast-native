# v1.0.0-beta.5 -- draft, not yet published

**Status: DRAFT.** `v1.0.0-beta.5` has not been published. This document is
prepared ahead of tonight's publish, following the
`2026-09-03-beta4-release-notes.md` pattern, so the publish itself is a
fill-in-the-placeholders-and-run operation rather than a from-scratch write.
`docs/releases/release-truth.yaml` still carries `v1.0.0-beta.4` as
`current` and `v1.0.0-beta.5` as `staging` -- neither this document nor any
other surface in this PR flips that.

**Publisher (once run):** the coordinating agent, per the owner's
2026-09-02 delegation ("every green build gets tagged and published" --
see `scripts/release/publish_beta_candidate.py`'s module docstring).
**Will affect:** `docs/releases/release-truth.yaml`; every beta.4 station's
upgrade path; README / INSTALL-WINDOWS.md / `docs/index.html` /
`docs/tester/*` "current release" wording -- see "Surfaces to flip at
publish time" below for the exact list, prepared but not applied here.

## What will happen

`v1.0.0-beta.5` will publish as a GitHub prerelease on
[`scottconverse/civiccast-native`](https://github.com/scottconverse/civiccast-native/releases),
targeting source SHA `91caebccc6a6decef476fea5cd785a9ff19abfe6`. Like beta.3/beta.4, it will be
downloadable: `setup.exe` and the runtime `.ccpack` packs as release assets,
verified by a published `SHA256SUMS.txt` and a `setup.exe.sidecar.json`
sidecar.

**For Sergio/LPM (already on `v1.0.0-beta.4`): this will be a download-only
upgrade**, exactly as beta.3 -> beta.4 was. Run `setup.exe` (with the
runtime packs) over the existing install -- no `station\` folder, no
re-downloading the ~21 GB AI-model bundle. Recordings, settings, database,
and AI models already on the machine are kept.

Will be published via `python scripts/release/publish_beta_candidate.py
--kit-dir <kit> --source-sha 91caebccc6a6decef476fea5cd785a9ff19abfe6 --build-run-id 33971258093
--gate-a-run-id 33972726431 --tag v1.0.0-beta.5 --truth-status current`,
whose fail-closed checks must all pass before any GitHub state is touched:
version identity agreeing across `setup.exe` ProductVersion,
`civiccast._native_version.__version__`, and the tag (already
`1.0.0-beta.5` as of PR #164's version bump); Authenticode signature status
`Valid`; Gate A run `33972726431` showing `PASS` on all three required
lanes.

## Headline: the real cause of the playout-worker restarts, found on real station hardware (#172, merged)

Two earlier rounds of this document attributed the beta.4 soak's
relaunch-count `FAIL` first to plan-boundary worker exits (retracted, see
`docs/releases/2026-09-03-beta4-release-notes.md` and
`docs/releases/v1.0.0-beta.4-verification.md`), then to a mix of a
sandbox-only output stall and a `UnicodeEncodeError` in the automation
pass. **That second explanation was also incomplete.** A soak on the
tester's own real hardware (`DESKTOP-VBMA6O5`, 2026-09-05) reproduced the
same restarts with no sandbox involved, which ruled out "sandbox-specific
stall" as the driver and pointed at the one thing common to every
environment: the live caption tap.

**Root cause: the caption tap transcribes every `ON_AIR` channel's audio
in-process on CPU, and with three channels running it overloads.**
`civiccast/captions/tap_worker.py` runs speech-to-text for every on-air
channel in the same process, on the CPU, with no backoff. On the tester's
three-channel real-hardware soak (`DESKTOP-VBMA6O5`, kit `e502074`,
mission `soak8-e1acfe6`, planned 2 hours, actually run 2.5 hours,
2026-09-05T09:06:14Z -- 11:36:14Z), the control-plane log recorded this
line roughly every 30 seconds, on all three channels, throughout the run:

```
CRITICAL civiccast.captions.tap_worker: Caption tap overload for channel <id>: N settled segments exceeds the maximum 2; active captions were cleared and stale audio was moved to overload evidence
```

It never backs off. Sustained, it drives the control-plane process to
roughly 2.8 CPU cores (1.4-1.9 GB resident) throughout the run, which
starves the GStreamer playout workers of CPU time. Each starved worker
trips its own stall watchdog (`CTRL stall: no output for 10s`) and exits,
and the daemon relaunches it -- on the tester's real-hardware soak, public
relaunched twice, education once, government three times (6 relaunches
total); at the final probe, public and government were in
`FALLBACK_SLATE` after a relaunch and education was still `ON_AIR`; the
sandbox soaks saw 5-10 relaunches per channel in 2 hours. TSDuck (`tsp`)
packet-level checks passed on every 30-minute probe cycle from 09:36Z
onward (the two earlier probe failures, at 08:28Z and 09:06Z, predate
`ON_AIR` -- the channels had not yet been created -- and are excluded),
and the upgrade path passes independently on real hardware -- the
restarts are a CPU-contention symptom of the caption tap, not an engine
or upgrade defect.

**Fixed in this candidate by #172 (merged):** overload backoff/pause in
the caption tap so it stops driving unbounded CPU load once it is behind,
a bounded ASR workload, and higher process priority for the playout
workers so they are not the first thing starved when the box is under
load.

**Contributing, also fixed: a state-write crash on non-cp1252 characters
(PR #169, merged).** Independently of the CPU-contention root cause, every
restart's channel-automation pass on the earlier soaks also raised
`UnicodeEncodeError: 'charmap' codec can't encode character '\ufffd' in
position 118` -- the worker's stall message folds a `\ufffd` replacement
character into `last_error`, and writing that value out under the
process's `cp1252` client encoding failed, which aborted that channel's
automation pass until the next tick. Seen on the tester and on both
sandbox soaks. #169 fixed this by folding all persisted free text for
non-cp1252 clusters, and creates new clusters as UTF-8 going forward.

**Planner defects found on the way (PR #170, open, not yet in this
candidate):** while instrumenting the rollover and health-poll paths to
chase this bug, three more defects turned up in the schedule planner --
schedule slot duration was ignored entirely (a 30-second slot of long
media could air for hours), plans were sized by item count (8 items)
rather than duration so a run of short items produced 4-minute plans, and
the health poll re-read a worker's entire growing stderr log every 2
seconds instead of tailing it. None of these were the restart's root
cause; #170 is tracked separately.

**The seamless plan rollover (PR #162, merged) is a real improvement for
genuine plan-boundary transitions, but it did not fire in any soak (0
rollovers in the tester's 2-hour log) and did not cause, and does not fix,
the restarts.** Evidence:
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-4b30c99-20260904`
(beta.4 sandbox), `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\soak-120-e502074-20260905`
(beta.5 sandbox retest), and the tester's real-hardware soak on
`DESKTOP-VBMA6O5` (2026-09-05).

**Known limit, carried forward in beta.5:** captions are best-effort. When
the box cannot keep up, they pause and playout wins -- a three-channel,
CPU-only station will pause captions under load rather than risk playout.

**What beta.5 is, in full:** the caption-tap overload fix (#172, merged,
above) is the headline; also in this candidate are the state-write encoding
fix (#169, merged), the four Gate A harness fixes below (#158/#160/#161/#163),
and the release-prep identity bump (#164). The seamless plan rollover (#162)
shipped in an earlier round of this candidate and is described below for
completeness; the planner defects (#170) are tracked separately and are not
part of this candidate.

## Also in this candidate: seamless source-plan rollover for genuine plan-boundary transitions (#162)

Independent of the diagnosis above, the playout worker genuinely does
exit cleanly at the end of every source plan
(`civiccast/egress/source_plan.py`'s `max_segments=8` bounds how many
segments one worker process plans before it exits by design), which can
happen under continuous back-to-back premieres, and each exit-and-restart
is a short on-air blip. `v1.0.0-beta.5` fixes that at the root:

- New `ChannelAutomationService._check_plan_rollover`
  (`civiccast/egress/automation.py`) runs every automation tick and tracks
  the projected wall-clock end of the plan a channel is actively airing.
- Within 30 seconds of that projected end, it re-fetches the schedule
  through the same `source_plan_provider` already in use. Because
  `build_source_plan_from_schedule` always resumes the currently-airing
  item and windows forward from "now," a later fetch naturally reaches
  further into the schedule once more content has been published -- that
  recompute *is* the rollover.
- If the fresh plan extends further than the one already loaded, the
  channel enqueues the same `"reload"` command the existing slate-to-program
  transition already uses. The engine switches both video and audio to the
  new leg at the outgoing clip's end: EOS is dropped on the outgoing
  selector pads, running-time is rebased, and the new leg is held prerolled
  so there is nothing left to wait on at the switch point. The channel's
  `state` stays `ON_AIR` the whole time; only a `TRANSITIONING` proof event
  is recorded, matching the slate-to-program transition's own behavior.
- If nothing further is published yet, this is a deliberate no-op and the
  plan is left to reach its natural end -- closing that smaller residual
  gap is a separate follow-on, not part of this fix.
- The immediate-switch path (used when a channel is not mid-plan, e.g. the
  slate-to-program transition itself) is unchanged.

**Proven on HALO with the bundled GStreamer:** the rollover engine test
suite passed 5/5, TSDuck measured 0 discontinuities and 0 PCR/PTS leaps
across the monitored rollovers. **Known residual:** if the next leg is not
ready before the outgoing clip ends, the output freezes until it is ready
or the existing 10-second stall watchdog restarts the channel -- see "Known
issues in beta.5" below.

**T6 relaunch-count retest, real-hardware soak on tester `DESKTOP-VBMA6O5`,
kit `e502074` (mission `soak8-e1acfe6`, planned 2 hours, actually run 2.5
hours):**

```
T6_RESULT=FAIL beats=83 failed_beats=0
relaunches_public=2
relaunches_education=1
relaunches_government=3
```

`beats` counts the harness's 83 recorded heartbeats over the run;
`failed_beats=0` because TSDuck (`tsp`) passed on every 30-minute probe
cycle from 09:36Z onward -- the only two probe failures, at 08:28Z and
09:06Z, predate `ON_AIR` (the channels had not yet been created) and are
excluded. PASS criterion is `relaunches=0` per channel; this run did not
meet it. Kit `e502074` was `main` at soak time -- it carries #169's
state-write encoding fix but not the caption-tap overload fix (#172,
merged), so this retest measures the caption-tap-driven relaunches
described above, not a regression in the rollover fix itself (0 rollovers
fired in this run). Evidence: tester branch
`tester/soak8-e1acfe6-DESKTOP-VBMA6O5` (`soak/final-verdict.json`,
`soak/SOAK-REPORT-DESKTOP-VBMA6O5-20260905T113614Z.md`,
`soak/DIAG-9i-20260905T103612Z.md`); local copy
`C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\tester-soak8-e1acfe6-20260905\`.

**Second real-hardware soak, first attempt -- ARCHIVED, not evidence about
#172.** Soak clock started `2026-09-05T18:40:36Z` on tester
`DESKTOP-VBMA6O5`: installing kit `91caebc` (the final beta.5 candidate,
carrying #172) as an install-over the still-live `e502074` station from
the soak above. Because both kits declared the same `1.0.0-beta.5`
version string, known issue 6 above applied: the installer's pack staging
treated the app payload as already satisfied and never replaced it, so
this run kept executing the *old*, pre-#172 caption tap the whole time
-- the installer exited `0` and `/health` came back healthy regardless,
because from the installer's perspective nothing needed to change. The
control plane ran at roughly 4 CPU cores with the same `CRITICAL` caption
overload lines described above, and the station relaunched channels twice
in the first 35 minutes -- the exact behavior #172 was written to fix,
reproduced because the fix's own code never actually made it onto the
box. **This run is archived and is not read as evidence for or against
#172** -- it measured the previous candidate under a new label, not the
new one.

**Second real-hardware soak, valid retest: clean install of kit
`91caebc`.** To get a real measurement, the tester uninstalled the
station completely (including a data wipe) and ran a fresh `/S` install
of kit `91caebc` from scratch -- this sidesteps known issue 6 entirely,
since there is no prior install for the version-string comparison to
match against. The installed `captions/tap_worker.py` hashed to sha256
`0a9610bb...`, equal to the kit's app-payload pack, and `tap_backoff.py`
was present. First admin was created, and the same four approved LPM
clips were uploaded across three GStreamer channels (`public`,
`education`, `government`); ffprobe is not present on this box, so the
schedule setup fell back to its 30-second default clip duration (the
playout engine trims each clip to fit at air), committing 272
thirty-second schedule items per channel. All three channels were
ON_AIR with content when the clock started. Soak clock started
`2026-09-05T20:16:29Z` on tester `DESKTOP-VBMA6O5`. **PENDING -- the
soak's own verdict is not yet complete as of this writing (expected
around 22:26Z).** Verdict: `<SOAK3_VERDICT>`; relaunches observed:
`<SOAK3_RELAUNCHES>`. This section will be updated in place once the soak
finishes; do not read a pass/fail verdict here until the placeholders
above are filled with a real result.

## Also in this candidate: the Gate A schema proof now actually executes

Four sequential harness-only bugs, each exposed by fixing the one before it,
all on the cross-version-upgrade lane's independent post-upgrade `psql`
schema proof:

- **#158 -- `tsp.exe`'s exit code came back `null` on PowerShell 5.1**
  (`Start-Process -PassThru` + `Wait-Process -Id` needs the process handle
  touched first), which judged a fail-exit- against Gate A run
  `33826665417`'s otherwise fully healthy TSDuck capture (1229 packets, 0
  invalid syncs, 0 transport errors). Fixed by caching `$proc.Handle`.
- **#160 -- the schema proof read `DatabaseUrl` from the wrong registry
  key** (`HKLM\SOFTWARE\CivicCast` instead of the installer's actual
  `HKLM\Software\CivicCast\Native`), judging every reaching upgrade run
  `<no-database-url>` (first seen: Gate A run `33857982657`, kit `c27c6e7`,
  install/activation/health all independently passing). Fixed; contract
  test pins the key against the NSIS source.
- **#161 -- the proof's SQL argument to `psql` was not quoted**
  (`Start-Process -ArgumentList` splits unquoted arguments), so `psql`
  warned about an ignored extra argument, ran a bare `SELECT`, and exited 0
  with no rows -- judged `<no-alembic-version-row>` (Gate A run
  `33870994702`, kit `c27c6e7`). Fixed by quoting the SQL and treating an
  exit-0-with-warnings result as a failed proof.
- **#163 -- the proof's single `UNION ALL` query failed outright when only
  one of `civiccast.alembic_version`/`public.alembic_version` exists** (the
  product keeps its version table in the `civiccast` schema only) -- Gate A
  run `33885550628` (kit `c27c6e7`) recorded `<psql-failed>` with `relation
  "public.alembic_version" does not exist` while
  install/activation/health/DB-at-head all independently passed. Fixed by
  querying each namespace in its own statement and falling through cleanly
  on "does not exist."

Each bug was found only after the one before it was fixed. Tonight's Gate A
run is the first whose cross-version-upgrade lane can reach a real,
independent `psql`-read verdict on the post-upgrade schema instead of
failing inside the harness before producing one. This is a harness-only
class of fix -- it does not touch the product's own upgrade/migration code
path, only the independent proof that checks it from the outside.

## Known issues in beta.5

1. **Seamless rollover has a residual freeze case (#162).** If the next leg
   is not ready before the outgoing clip ends, the output freezes until it
   becomes ready or the existing 10-second stall watchdog restarts the
   channel. The immediate-switch (non-rollover) path is unchanged. Not yet
   scheduled; tracked as a follow-on to #162.
2. **Gate A harness self-test lane still to add (batch 27).** The four
   independent-proof bugs fixed above (#158, #160, #161, #163) were each
   found by a real Gate A run failing in a new way, one at a time, rather
   than by a test exercising the harness's own proof logic in isolation. A
   self-test lane for the harness is queued as batch 27 and is not part of
   this candidate.
3. **Captions are best-effort and pause under load (#172, merged).** The
   caption tap's overload backoff means a box that cannot keep up pauses
   captions rather than risk playout -- a three-channel, CPU-only station
   will see captions pause under sustained load. Playout always wins over
   captioning.
4. **Planner defects tracked separately (#170, open).** Found while
   diagnosing the restarts above: schedule slot duration was ignored (a
   30-second slot of long media could air for hours), plans were sized by
   item count rather than duration, and the health poll re-read a worker's
   entire growing stderr log every 2 seconds. Not part of this candidate.
5. **A channel an operator started by hand does not come back on its own
   after an upgrade install or any service restart -- only a channel with
   "Start automatically" turned on does (beta.4 and beta.5).** On every
   restart, channel automation re-starts a dark channel only when its
   config has `auto_start=true`; a channel the operator switched on by
   hand without that setting stays off the air until the operator opens it
   and presses Start again (`civiccast/egress/automation.py:478-493`). A
   channel's on-air/off-air choice and its `auto_start` setting are both
   ordinary config/state rows (`egress_configs`, `egress_states`) and
   survive an upgrade install untouched -- nothing is lost, the automation
   loop simply does not act on a channel that was never marked to
   auto-start. **Operator action:** after any upgrade or restart, check
   each channel you run by hand and press Start if it is not already on
   air, or turn on "Start automatically" for it so this is not needed
   again. Gate A's cross-version-upgrade lane does not assert on-air state
   after install-over, so this gap is not caught by that lane.
6. **Installing a kit over a station that already reports the same version
   string does not replace the app -- it silently does nothing.** The
   installer's pack staging
   (`civiccast/apps/installer/src-tauri/src/native_pack_staging.rs`,
   `classify_dest_pack_state` -> `AlreadySatisfied`, and
   `ensure_pack_extracted`'s matching early return) decides whether to
   re-stage a pack by comparing the already-installed pack's declared
   `product_version` string to the kit's -- it never looks at the pack's
   actual content. When a kit is rebuilt without bumping that version
   string, installing it over a station already on that version leaves the
   old files in place: the installer still exits `0` and `/health` still
   comes back healthy, because nothing about the running station actually
   changed. **Measured on the tester:** installing kit `91caebc` over a
   station that was already installed from an earlier `1.0.0-beta.5`
   candidate left the pre-#172 caption tap running underneath it -- proven
   by comparing file hashes before and after the install, not by anything
   the installer or the health check reported. **This does not affect the
   customer upgrade path:** a real beta.4 -> beta.5 upgrade carries two
   different version strings, so the version comparison correctly sees a
   change and replaces the payload, exactly as documented above. It only
   affects re-installing the *same* declared version to pick up a kit that
   was rebuilt without a version bump -- something only this project's own
   release process does today. **Workaround:** uninstall the station
   completely, then install the new kit fresh, rather than installing over
   the existing station. **Fix pending:** tracked as
   `fix/pack-staging-identity-not-version-string` -- not part of this
   candidate.

## Also in this candidate: release-prep

- **#164 -- identity bump to `v1.0.0-beta.5`, baseline repin to the
  published beta.4 kit, clock-timed source-factory table.** Every
  `check_release_identity.py`-bound surface now reads `1.0.0-beta.5`;
  `sandbox-lab/upgrade-baseline.json` is repinned from the beta.3 kit to
  the published beta.4 kit (source SHA
  `c27c6e70200406b51558ee1ef6b3a95ee4dc4426`, build run `33854799455`, Gate
  A run `33901203343`) so Gate A's cross-version and download-only lanes
  upgrade from the actual current published release. Also fixes a
  `source_leg_is_clock_timed` docstring/code mismatch (the fail-safe
  default for an unknown source factory has always been `False`, not
  `True` as documented) and adds the Windows live-capture device factories
  to `CLOCK_TIMED_SOURCE_FACTORIES`. See `[Unreleased]`/`[1.0.0-beta.5]` in
  `CHANGELOG.md` for the full account.

Full detail for every item above is in the dated `[1.0.0-beta.5]` section of
`CHANGELOG.md`.

## Surfaces to flip at publish time (prepared list, not applied in this PR)

This PR deliberately does **not** change any of the following to say
`v1.0.0-beta.5` is current -- that flip happens only at actual publish time,
alongside `docs/releases/release-truth.yaml`'s `staging` -> `current` flip
for `v1.0.0-beta.5` and `current` -> `superseded` flip for `v1.0.0-beta.4`.
Prepared here so publish is a mechanical sweep, not a rediscovery:

- `README.md` -- "Current version" banner, the beta.4 GitHub Release link,
  the `v1.0.0-beta.4-verification.md` link, and the "next candidate"
  paragraph naming beta.5 as owner-held/unpublished.
- `docs/index.html` -- the version-identity HTML comment, the FAQ's "is
  this the current release" answer, and the "next candidate" paragraph.
- `INSTALL-WINDOWS.md` -- any "upgrade of an already-installed station"
  wording that names beta.4 as the target of an in-place upgrade.
- `docs/tester/START-HERE.md`, `docs/tester/lpm-beta-test-handoff.md`,
  `docs/tester/known-limitations.md`, `docs/tester/SMARTSCREEN-WALKTHROUGH.md`,
  `docs/tester/technical-walkthrough.md` -- "current release" wording.
- `ARCHITECTURE.md`, `SUPPORT.md`, `FAQ.md`, `CAPABILITIES.md` -- release
  posture paragraphs naming the current candidate.
- `docs/adoption/release-policy.md` -- any current-release cross-reference.
- `docs/releases/release-truth.yaml` -- flip `v1.0.0-beta.5` `staging` ->
  `current`, `v1.0.0-beta.4` `current` -> `superseded` (`superseded_by:
  v1.0.0-beta.5`).
- This document and `v1.0.0-beta.5-verification.md` themselves --
  `Status: DRAFT` -> `Status: PUBLISHED`, all `<PLACEHOLDER>` tokens filled
  with the real run ids, hashes, and evidence paths from tonight's actual
  run.

## Evidence (to be filled in at publish time)

- **Release:** `gh release view v1.0.0-beta.5 -R scottconverse/civiccast-native
  --json isDraft,assets,targetCommitish,tagName`.
- **Hash + signature, verified from the outside:**
  `scripts/download_windows_release_artifacts.ps1 -AssetSet NativeCandidate`,
  cross-verified against `SHA256SUMS.txt` and `Get-AuthenticodeSignature`.
- **Gate A:** run `33972726431`, all three lanes PASS, evidence copied to
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-verdict-33971258093\gate-a-verdict.json` /
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-dirty-verdict-33971258093\gate-a-verdict.json` /
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-v1.0.0-beta.5-final-33972726431\gate-a-download-only-verdict-33971258093\gate-a-verdict.json`.
- **T6 relaunch-count retest:** tester branch
  `tester/soak8-e1acfe6-DESKTOP-VBMA6O5` and local copy
  `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\tester-soak8-e1acfe6-20260905\`
  (see "T6 relaunch-count retest" above -- already run, real-hardware,
  `FAIL`; not a publish-time placeholder).
- **Test suite:** `uv run pytest tests/docs tests/policy -q` re-run for this
  publish; see the commit history on this branch for the result.

## What did NOT change

- The kit-staging directory the live soak tester reads is not touched,
  moved, or deleted by this draft.
- The ~21 GB `station\` AI-model bundle is not, and will never be, a GitHub
  release asset.
- No tag or draft release exists yet for `v1.0.0-beta.5`. If the publish
  does not succeed end to end, this document stays a draft and nothing
  above is presented as done.

## Related

- `docs/releases/release-truth.yaml` -- the authored release-state record;
  unchanged by this PR (`v1.0.0-beta.4` stays `current`, `v1.0.0-beta.5`
  stays `staging`).
- `docs/releases/v1.0.0-beta.5-verification.md` -- this candidate's draft
  verification record (Gate A run, asset/hash/signature checks -- all
  placeholders pending tonight's run).
- `docs/releases/2026-09-03-beta4-release-notes.md` -- the immediately
  prior publish record, same pattern this document follows.

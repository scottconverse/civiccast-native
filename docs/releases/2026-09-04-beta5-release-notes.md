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
targeting source SHA `<KIT_SHA>`. Like beta.3/beta.4, it will be
downloadable: `setup.exe` and the runtime `.ccpack` packs as release assets,
verified by a published `SHA256SUMS.txt` and a `setup.exe.sidecar.json`
sidecar.

**For Sergio/LPM (already on `v1.0.0-beta.4`): this will be a download-only
upgrade**, exactly as beta.3 -> beta.4 was. Run `setup.exe` (with the
runtime packs) over the existing install -- no `station\` folder, no
re-downloading the ~21 GB AI-model bundle. Recordings, settings, database,
and AI models already on the machine are kept.

Will be published via `python scripts/release/publish_beta_candidate.py
--kit-dir <kit> --source-sha <KIT_SHA> --build-run-id <BUILD_RUN_ID>
--gate-a-run-id <GATE_A_RUN_ID> --tag v1.0.0-beta.5 --truth-status current`,
whose fail-closed checks must all pass before any GitHub state is touched:
version identity agreeing across `setup.exe` ProductVersion,
`civiccast._native_version.__version__`, and the tag (already
`1.0.0-beta.5` as of PR #164's version bump); Authenticode signature status
`Valid`; Gate A run `<GATE_A_RUN_ID>` showing `PASS` on all three required
lanes.

## Headline: seamless source-plan rollover (#162)

beta.4's own 120-minute engine soak proved the GStreamer default engine
itself healthy for two continuous hours (`failed_beats=0` across 66
samples) but failed Gate A's T6 lane on a relaunch-count rule: the playout
worker exits cleanly at the end of every source plan
(`civiccast/egress/source_plan.py`'s `max_segments=8`), which happens every
10-15 minutes under continuous back-to-back premieres, and each
exit-and-restart is a short on-air blip. `v1.0.0-beta.5` fixes the root
cause instead of the symptom:

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

**T6 rollover soak retest, sandbox-lab `soak-4h` on HALO, proof kit
`b2b5694`:**

```
T6_RESULT=<SOAK_RESULT> beats=<SOAK_BEATS> failed_beats=<SOAK_FAILED_BEATS>
relaunches_public=<SOAK_RELAUNCHES_PUBLIC>
relaunches_education=<SOAK_RELAUNCHES_EDUCATION>
relaunches_government=<SOAK_RELAUNCHES_GOVERNMENT>
```

PASS criterion is `relaunches=0` per channel. Evidence:
`<EVIDENCE_PATH_SOAK>`.

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
- **Gate A:** run `<GATE_A_RUN_ID>`, all three lanes, evidence copied to
  `<EVIDENCE_PATH_CLEAN>` / `<EVIDENCE_PATH_CROSSVERSION>` /
  `<EVIDENCE_PATH_DOWNLOADONLY>`.
- **T6 rollover soak:** `<EVIDENCE_PATH_SOAK>`.
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

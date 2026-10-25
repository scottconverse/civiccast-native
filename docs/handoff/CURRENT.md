# CivicCast portable handoff â€” October 24, 2026

## Active F1–F3 execution — October 25, 2026

Owner assignment: execute F1/F2/F3 from plan commit `7edc550049c38b3806ba091e4f3d6b9d6051b6b9`;
implement, verify focused behavior and CI, push DCO commits and deliver a review-ready PR.
**No merge, release, installer rebuild or installed-station update. Goal remains incomplete
until real YouTube acceptance and CI are satisfied.**

- Candidate: `C:/Dev/civiccast-f1-f3`, branch `fix/f1-f3-caption-publish-dependencies`,
  based on plan commit `7edc5500`; fetched main `933dd657`. Original checkout and its
  uncommitted restart checkpoint are preserved. One executor; routing skill applied,
  current agent retained; no independent reviewer was commissioned.
- F1: earlier review missed delivered source commits `5c3540ec` and `5ca75521`.
  Preserve those fixes: package timeline clips/rebases approved English/Spanish cues;
  repackaging reconstructs from approved source cues and holds missing/stale review.
  Existing caption/packager/PDF focused run: 107 passed; eight auth failures diagnosed
  as ambient `CIVICCAST_STAFF_TOKENS`, with all nine packaging cases passing after
  clearing it in the isolated child shell. Real fractional trim passed. Added combined
  real FFmpeg package + bilingual-caption sample passed (0.333–0.9 s range, head/tail
  removed, cues 0–0.167 and 0.467–0.567 s, originals preserved). No caption engine change.
- F2 implemented: protected Setup values feed IA/YouTube/NAS/SMTP settings directly,
  explicit provider selections retained, no environment mutation or duplicate setup.
  Added refresh-token and SMTP fields; webhook-only configuration stays compatible.
  Selected channel's fresh local HLS feeds a separate owned FFmpeg RTMPS output;
  event title/current start/privacy/auto-start/stop are configured and bound.
  Watch links replace ingest links. Destination polling distinguishes starting/live/
  failed/stopped; startup timeout, process exit, disconnect, stop, partial event setup,
  shutdown and restart interruption are handled. Unused events/streams are cleaned up;
  remote cleanup failure is reported; shutdown continues if status saving fails.
  Destination polling is 30 seconds to limit API quota use; UI polling stays local. CAS surface updates preserve concurrent publish
  work; dashboard reads remain batched. Legacy unconfirmed YouTube successes display
  unverified and private ingest URLs are removed from responses. Local portal survives
  output/provider failures. Mocks explicitly remain simulated/unverified.
- F2 acceptance blocker: no YouTube OAuth client ID/secret/refresh token in the existing
  shell or saved Setup store. Asked Scott for an existing protected credential location
  (never secrets in chat); no response yet. No account, spending or external YouTube
  event was created. **Simulator proof is not real YouTube viewer acceptance.**
- Software receiver proof: existing real FFmpeg sender and loopback RTMP receiver
  transferred 62,197 bytes of FLV; simulated API confirmation drove starting/live/
  stopped; sender was reaped and receiver terminated. Contract tests cover metadata,
  OAuth, cleanup, missing source, process/destination failure and confirmation timeout.
- Verification: 190 backend cases passed, then 39 real-sample/lifecycle cases after
  cleanup corrections, 156 publish cases after CAS/batched-read changes, 21 targeted
  legacy/query-count/default-selection regressions. Final restart/setup regression: 27 passed.
  Operator publish UI: 31 passed including channel payload/stop; operator build/lint
  passed. Public portal: 69 passed and lint passed. One stale on-air wording assertion
  failed with both old Vitest 4.1.11 and updated 4.1.12; corrected only the test to the
  existing playback-position wording. Native lock/closure checks: 71 passed.
  Repository Ruff check/format passed with pinned 0.15.12; full mypy passed for 725
  files with pinned mypy 2.0.0/SQLAlchemy 2.0.49. Earlier latest-tool diagnostics were
  resolved by matching the lock, without unrelated source changes. Generated API
  artifacts updated. Claims blob and marker checks found no drift. Final CI pending.
- F3 targeted updates only: uv lock changes exactly four package versions; native app
  lock changes only pypdf/filelock/setuptools; runtime lock changes setuptools. Existing
  LGPL PyAV wheel hash and all other native pins retained; app lock hash updated.
  Public/operator npm lock changes are Vitest family/Zod and public Undici only.
  Fresh pip-audit passes existing allowlist policy; both npm audits have zero findings.
  No suppression/threshold/workflow changes. Existing NLTK PYSEC-2026-3740 exception
  remains unchanged and is outside these selected remediation claims.

| Dependency | Corrected advisory identities | New pin and exposure |
|---|---|---|
| pypdf | CVE-2026-115572 / GHSA-6c7f-9265-g8fw; CVE-2026-115585 / GHSA-jr96-gvgh-j3r4; CVE-2026-115580 / GHSA-gmh7-3g9r-mjh5 | 6.21.2; runtime uploaded/vendor PDF extraction, addressed first |
| filelock | CVE-2026-112940 / GHSA-v4x8-3wr5-3wq8; CVE-2026-112913 / GHSA-9vhv-jxww-xfm5; CVE-2026-112907 / GHSA-567q-5qvw-pf92 | 4.2.4; caption model-cache dependency and dev virtualenv; local/shared-lock risks, largely POSIX |
| setuptools | GHSA-xmj3-9gf7-h52w | 84.2.1; bundled app/runtime installer tooling; vulnerable wheel-install path, outside normal playout |
| virtualenv | CVE-2026-113713 / GHSA-4f8h-vr72-p32c | 21.14.13; dev/pre-commit tooling |
| Vitest / mocker | GHSA-qxg6-89mg-rqv8; GHSA-xp26-3454-mjgp | 4.1.12 family; development test server/tooling |
| Zod | GHSA-mrhx-c7xc-m3w5 | 4.6.7; frontend development ESLint tooling |
| Undici | GHSA-4qv8-2p9j-2685; GHSA-f72v-6w45-q472; GHSA-xjj6-f33q-929c | 7.30.1; public portal dev jsdom dependency |

Installed environments retain their current packages. Applying these dependency fixes
later requires an owner-authorized installed application/runtime update from corrected
locks (including caption environment filelock where present). Nothing was installed into,
restarted or rebuilt for the endurance station. Source CI does not prove its remediation.

- Next: finish focused restart/setup results, commit/push one candidate, open PR, then
  follow CI using GitHub's existing watch facility. PR267 is open (no merge authorized).
  Initial candidate `4b90b888375b7a20eb92c3c7f0e69c47aa4a60b0`; one final cleanup/quota
  correction is being pushed. CI watch session98103, started October25 ~13:54 Denver,
  watches PR267 every30s and exits when checks finish; Ctrl-C cancels only this watch.
  ci-test run40228250962 is the initial run (a new push supersedes it automatically).
  Local check sessions/logs live under the original chat's `work/` scratch directory;
  all local check processes are terminal; no owned background process remains.
- Boundaries: no station touch, LFS transfer, installer, release, merge, paid service,
  account creation, F4–F7/N-series work or automatic delegation. Historical records below
  are superseded only for this explicitly authorized F1–F3 assignment.

## Historical restart checkpoint â€” October 25, 2026

Scott requested preparation for context compaction and a Codex app update/restart.
This checkpoint is a local documentation change only; it has not been committed
or pushed, and must not automatically trigger another PR or CI cycle.

- Checkout: `C:\Dev\civiccast-native`, branch `fix/brotli-agenda-advisory`,
  HEAD `0fb01b0bc51bfa648dac2fc419890fd3d18d15f2`.
- Fetched `origin/main`: `933dd6571ab57ee5891f76c1148b79cb9c77bbc0`.
  PR265 (checker/handoff) and PR266 (targeted Brotli) are merged. Both authorized
  delivery tasks are complete; there is no pending merge, build or release.
- **Leave the endurance station running.** Scott explicitly said it is a test
  station to see how long it runs without issues. Do not update its installed
  packages, restart its processes/services, reinstall, reboot, stress-test, or
  interrupt it. At this checkpoint `CivicCastSupervisor` is Running, PID12084.
- No owned CI watcher/helper remains running. Wait sessions78744,94426,19473
  are terminal; the final watcher confirmed the PR266 merge. A process-name/
  command-line probe found no visible Python checker/Brotli wait helper.
- No installer rebuild, new release, LFS transfer, or installed-station package
  update was performed. The Codex app update/restart itself was not initiated.
- Latest requested review is complete: specs, records, current source, open
  issues/PRs, and five related repositories were inspected read-only. Scott has
  **not authorized implementing the resulting backlog**. Resume by reading the
  report and the next owner instruction, not by starting repairs automatically.
- Full review and source references:
  `C:\Users\scott\Documents\Codex\2026-10-24\us\outputs\civiccast-unfinished-work-review-2026-10-25.md`.
  Brotli investigation/merge receipts:
  `C:\Users\scott\Documents\Codex\2026-10-24\us\outputs\civiccast-brotli-investigation.md`.
- Main findings: other dependency advisories; trimmed-recording caption timeline;
  fixed/nonexistent CG preview segments; installed native launcher unsigned
  (read-only signature check); intermittent replacement-program test failure;
  native-app audience beacons missing; incomplete field workflow evidence; five
  unreconciled open PRs; stale current-status records. Distinguish confirmed
  defects, static source gaps, missing proof and owner-deferred work.
- TownLight integration is owner-deferred to2.0. Historical WSL/macOS/audit-role
  obligations do not revive retired work or superseded workflow gates. No new
  release requirements or automatic audit/delegation were authorized.
- Scott requested the `codex-model-routing-1024` skill for this session:
  `C:\Users\scott\.codex\skills\codex-model-routing-1024\SKILL.md`.
  Keep the suitable current agent; no automatic delegation/model change. Keep
  Windows helpers hidden and gh inside invisible ConPTY (`tty=true`,
  `login=false`), preserve disabled telemetry, no host reboot, no LFS spending.

The following entries retain their original preparation/history scope. This
restart checkpoint and the confirmed merge receipts supersede pending wording.

## Completed follow-up â€” targeted Brotli correction

The checker integration below is complete: PR265 merged into main at
`f9d380bebb15489762424f4f1293f4e6f050211a` after current-head unit tests,
Windows probes and claims verification passed (test run `40161873024`).
Earlier pending/failure notes below describe preparation, not the final result.

Scott subsequently authorized the Brotli dependency fix through a PR and merge
after required CI, with no installer rebuild or new release. Branch
`fix/brotli-agenda-advisory` adds `brotli>=1.2.1` to `agenda-js-import` and updates
the locked decoder from 1.2.0 to 1.2.1. Only the Brotli package record and root
optional-dependency metadata change in `uv.lock`; crawl4ai remains 0.9.2 and all
other package records are identical. Native payload requirements are unchanged.

Passed local checks: `uv lock --check`; semantic comparison of all 200 locked
package records; Python 3.12 Windows x64 wheel availability in the lock; 45
`test_js_portal.py` tests (two real-crawl4ai checks skipped because that extra is
absent locally); isolated Brotli 1.2.1/HTTPX 0.28.1 compressed-response decoding;
and a focused `pip-audit --no-deps --disable-pip` scan of `brotli==1.2.1` reporting
no known vulnerabilities. No waiver or unrelated dependency upgrade is included.

PR266 merged at `2026-10-25T06:32:40Z` as
`933dd6571ab57ee5891f76c1148b79cb9c77bbc0`. Applicable CI passed, including
unit tests, claims verification, optional agenda integration, virtual headend,
publish soak, veraPDF and app-payload reproducibility. The Windows media job
initially failed on an unchanged GStreamer replacement-leg stream error, then
passed on one job-only retry without code/assertion changes. GitHub itself
returned HTTP403 for retry while the workflow was still running; that waiting
restriction was not a repository-configured rule. Test workflow40165319415,
payload reproducibility40165319416. Security40165319459 installed Brotli1.2.1
and no longer reported its advisory; independent Python/npm findings remain
failed and are not waived. Informational randomized run40165319528 was
cancelled, not passed. No independent agent review was required or performed.
No installer or release workflow was dispatched. Existing signed artifacts and
the running station are untouched.
Installed optional-extra environments need a separate package update and process
restart; merging this source fix does not patch running environments. Earlier
Brotli investigation and other security findings below remain historical evidence.

Read this file and the root `AGENTS.md` / `CLAUDE.md` before continuing. This is
the current handoff, replacing dependence on the previous coordinator's local
chat and drive. Historical release records retain their original evidence scope.

## Get the complete handoff

Repository: <https://github.com/scottconverse/civiccast-native>

This handoff and the checker fix are on **`fix/beta20-portable-handoff`**, based on
published main commit `121465506a7314f02ad7572337b46a83fa3f6e51`. They are being
delivered as a branch, not represented as already merged into `main`.
Do not start from the Beta20 tag expecting the latest instructions or package source.

PowerShell, on the destination machine (choose a short writable source directory):

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
$env:GIT_LFS_SKIP_PUSH = '1'
git clone --single-branch --branch fix/beta20-portable-handoff https://github.com/scottconverse/civiccast-native.git civiccast-native
Set-Location civiccast-native
git status --short --branch
git log -1 --oneline
```

No `git lfs pull`, `fetch`, or `push`; no LFS transfers or spending through
October 2026. The current tree has no LFS-tracked files; historical revisions may.
The handoff branch deliberately has no PR yet: creating a PR launches broad
application CI. Scott requested a push and portable handoff, not another CI cycle
or merge. Check current remote state before later integration.

## Current result and exact identities

- **Beta20 is already public:** [release and assets](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.20).
  GitHub labels it a prerelease because it is a beta; it is not a draft.
- Current installer is the documentation revision built from
  `2e19612467fda894d63e499580e4d7b5f029f5f2`, signed
  [build 39810481727](https://github.com/scottconverse/civiccast-native/actions/runs/39810481727).
  Setup SHA-256: `6c0aa52d773a4c5c0a0643e00d860a83560551d497c5f1efb05cba5beadc3e5d`.
  Existing evidence records a valid Scott Converse signature and installed Help/manual acceptance.
  See [Beta20 verification](../releases/v1.0.0-beta.20-verification.md).
- Original release tag remains at `a17449189a39af6474d914137eab020169f91023`.
  The tag's automatic source ZIP is **not** the documentation-revision source.
  Do not move the tag or rebuild an installer to reconcile these identities.
- [PR263](https://github.com/scottconverse/civiccast-native/pull/263) merged the final
  prior CI corrections at `086f1b967766aaea31a5a4296ce6f96771e2d72f`.
  Its recorded rollup was 21 successes / 3 inapplicable skips / 0 failures.
  That historical pass does not claim later CI is green.
- The approved station-manager landing page and Scott's biography are live at
  <https://scottconverse.github.io/civiccast-native/>.
  [PR264](https://github.com/scottconverse/civiccast-native/pull/264) merged at
  `121465506a7314f02ad7572337b46a83fa3f6e51`;
  [Pages run 39989225060](https://github.com/scottconverse/civiccast-native/actions/runs/39989225060)
  succeeded. Live HTTP 200, headline, biography/LinkedIn, loaded images and working
  walkthrough were checked, with no browser JavaScript errors. Six local tabs and
  390/768/1440-width layouts passed. The walkthrough is explicitly an illustration,
  not a real station demo. No customer testimonial or production-station claim was invented.

## Checker correction included in this branch

Only `scripts/verify_native_runtime_closure.py` and
`tests/native/test_closure_verifier.py` change checker behavior.

The last passing Windows run used GitHub image `20261007.264.1`; the failing run
used `20261021.278.1`. Product runtime, dependency lock, checker and workflow were
unchanged between those runs. The rejected file was Windows Terminal's root
`resources.pri`, observed as a known non-executable mapping. Six other closure
checks passed, including plugin origin and the caption embed/decode round trip.
This is a data-resource classification false positive, not evidence of a missing
media DLL. The precise Windows API that mapped the file was not captured.

The correction recognizes the stable Microsoft Windows Terminal x64 package
identity (numeric version, publisher `8wekyb3d8bbwe`) and **only root
`resources.pri`**. The path stays visible in the report. Executable and unknown
protection mappings, DLLs, wrong publishers, different packages and subdirectories
still fail. Canonical-path and file-identity safeguards are retained.

Existing verification, October 23, reused without rerunning unchanged code:

```text
.venv\Scripts\python.exe -m pytest tests/native/test_closure_verifier.py -q --no-cov
153 passed in 6.38s
ruff check: passed
ruff format: applied; changed files reviewed
git diff --check: passed
```

This is local checker-logic evidence, not a new hosted Windows pass or installed
product test. No installer rebuild is required for this change.

Historical Windows runs:
[passing 39923178286](https://github.com/scottconverse/civiccast-native/actions/runs/39923178286)
and [failure 39987938776](https://github.com/scottconverse/civiccast-native/actions/runs/39987938776).
The failed prerequisite caused later Windows suites to skip; missing JUnit reports
are consequences, not separate product defects. Other broad PR264 runs were cancelled
to avoid unchanged full-suite/manual work; cancellation is not a pass.

## Remaining work, not authorized as part of this handoff push

1. Integrate this branch through the repository's normal PR process when requested.
   The corrected checker has not been exercised on the updated hosted Windows image.
   Use the existing affected Windows job when integration requires it, not repeated
   full suites or a new installer. Do not claim repository-wide CI is green.
2. The Python audit reported `brotli 1.2.0 / PYSEC-2026-4322`, pulled in through
   `crawl4ai 0.9.2`. See [run 39987938274](https://github.com/scottconverse/civiccast-native/actions/runs/39987938274)
   and main security run `39989225752`. Severity, reachability and inclusion in the
   released installer were **not established** in this session. The finding has not
   been fixed or waived. Inspect the advisory and actual dependency use before a
   bounded dependency correction; do not invent an allowlist exception.

The next agent should take Scott's current assignment. Reading this handoff is not
permission to restart old nine/twelve-goal lists, redesign the product, create a
new release, or repair unrelated findings.

## Accepted behavior and boundaries to preserve

- Scott accepted the observed ~8.763-second caption sample delay and brief
  previous-program carryover for Beta20. It is not a universal latency bound and
  not a new release blocker.
- Summary evidence covers a short transcript and cited narrative; no long-meeting
  benchmark is claimed. Local AI model RAM requirements still apply.
- Roku acceptance uses the repository's software/API mocks and BrightScript
  validation. Scott explicitly prohibits physical-hardware testing requirements.
- The previous host was a test server, with owner-authorized reset/stop/start
  operations. Do not infer that a new machine is a test host without context.
- Mutation testing was removed at Scott's request. Never restore it as a CI or
  release requirement, or promote informational results into mandatory gates.
- Serial work, one justified candidate, no automatic subagents or repeated audits.
  Every additional check must address changed behavior, an unresolved requirement,
  a concrete defect or required CI. Reuse unaffected evidence and artifacts.
- No LFS transfers, new spending, host reboot or installer rebuild for this handoff.
  Keep windows/helpers hidden. No automatic monitor or continuation is required.

## Build, runtime and machine state

See [BUILD-ASSETS.md](BUILD-ASSETS.md) for exact source locations, asset sizes,
existing release downloads, the FFmpeg mirror and PyAV reuse recipe.
Source checkout and checker development do not require copying the old machine's
station data, models, installer, virtual machines, `.venv`, or agent tooling.

The old untracked `.codex/` directory is deliberately not imported. It contains
machine-specific Desktop paths, historical authorization/evidence files and
wake/completion hooks for a previous assignment. These are not product build inputs.
Current owner rules are portable in `AGENTS.md` and `CLAUDE.md`; do not recreate
old hooks or depend on `C:/Dev/codex-hook-kit` to develop CivicCast.

The previous workspace has older candidate/worktree directories. This handoff is
for the current released native product and this branch; it does not certify or
publish abandoned experiments from every historical worktree. The coordinator's
incident drafts, token-accounting reports and browser mockup scratch files are
not prerequisites. Relevant product status and evidence are linked above.

No fresh-machine build was run for this handoff. Required binary sources are
identified; availability of every third-party download and access to private
signing credentials are not implied by a successful Git clone.


## Integration and advisory investigation â€” October 24, 2026

Scott authorized [PR265](https://github.com/scottconverse/civiccast-native/pull/265)
and merge after applicable CI passes, followed by a Brotli investigation/report.
No installer rebuild or new release is authorized. At preparation of this update,
integration awaits corrected-head CI; PR265 records the subsequent merge result.
Do not infer repository-wide green CI from a merge: informational scans have findings.

- Initial PR head: `50b4e11d15f36aa50ba2bf02f9bd417d1e1ddf60`.
  Windows closure/native job `121056228553` passed in run `40155601318`.
  App-payload reproducibility run `40155601291` passed byte equality.
- Informational randomized run `40155601353` exposed five deterministic stale
  policy/doc assertions (seed `824704267`): native collection counts/floors,
  removed historical coder-seat wording, and two old landing-page assumptions.
  All five reproduced locally. The still-running unit workflow `40155601318`
  was cancelled before pushing corrections; cancelled is not passed.
- The integration correction updates collection expectations to 2082 pure /
  2324 total / 2321 Windows non-integration tests, and raises JUnit floors to
  2032 / 2271, preserving the existing 50-test margin. Role checks protect
  current owner assignment; landing-page checks protect current release links,
  reject withdrawn releases, retain prohibited-claim checks and require historical
  citations if historical measurements return. Product/page content is unchanged.
- Reuse the passed payload byte-equality proof for these test/doc/floor-only
  corrections; they do not alter packaging. Await applicable CI on the corrected
  PR head, including the downstream claims-evidence verifier, before merging.
  Main rules require a PR but returned no named required checks or approving
  review requirement. The security workflow and randomized suite are explicitly
  non-required/informational; report their findings without making them new gates.
- Focused local verification passed: 50 documentation/role tests and 21 native
  workflow-policy tests (including live collection/floor checks), plus ruff lint,
  formatting and git diff --check. The checker code remains unchanged; reuse its
  153-test evidence and the hosted Windows proof above.
- Previous local watchers ended. Next action at preparation: push the corrected
  head, wait for applicable CI, and merge the exact authorized candidate.

Brotli findings (dependency correction is not implemented):

- PYSEC-2026-4322 / CVE-2026-111497 / GHSA-9v8h-qqgm-4m35 is one upstream
  decoder memory-corruption issue, rated critical (CVSS 4.0 9.2), fixed in 1.2.1.
  See [PyPA advisory](https://github.com/pypa/advisory-database/blob/main/vulns/brotli/PYSEC-2026-4322.yaml)
  and [upstream fix release](https://github.com/google/brotli/releases/tag/v1.2.1).
- Optional `agenda-js-import` -> crawl4ai 0.9.2 (`brotli>=1.1.0`) locks 1.2.0.
  Installing that extra enables HTTPX's Brotli decoder automatically. CivicCast's
  `js_portal` robots.txt fetch provides a concrete remote-response input path.
  This is static reachability evidence, not an executed exploit or compromise.
- Fix needed: require `brotli>=1.2.1` in that optional extra and refresh only its
  affected lock/hashes; verify the selected version, advisory result and focused
  agenda/HTTP tests. Crawl4ai 0.9.2 accepts 1.2.1, and a Python 3.12 Windows x64
  wheel exists. Installed affected environments also need their decoder updated
  and processes restarted. Do not add an allowlist waiver.
- Exact released source `2e19612467fda894d63e499580e4d7b5f029f5f2` excludes Brotli
  and crawl4ai from the native Python locks; packaging uses `--no-deps`.
  Bounded HTTP ranges inspected the published app pack's ZIP directory:
  1,152,522 bytes read, 9963 entries / 83 wheels, no Brotli/crawl4ai paths.
  Full artifact checksum/signature verification and installed-environment
  inspection were not performed; other embedded decoders are not ruled out.
- Security run `40155601323` also reports filelock, pypdf, setuptools, virtualenv,
  Zod, Vitest/mocker and Undici findings. Their reachability and artifact scope
  were not investigated here. No dependency edits, waiver, installer rebuild,
  release or LFS transfer was performed.

### Claims-binding follow-up during integration

Corrected head `8b3c90174aa584238e6ccc8aa9f58ab895502913` passed its Windows
job in run `40158115701`. Its unit job reported 16 failures / 11712 passes:
all failures derived from six workflow blob bindings left stale by the JUnit
floor correction. Local checks reproduced those six mismatches. The downstream
claims verifier rejected the failed producer; this is not green CI.

The six registry workflow references are renewed after reviewing the floor/comment
only delta; see the October 24 section of the existing current-source review
note. No producer, registered node, control or enforcement is weakened, and no
historical acceptance is renewed. All 125 claims-evidence policy tests passed locally after rebinding (67.49s).
The next candidate must complete same-run CI.
The previous finite merge watcher exited on these required failures without
merging. No merge is currently armed while this follow-up is prepared.

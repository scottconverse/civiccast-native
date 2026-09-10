# CivicCast Native — full project status and cold-start handoff

**Written 2026-09-10, ~11:10 AM Mountain.** Times in this document are Mountain (America/Denver),
12-hour where they are user-facing.

Read this first if you are picking the project up with no prior knowledge. It is written to be
enough on its own: a session on **this machine** can find every local artifact from here, and a
session with **only GitHub access** can find everything it needs without this machine.

---

## 1. What the product is, in one paragraph

CivicCast is an open-source, self-hostable civic broadcast platform for PEG / local-government
stations. It records a meeting, generates offline captions, lets an operator review and approve the
recording, drafts an AI summary linked back to the transcript, schedules it, and publishes it to
residents on a branded portal — and it plays out a continuous cable channel to a headend. It ships
as a **native Windows station-in-a-box**: a signed installer that registers a Windows service and
supervises the control plane, PostgreSQL, and the media workers from a bundled runtime. No WSL, no
Docker, no Linux target. The repository `scottconverse/civiccast-native` is the **only** product
line; an earlier retired WSL2/Ubuntu lane's history lives in a separate private repository.

**The goal driving everything:** a working install for LPM (the beta tester, "Sergio"), who checks
the GitHub releases page daily.

---

## 2. Where the project actually is, right now

| | |
|---|---|
| **main** | `6de69b8e` — green. (`795cdab5` was main when the beta.6 kit was built; the only commits since are this document and the soak evidence.) |
| **Latest public release** | **v1.0.0-beta.5**, published 2026-09-09 10:14 PM |
| **`docs/releases/release-truth.yaml` `current:`** | `v1.0.0-beta.5` |
| **Product version in source** | `1.0.0-beta.6` (release-prep bump already landed) |
| **beta.6 kit** | **built and byte-verified, NOT soaked, NOT gate-tested, NOT published** |
| **Open PRs** | #202, #175, #155, #138 — all pre-existing, none from the 2026-09-09/10 work |

### The one thing that governs every decision from here

Two 8-hour overnight soaks of **beta.5** ran on the night of 2026-09-09 and **both failed**. They
found a blocker that silently kills a channel and never recovers it. **The beta.6 kit that is
already built does not fix it** — the bug was found after those changes were written.

So: **beta.6 must not be published as-is.** See §5.

### What is NOT done — the whole list, in one place

- **F-1 and F-2 are unstarted.** The silent-death bug and the missed schedule boundaries. **Those
  two are the release.** Every fix in §5 is unstarted; nothing below §5's heading has been begun.
- **The beta.6 kit is built and byte-verified but unsoaked, ungated and unpublished.** It sits at
  `C:\CivicCastTester\kit-safe\795cdab5065e3b1b1d9df69c6fc06658f481c8d4\`. Leave it there.
- **No soak has been run against beta.6 at all.** The two failed soaks were of **beta.5**.
- **The kit LAN file server (port 8766) and the Gate A runner are both down** after the 2026-09-10
  reboot. **This does not matter yet** — neither is needed until there is a fixed candidate worth
  testing. Do not spend time restarting them before then. §8 step 0 and §7.2 say how, when you do.
- **The five follow-ups in §3 are unstarted**, and none of them block the release.
- **Not measured, do not assume either way:** picture quality between failures (beta.5 emits no
  drop metric), and anything involving a **physical cable headend** — both soaks used loopback UDP.

---

## 3. What landed on the night of 2026-09-09 → 09-10

Seven fix PRs, every one hostile-reviewed to a `VERDICT: MERGE` with delta rounds, merged in this
order:

| PR | main SHA | What it fixed |
|---|---|---|
| #211 | `74e3d7c5` | Install-helper doc named screens that do not exist; adds `docs/SOAK-PROMPT.md` |
| #212 | `bc32dfa3` | A finite slate plan reaching EOS wrote **STOPPED** instead of relaunching onto the due programme; `STARTING` is now written before source preparation |
| #215 | `184398d9` | **CRITICAL.** `/api/setup/storage` served the PostgreSQL URL **with password** to an unauthenticated caller. Setup routes now require a staff token, and `POST /storage`, `/first-admin`, `/recovery-kit/acknowledge` require the `setup_admin` role once setup is complete |
| #213 | `24894218` | Recovery kit vanished before it was saved; no Sign out control existed; browser autofill painted saved credentials into first-time setup |
| #209 | `91ebe7c7` | Installer's runtime-ownership claim now runs first, gathers machine-wide evidence, and records **why** it refused, with a remedy that is reachable and a message that does not truncate |
| #216 | `0cc34881` | Publish defaulted to **every** surface including Internet Archive — now Portal only; Channels showed fabricated sample rows; Start refused nothing; readiness conflated "rehearsal ran" with "cleared to broadcast" |
| #214 | `2d7fd65b` | Resident portal advertised a **loopback** playlist URL no resident could play; a fallback slate reported itself as "On air"; headend presets did nothing until restart; unbounded local paths behind a public unauthenticated media route |

Review depth, for calibration: #212 and #213 took one round; #215 and #216 three; #214 five; #209
six. Reviewers **executed** rather than read — 71 adversarial database URLs against the credential
describer, all nine ARP state combinations compiled into the installer crate, ten now/next probes
against the resident endpoint, a real `mklink /J` junction swapped in inside a path-resolver cache
TTL, and a mutation-revert of every claimed fix to prove its test was load-bearing.

### Follow-ups filed during that work, none of them blocking

1. **The `FALLBACK_SLATE` Start watchdog can never fire.** The daemon rewrites that row's
   `updated_at` every 2 s, so the "Start was queued but the feed did not start" alert never arms.
   The test that pins it freezes `updated_at`, so it looks green. Full reproduction is in #216's
   round-2 review comment.
2. Withhold `current_source_label` on the unauthenticated `GET /api/public/egress/channels/{id}/now`.
3. `SetupScreen` renders the sign-in form **twice** on a 429 (duplicate DOM ids; still functional).
4. The "Recovery kit never confirmed" button swallows a 403 with no message.
5. A resolver-cache TTL window can advertise a `manifest_url` the router then 404s.

---

## 4. The soak results — the actual state of the product

Both reports and all raw evidence are committed at
**`docs/evidence/soak-2026-09-09-beta5/`** (see §7 for the file list). Read
`VERIFICATION-NOTE.md` there first: it re-derives every headline number from the raw logs and lists
three claims in the reports that do **not** hold.

### 4.1 The blocker — one mechanism, everything else follows

When a programme changes, the playout worker builds the new video leg, **waits for it to preroll**,
then disposes the old leg. A healthy commit is **146 elements** and always logs
`new leg stream held at its first buffer (N stream(s) still to preroll)` first.

**20 times in 8 h 21 m the reload skipped the wait.** It disposed the old leg first and committed a
half-built pipeline — **56 or 74 elements**. The worker then had nothing to play and shut down
**tidily**, reporting `error: None`.

That tidy exit is the second half of the bug. The daemon relaunches a worker that dies with an error
(it did so 29 times for ordinary stalls) but treats a **clean** exit as *"the operator turned this
channel off"*. **The one failure mode that produces a clean exit is the one with no recovery.**

Verified by direct count across the three `gst-worker.stdout.log` files:
**90 healthy `elements=146` commits, 20 undersized, 20 clean `error: None` exits, 67 worker exits
total.** Twenty and twenty — exact.

### 4.2 What that cost in one night (Blackwell, captions ON)

- **19 silent channel deaths. Zero self-recoveries.** Every one needed a human or a script.
- **Longest true outage 41 m 39 s** (Education, 23:21) — the only outage measured before the runner
  wrote a watchdog mid-soak. Everything after was capped at ~2 min by that watchdog, not by the
  product. Unattended, the station would have been dark by ~2 AM until morning.
- **218 of ~300 scheduled programme changes did not happen. Zero happened on time.**
- **117 UDP gaps over 5 s**, 18 of them over 100 s.
- **All 14 alerts nameless** — `default:off-air` with `title: None`, `detail: None`, no channel
  name — and ~90 s late.
- **Captions failed their own decode-back proof on all three channels** (zero cues in the emitted
  stream) while the operator screen showed the soft *"Not yet confirmed (waiting for the on-air
  check)"*. The check ran **once**, a minute after startup, and never again in 8 hours. Captions are
  an ADA obligation.
- **System Health read "Idle — no channels are configured for 24/7 automation" and "0 CRITICAL,
  0 WARNING"** while three channels ran and one was dead.
- `last_error` was **empty in all 300 samples**. The deaths are silent at the API surface.

### 4.3 The clean machine reproduced it with captions OFF

The clean report concluded "no verifiable worker feed" and did not name a mechanism. Its own
evidence shows the same bug: workers ran (buffers to **87,319**), each committed **`elements=33`**
and exited **`error: None`**, and was never relaunched. That is why the console advertised **PIDs
9628 and 9224 for processes that no longer existed** and why all three channels sat frozen for the
entire 8 hours — Public `FALLBACK_SLATE`, Government `TRANSITIONING`, Education `ON_AIR`, never one
state change. Stop was pressed and confirmed in the UI; the status endpoint still reported the old
states. It also showed **15 × "reload superseding a still-settling reload"**, which Blackwell did not.

**So: not captions-specific, not machine-specific.**

### 4.4 Three report claims that do not hold — do not act on these

1. **Dropped frames: withdraw.** The claimed peaks (312 / 876 / 731) appear nowhere. Every
   `dropped_frames` value in the evidence is `0`, and beta.5 reports 0 when no drop metric is
   emitted. Picture quality between failures is **unmeasured**, not proven bad.
2. **Caption overload: understated.** The report says 12 warnings; the real count is **182**,
   escalating to overload #10 with 900-second caption pauses, backlogs to 38 segments.
3. **"Automation stopped issuing reloads": too broad.** It issued **97** reloads evenly through to
   07:35. It fires only at `:00 :05 :10 :15 :20 :30 :35 :40 :45` and **never** `:25 :50 :55`. The
   00:50 gap is real. The correct statement is that automation **systematically skips about two
   thirds of scheduled boundaries**.

### 4.5 Evidence gaps — assume nothing beyond these

- The clean machine's `control_plane-app.log` covers **21:08 → 00:02:18**; its soak ran
  **00:05 → 08:04**. **The service-side view of that run is missing.**
- Both soaks used `udp://127.0.0.1` loopback. **No physical cable headend was exercised.**
- Blackwell's two large service logs were queried, not read line by line, during verification.

---

## 5. What has to be fixed, and what "done" means

Ordered by importance. Nothing below is started.

### F-1 — BLOCKER: seamless reload can commit a half-built pipeline

**Two halves, both required.**

- **(a)** The reload must **refuse to dispose the old leg until the new leg has prerolled**. Today
  it can reach `old leg disposed` with zero `new leg stream held at its first buffer` lines.
- **(b)** The daemon must treat *"the worker exited while this channel is supposed to be on air"* as
  a **fault regardless of exit code**. A clean exit while the desired state is on-air is not consent.

**Definition of done for F-1:**
- A test drives a reload where the new leg never prerolls, and asserts the old leg is **not**
  disposed and the commit does **not** happen — proven failing before the fix.
- A test asserts a worker exiting `error: None` while the desired state is on-air **is relaunched**
  — proven failing before the fix.
- A grep-style assertion (policy test) that no commit path can emit `committed (elements=N)` without
  a preceding preroll-hold line, so this cannot regress silently.
- `python -m pytest tests/egress tests/live -p no:randomly -q` green.
- **A ≥2-hour sandbox soak with zero `error: None` worker exits and zero undersized commits.**
  Grade from `gst-worker.stdout.log`: every `committed (elements=…)` must be the healthy count for
  that machine and must be preceded by preroll-hold lines.

### F-2 — BLOCKER: scheduled programme changes do not happen

Three contributing causes are visible in the logs and should be treated as separate work:

- **(a)** Source preparation runs **synchronously on the automation thread** — 35.0 s measured for
  one channel at the very first boundary, and 195 such warnings across the run. One slow prepare
  delays every channel's boundary.
- **(b)** The seamless reload path times out after 5 s (`ack timeout after 5.0s; falling back to
  restart`) and degrades to a full restart, which takes the channel off air.
- **(c)** Automation only fires at some boundary minutes and never at `:25 :50 :55` — about two
  thirds of boundaries never get a reload at all. Root-cause this; do not assume it is (a).

**Definition of done for F-2:** in a ≥2-hour soak with 5-minute boundaries, **≥95% of scheduled
boundaries change source within 30 s of the boundary**, measured the way the soak sampler measures
it (`current_source_label` against the wall-clock boundary), with the remaining ≤5% explained
individually. Plus a unit test that source preparation cannot block the automation loop.

### F-3 — BLOCKER: workers cannot stay alive

29 of 67 exits were the same `no output for 10 seconds, quitting for daemon restart` stall, on slate
as well as on real content, so it is not a property of the test media. Each relaunch takes the
channel off air 5–60 s.

**Definition of done:** a ≥2-hour soak with **zero** stall exits on a machine at <20% CPU, or a
documented, understood cause with a bounded mitigation.

### F-4 — BLOCKER: a channel death is invisible to the control plane

For one death the entire service log across four minutes contained a single line about that channel:
the `STOPPED` row. No reload, no warning, no error, no stop command. The reload that killed it had
been armed 12 minutes earlier as a deferred switch (`switch_at_end_of_current=True`) and logged
nothing when it fired.

**Definition of done:** every reload logs when it **fires**, not only when it is armed; every worker
exit logs its channel, exit reason and desired state; a death sets `last_error`. Assert with a test
that a deferred reload emits a fire-time log line.

### F-5 — MAJOR: captions fail their own proof and the UI understates it

`GET /api/staff/egress/channels/<id>/caption-status` returned `status: FAIL`,
`expected_cue_count: 0`, `decoded_cue_count: 0`,
`blocker: EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES` on all three channels, while the screen said
*"Not yet confirmed (waiting for the on-air check)"*. The check ran once and never re-ran.

**Definition of done:** (a) a hard `FAIL` renders as a **failure**, never as "not yet checked";
(b) the check re-runs on a stated cadence and the UI shows how stale the reading is; (c) the
underlying zero-cue defect is fixed or explicitly documented as a known issue with a dated owner.
This is legally load-bearing — do not ship a beta describing a caption FAIL as "not yet confirmed".

### F-6 — MAJOR: captions pause themselves under load

182 "Caption tap overload" warnings, escalating to 900-second pauses, backlogs to 38 segments. The
two largest backlogs each landed 5–6 s before a fatal undersized reload, so captions are a plausible
contributor to F-1's resource stall — but F-1 also reproduced with captions **OFF** on the clean
machine, so captions are **not** the sole trigger.

**Definition of done:** the reload path is tested with captions ON and OFF; the caption tap either
keeps up on three channels on reference hardware or degrades in a way the operator is told about.

### F-7 — MAJOR: the off-air alert is unusable

All 14 alerts were `default:off-air` with `title: None`, `detail: None`, no channel name, ~90 s late.

**Definition of done:** the alert names the channel and the reason, and fires within a stated bound.
Test it.

### F-8 — MAJOR: real media errors are absorbed silently

A worker died on `Internal data stream error … streaming stopped, reason error (-5)` reading a
source file, then `reload aborted: new program errored before commit`. None of it reached the
operator UI, the alerts feed, or `last_error`.

### F-9 — MAJOR: System Health is actively misleading

Read "Idle — no channels are configured for 24/7 automation" and "0 CRITICAL, 0 WARNING" while three
channels ran and one was dead. Readiness showed "Cable headend: NOT CONNECTED" for a channel that
was streaming and "CONNECTED" for one that was not — this was already wrong at minute one of the
soak (see `SOAK-evidence/readiness-start.txt`).

### F-10 — MAJOR: stop is not honoured / stale PIDs are advertised (clean machine)

Stop was issued and confirmed in the UI; the public status endpoint still reported
`FALLBACK_SLATE` / `TRANSITIONING` / `ON_AIR`, and the console advertised PIDs for processes that did
not exist.

**Definition of done:** the console never advertises a PID it has not verified exists; a confirmed
Stop is reflected by the status endpoint or the UI says it failed.

### F-11 — MINOR: memory climbs on every long-lived process

Control plane 469.7 → 573.0 MB in 8 h; supervisor `pythonservice.exe` 35.0 → 77.7 MB (more than
doubled with no work of its own); longest-lived worker 1126.5 MB. Not fatal in one night. A PEG
station runs for months between restarts.

### F-12 — MINOR: dropped-frame telemetry does not exist

beta.5 reports `0` when no supported GStreamer drop metric is emitted, so picture quality between
failures is **unmeasured**. Either emit a real metric or label the field honestly in the UI.

### F-13 — the schedule did not fully commit (clean machine)

Slots from 00:25 onward showed "Ready to review" rather than "Committed"; the intended nine-hour
schedule was never fully committed to air. Root-cause separately from F-2.

---

## 6. What testing has to happen before anything ships

The standing rule on this project (owner, binding 2026-09-06): **sandbox 15-minute soaks until it
always works, then a tester 2-hour soak, then publish, then 24-hour.** That was not enough to catch
F-1 — F-1's first death happened at 7 minutes, but the 15-minute sandbox soaks that preceded beta.5
did not grade for it. **Grade explicitly for the F-1 signature from now on.**

**Gate order for the next candidate:**

1. **Unit / policy gates green on main** — `pytest`, `mypy civiccast`, `ruff check .`,
   `ruff format --check .`, OpenAPI artifact check, both portals' lint + build + vitest, and the
   operator portal's `test:a11y` (light **and** dark axe scans).
2. **Sandbox soak, 15 min**, graded from `control_plane-app.log` and `gst-worker.stdout.log` for:
   zero `error: None` worker exits, zero undersized `committed (elements=…)`, zero
   `reload-commit-timeout`.
3. **Gate A full** (`gh workflow run gate-a-station-acceptance.yml --ref main -f run_id=<build run>
   -f lane=full`) — three lanes: clean install, cross-version upgrade, download-only.
4. **Tester soak ≥2 hours on real hardware**, captions ON and OFF, graded against the definitions of
   done in §5.
5. Only then publish.

**Nothing CPU- or I/O-heavy may run on the host during Gate A.** Two attempts failed at activation
after ~30 minutes from host load (a USB copy, then 27 hung `node --test` processes from another
project).

**Known CI facts:** `mutation-report` and `randomized-suite` are **informational**, not gating.
Everything else is required. `Unit tests` takes ~40 minutes.

---

## 7. Where everything is

### 7.1 On GitHub — a remote session needs nothing else

- **Repo:** `https://github.com/scottconverse/civiccast-native`
- **main:** `795cdab5`
- **Soak reports and full raw evidence:** `docs/evidence/soak-2026-09-09-beta5/`
  - `BLACKWELL-SOAK-REPORT.md` — the captions-ON report
  - `CLEAN-SOAK-REPORT.md` — the captions-OFF report
  - `BLACKWELL-SOAK-NOTEBOOK.md` — the runner's live notebook, findings S-01 … S-13 with raw
    excerpts as they were discovered
  - `BLACKWELL-interventions.log.md` — every death the watchdog saw and every restart it issued
  - `VERIFICATION-NOTE.md` — **read this**; independent re-derivation, and the three claims that do
    not hold
  - `blackwell-evidence.zip` (711 KB) — `SOAK-samples.csv` (300 rows), `SOAK-events.log`,
    `SOAK-udp.log`, `SOAK-raw.jsonl`, and `SOAK-evidence/` with `control_plane-app.log`,
    `control_plane.log`, `supervisor.log`, per-channel `gst-worker.{stdout,stderr}.log`,
    `readiness-start.txt`, and the three scripts used to run the soak
  - `clean-evidence.zip` (22 KB) — the clean machine's samples, events CSV, run state, worker logs
- **Release-state source of truth:** `docs/releases/release-truth.yaml` — human-facing release
  claims are checked **against** this file, never the reverse. Edit it first, then the prose.
- **Soak brief given to the testers:** `docs/SOAK-PROMPT.md`
- **Operational scripts** (were temp-only until now): `scripts/ops/`
  - `build-chain.sh` — the whole kit build chain (see §8)
  - `after-build.ps1` — kit-safe copy + verify + mirror
  - `sbsoak-launch.ps1` — sandbox soak launcher
  - `opus-changelog-resolve.py` — resolves the `[Unreleased]` CHANGELOG conflict every branch hits
- **Live handoff file:** `HANDOFF.md` at the repo root. **It is gitignored** (`.gitignore:146`) and
  must be committed with `git add -f`. It is on GitHub; it just will not stage normally.
- **Backup branches:** 20 branches that existed **only on this disk** were pushed on 2026-09-10 to
  `backup/2026-09-10/<original-branch-name>`. They range from 1 to 58 commits. They are unreviewed
  and unmerged — treat them as an archive, not as work in progress. Indexed in
  `docs/evidence/trackers/ARCHIVED-BRANCHES-2026-09-10.md`.
- **Uncommitted worktree edits:** three worktrees had uncommitted changes from earlier sessions.
  They are captured as patches in
  `docs/evidence/trackers/uncommitted-worktree-snapshots-2026-09-10/`. Those worktrees were **read,
  not touched** — no commit, no stash, no checkout — because committing another session's
  half-finished edits is how you destroy them.
- **Reviews:** every hostile review from the 09-09/10 work is a **PR comment** on #209, #214, #215
  and #216. They contain reproductions, measured numbers and file:line citations, and are the best
  record of why each fix looks the way it does.

### 7.2 On this machine

| What | Where |
|---|---|
| Main checkout | `C:\Users\scott\Desktop\Code\civiccast-native` |
| Worktrees | `C:\Users\scott\Desktop\Code\cc-*` (one per branch) and `civiccast-native\.claude\worktrees\*` |
| **beta.6 kit, verified** | `C:\CivicCastTester\kit-safe\795cdab5065e3b1b1d9df69c6fc06658f481c8d4\` |
| Same kit, staging + mirror | `C:\CivicCastTester\kit-staging\<sha>\`, `C:\CivicCastTester\kit-mirror\<sha>\` |
| Gate A runner | `C:\actions-runner-gate-a` — **not a service**; start `run.cmd` after every reboot |
| Gate A evidence | `C:\actions-runner-gate-a\_work\civiccast-native\civiccast-native\sandbox-lab\evidence\<sha>\` |
| Elevated helper queue | `C:\dev\ClaudeElevatedHelper\queue` — drop job JSON, then `Start-ScheduledTask ClaudeElevatedDevHelper` |
| Orphan-sandbox killer | `C:\dev\ClaudeElevatedHelper\kill-orphan-sandbox.ps1` |
| Kit LAN file server pid | `C:\CivicCastTester\kit-http-server.pid` — dies on reboot, see §8 |
| Original soak zips as delivered | `C:\Users\scott\Downloads\Blackwell-SOAK-2026-09-09-beta5.zip`, `clean-SOAK--.zip`, and the two `.docx` reports |
| Batch fix list (items 93–135) | `C:\Users\scott\Desktop\floatsom\CIVICCAST-BATCH-FIX-LIST-2026-09-03.md` |
| Append-only run log | `C:\Users\scott\Desktop\floatsom\CIVICCAST-RESUME-STATE.md` |
| Earlier walkthrough report | `C:\Users\scott\Desktop\9.9.26 civiccast TESTresults-20260910T041852Z-1-001.zip` (138 screenshots; already worked through — it produced items 102–135) |

**`Desktop\floatsom\` and `Desktop\CIVICCAST-EVIDENCE\` are outside git.** If this machine is lost,
those are lost. The soak evidence is now safe because it is in the repo; the fix list and run log
are not.

### 7.3 Machine state after the 2026-09-10 reboot

Verified at 10:50 AM:

- Kit intact — all 19 files match `SHA256SUMS.txt`; installer sha256
  `ac1429b9657b6654a1a5eff697dd2cd1b246b401e7a90012e48e399790e79f8e`
- Repo clean. Main was `795cdab5` at that moment; it is `6de69b8e` now — the difference is docs only.
- Elevated helper scheduled task: `Ready`
- **Dead and needing a restart:** the kit LAN file server on port 8766, the Gate A runner, and any
  monitors. A probe for Windows Sandbox processes found none.

---

## 8. The beta.6 pipeline — exact commands

**Do not run this until §5's blockers are fixed and §6's gates pass.** Recorded here because it is
the operational knowledge that is otherwise only in one session's head.

```bash
# 0. Restart the kit LAN file server if a reboot has happened (it is not a service):
#    Start-Process python -ArgumentList "-m","http.server","8766","--bind","0.0.0.0",
#      "--directory","C:\CivicCastTester\kit-safe" -WindowStyle Hidden -PassThru
#    then write the pid to C:\CivicCastTester\kit-http-server.pid

# 1. Build the kit (dispatch -> wait -> stage samples -> SHA256SUMS -> kit-safe -> LAN HEAD check)
bash scripts/ops/build-chain.sh <full main sha>
```

`build-chain.sh` exits non-zero at the failing step. **Exit 10 means the LAN HEAD checks failed** —
that is almost always the file server being dead after a reboot, not a bad kit. Restart it and
re-run just the HEAD-check loop.

```
# 2. A Gate A run auto-triggers as soon as the build succeeds. CANCEL IT.
#    It would run against an unsoaked kit and fight the kit staging for the host.
gh run cancel <that run id>

# 3. Clear any orphan sandbox VM via the elevated helper:
#    write {job_id, action: RunTrustedPowerShellScript,
#           scriptPath: C:/dev/ClaudeElevatedHelper/kill-orphan-sandbox.ps1}
#    into C:\dev\ClaudeElevatedHelper\queue, then:
#    Start-ScheduledTask ClaudeElevatedDevHelper

# 4. Sandbox soak (captions OFF is the default; seamless ON):
#    scripts/ops/sbsoak-launch.ps1 -Sha <sha> -Run c3s1 -Minutes 15 -Seamless
#    Grade the slate boundary from control_plane-app.log, and grade F-1 from
#    gst-worker.stdout.log (see §5 F-1 definition of done).

# 5. Gate A, full:
gh workflow run gate-a-station-acceptance.yml --ref main -f run_id=<build run id> -f lane=full

# 6. Publish:
python scripts/release/publish_beta_candidate.py \
  --kit-dir C:\CivicCastTester\kit-mirror\<sha> \
  --source-sha <sha> --build-run-id <id> --gate-a-run-id <id> \
  --tag v1.0.0-beta.6 --truth-status current
# then commit the release-truth change, flip the install surfaces, update HANDOFF.md
```

---

## 9. Traps that have already cost time

- **CHANGELOG `[Unreleased]` collides on every branch.** Each merge invalidates the next PR and
  costs a full CI round. Use `python scripts/ops/opus-changelog-resolve.py` from the worktree root:
  main's entries first, then the branch's, and it prints every bullet it kept.
- **A silent merge collision broke a test with no conflict.** #214 and #216 each added a
  module-level `_client_with_egress_store` in different places; git kept both and the later one
  shadowed the earlier, breaking two tests. `git merge` reported success. **After merging two PRs
  that touch the same test module, grep for duplicate top-level definitions.**
- **The global tools disagree with the locked ones.** This box's ruff is 0.16.4 and mypy 2.3.1; the
  repo pins ruff 0.15.12 and mypy 2.0.0. Global mypy reports 2440 errors in 376 files where the
  locked one is clean. **Always gate with `uv run --frozen`.**
- **Concurrent pytest runs across worktrees fight over shared state** —
  `%LOCALAPPDATA%\CivicCast\installer-state.json` and `managed-storage.json` — producing phantom
  teardown ERRORs in whichever run loses. Re-run any erroring test in isolation before believing it.
- **A subagent reporting `status: completed` is often still working**, waiting on a background
  command. Taking over its worktree once produced a false public claim on a PR that had to be
  corrected. Check the agent's own last line first.
- **Never `git stash` in this repo.** The stash stack is shared across every worktree and other
  sessions may pop it. Use a temporary WIP commit.
- **`HANDOFF.md` is gitignored** and needs `git add -f` every time.
- **main requires a PR**; merge with `gh pr merge N --squash --admin` on a MERGE verdict plus green
  required checks.

---

## 10. Standing rules from the owner

- No new features. Finish and test what exists.
- Commit after each task, not at the end. Update `HANDOFF.md` after each task. Stop at a clean state.
- Sort remaining work by importance and do the most important first.
- On a Gate A lane failure, do **not** stop for a decision — diagnose, fix, re-run until it passes.
- Bring only material decisions.
- Times in Mountain, 12-hour. Never UTC.
- Agents never merge. The coordinator merges.
- One agent per worktree.
- Hostile review per PR, delta rounds until `VERDICT: MERGE`; builders paste gate summary lines with
  the head SHA.
- **Never end a turn with work outstanding and nothing armed to wake you.** A drained work queue is
  exactly when a session goes idle. Arm a monitor with a timed heartbeat, or start the next step in
  the same turn.
- Never touch other repos, or the Codex worktrees under
  `C:\Users\scott\Documents\Codex\2026-09-01\is-this-tool-plugin-real-https\`.
- Never kill processes by image name — match PID plus command line.
- Never put passwords or recovery codes in files or chat.

---

## 11. If you are picking this up cold, do this

`HANDOFF-PROMPT.md` at the repo root carries a short paste-in prompt for a fresh session. It points
at this document rather than repeating it.


1. Read `docs/evidence/soak-2026-09-09-beta5/VERIFICATION-NOTE.md`.
2. Open `docs/evidence/soak-2026-09-09-beta5/blackwell-evidence.zip`, open any
   `SOAK-evidence/<channel>/gst-worker.stdout.log`, search for `elements=56`, and compare the four
   lines above it with the eight lines above any `elements=146`. That is the whole blocker in
   twelve lines.
3. Read §5 F-1 and F-2 here. Those two are the release.
4. Check `HANDOFF.md` for anything that happened after this document was written.
5. Do **not** publish the built beta.6 kit.

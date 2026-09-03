# DIRECTIVE 1 — soak72-9573d4a kickoff (full self-contained instructions, wiped-box safe)

Trigger: START NOW

This file is everything you need. Assume the machine you're on is a WIPED
Windows 11 box with nothing installed beyond the OS — no git, no python, no
wget, no GitHub CLI, no PowerShell 7. Everything below uses only:
built-in PowerShell 5.1 (`Invoke-WebRequest`, `Get-FileHash`, `curl.exe`
which ships with Windows 10/11), and `git` (installed in step 1.0). Do not
assume any other file on any other machine's disk is reachable from here —
this directive is the complete instruction set; nothing outside it or the
repo itself is required.

## Quick-start (read this first, then follow "Full instructions" below)

```
MISSION: soak72-9573d4a
CANDIDATE: kit-beta3-9573d4a (SHA 9573d4a82e1e1d9993589f633bad6dacba792afb)
KIT URL (LAN, HALO, port 8766 -- firewall confirmed OPEN):
  http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/
KIT CHECKSUM FILE (root of the kit, covers everything -- installer, packs,
  station, samples -- one line per file, "<sha256>  <relative/path>"):
  http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/SHA256SUMS.txt
SOAK DURATION: 48 hours total, one continuous run, with a REQUIRED interim
  checkpoint report at the 24-hour mark (not a stop -- keep running to 48h).
YOUR BRANCH (push only here, nobody else writes to it):
  tester/soak72-9573d4a-<YOUR-HOSTNAME>
DIRECTIVES BRANCH (read only, never push):
  soak72-9573d4a-directives
REPO: https://github.com/scottconverse/civiccast-native.git
ACK RULE: within 15 minutes of reading this directive, commit a short ack
  note to YOUR branch (tester/soak72-9573d4a-<HOSTNAME>) naming this
  directive file and what you're about to do, THEN start work. Never act on
  a directive without acknowledging it first via your own branch.
HEARTBEAT RULE: once running, push a heartbeat JSON to your branch every 30
  minutes, commit message exactly `test: soak heartbeat <UTC-stamp>
  soak72-9573d4a`, for the full 48 hours. Never skip one to catch up.
POLL RULE: re-check the directives branch every 15 minutes, forever --
  publishing your final verdict at T+48h ends this mission's data
  collection, not your polling duty.
```

You can start the git install and the kit fetch (sections 1.0 and 2 below)
in parallel — they don't depend on each other.

---

## Full instructions

You are the tester agent on this Windows machine for a CivicCast fleet soak.
Read this whole directive before doing anything. You drive every step
yourself — GUI included. Nobody is watching this machine and clicking along;
the owner cannot touch any machine until Friday morning
(2026-09-05 ~08:00 MDT). Every installer wizard screen, every UAC/consent
prompt, every first-run setup screen is something YOU click and type through
using your own computer-use tool (request access to the app first, take a
screenshot, then click/type from what the screenshot shows — repeat). Never
pause a step waiting for a human to click something. If a screen genuinely
cannot be resolved by you, that is a STALL — follow the stall rule near the
end, don't sit idle.

=== 1. Machine prep (assume the box is completely bare) ===

  0. Install git (a wiped box has none):
       winget install --id Git.Git -e --scope user
     Open a NEW shell after this (PATH only refreshes in a new process) and
     confirm:
       git --version
     Nothing else needs installing. Do not install Python, wget, GitHub
     CLI, or PowerShell 7 — everything in this directive works with git +
     built-in PowerShell 5.1 (`Invoke-WebRequest`, `curl.exe`,
     `Get-FileHash`).
  1. Confirm Windows 11, elevated PowerShell available, and that this box is
     not currently in use by another agent (check for a running civiccast
     installer process, gate-a/gate-b workflow runner process, or Windows
     Sandbox window before touching anything — if this box is shared with
     another automated tester, do not kill anything you did not start).
  2. Clone the directives branch — small and fast, this is where you'll
     re-read this file and any future directive:
       git clone --single-branch --branch soak72-9573d4a-directives https://github.com/scottconverse/civiccast-native.git C:\CivicCastSoak\directives
     Confirm the pointer resolves:
       git -C C:\CivicCastSoak\directives fetch origin soak72-9573d4a-directives
       git -C C:\CivicCastSoak\directives show origin/soak72-9573d4a-directives:LATEST-TEST-DIRECTIVE.md
     (This clone is intentionally narrow — it only ever needs this one
     branch, so a single-branch clone is correct here and is NOT the
     narrow-refspec bug described later; that bug is about a clone that
     ALSO needs other branches later failing to see them. Keep this
     distinction in mind if you re-read section "If the directive channel
     looks broken" below — that section's fix applies to the OTHER clone,
     `C:\CivicCastSoak\repo`, not this one.)
  3. Separately, clone the FULL repo — this is where the product scripts
     live (`sandbox-lab/soak-4h/...`, referenced in sections 4 and 6 below)
     and where you will create and push your OWN tester branch:
       git clone https://github.com/scottconverse/civiccast-native.git C:\CivicCastSoak\repo
     Create your branch now and push an immediate ack so the coordinator
     sees you're alive before anything else happens:
       git -C C:\CivicCastSoak\repo checkout -b tester/soak72-9573d4a-<YOUR-HOSTNAME>
       (create a short soak/ACK-1.md noting you read DIRECTIVE-1.md and are
        starting machine prep, with the exact UTC time)
       git -C C:\CivicCastSoak\repo add soak/ACK-1.md
       git -C C:\CivicCastSoak\repo commit -m "test: ack DIRECTIVE-1 soak72-9573d4a <UTC-stamp>"
       git -C C:\CivicCastSoak\repo push -u origin tester/soak72-9573d4a-<YOUR-HOSTNAME>
     Verify the push landed by resolving the remote branch (e.g.
     `git ls-remote origin tester/soak72-9573d4a-<YOUR-HOSTNAME>`) — if it
     doesn't resolve, retry the push before moving on. All further evidence
     in this directive (heartbeats, reports, verdict) goes to THIS branch,
     from THIS clone (`C:\CivicCastSoak\repo`).
  4. Fully uninstall/wipe any prior CivicCast install before starting (do not
     skip — a preserved old station database is a known cause of provision
     failures on this product):
     - Confirm no CivicCast service is registered (uninstall first if one is).
     - Confirm nothing answers on 127.0.0.1:8000.
     - Elevated delete: `C:\ProgramData\CivicCast`, `C:\CivicCastHostStore`,
       `C:\Program Files\CivicCast (Native)`, any `CivicCast*` scheduled
       tasks. Do NOT touch `C:\CivicCastSoak` (your own working dirs).
     - Verify every path is gone (Test-Path false) and commit
       `soak/CLEANUP.md` to YOUR branch recording what you deleted and the
       verification results.

=== 2. Fetch the candidate kit over the LAN from HALO — never GitHub for the kit ===

  HALO serves the kit at:
    http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/
  via a plain `python -m http.server 8766` in `C:\CivicCastTester\kit-staging`
  on that box. **Inbound TCP 8766 is OPEN on HALO's firewall (rule
  "CivicCast kit HTTP 8766") — this is confirmed, not a caveat.**

  `http.server` has NO recursive/mirror endpoint — it only serves plain HTML
  directory listings, so you have to walk them yourself. This PowerShell
  function does that with nothing but built-in `Invoke-WebRequest` (works on
  PowerShell 5.1, no modules needed) — paste it into your shell, then call
  it once:

    function Get-KitRecursive {
      param($BaseUrl, $RelPath = "", $DestRoot)
      $listing = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $RelPath)
      foreach ($link in $listing.Links) {
        $href = $link.href
        if (-not $href -or $href -eq "../" -or $href -eq "/") { continue }
        if ($href.EndsWith("/")) {
          New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot ($RelPath + $href)) | Out-Null
          Get-KitRecursive -BaseUrl $BaseUrl -RelPath ($RelPath + $href) -DestRoot $DestRoot
        } else {
          $destFile = Join-Path $DestRoot ($RelPath + $href)
          New-Item -ItemType Directory -Force -Path (Split-Path $destFile) | Out-Null
          Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $RelPath + $href) -OutFile $destFile
        }
      }
    }
    Get-KitRecursive -BaseUrl "http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/" -DestRoot "C:\CivicCastSoak\kit"

  That pulls everything at the kit root: the installer exe, `SHA256SUMS.txt`,
  `QUICKSTART-OPERATOR.md`, `packs\*.ccpack`, `station\*.ccpack` +
  `station\station-index.json` + `station\core-notice.txt` +
  `station\native-station-bundle-report.json`, and `samples\*.mp4` +
  `samples\SAMPLES-SHA256SUMS.txt`. The installer is named
  `CivicCast (Native)_1.0.0-beta.3_x64-setup.exe` — NOT `setup.exe`. If
  `Invoke-WebRequest` for any reason can't parse the listing on your box,
  fall back to `curl.exe -L -o <destfile> <url>` per file using the same
  file list (the kit root always has exactly: the installer exe,
  `SHA256SUMS.txt`, `QUICKSTART-OPERATOR.md`, and the three subfolders
  above — `curl.exe -s <kit-url>` alone will show you the raw listing HTML
  if you need to eyeball the exact filenames).

  Verify EVERY fetched file against the kit root's own `SHA256SUMS.txt`
  (format: `<sha256-lowercase>  <relative/path>`, forward slashes, one file
  per line, covering the installer + every pack + every station file +
  every sample — this is the canonical/complete manifest, generated fresh
  by the coordinator on HALO for this exact kit):

    Get-Content C:\CivicCastSoak\kit\SHA256SUMS.txt | ForEach-Object {
      $parts = $_ -split '  ', 2
      $expected = $parts[0]
      $relPath = $parts[1] -replace '/', '\'
      $actual = (Get-FileHash -Algorithm SHA256 (Join-Path C:\CivicCastSoak\kit $relPath)).Hash.ToLower()
      if ($actual -ne $expected) { "MISMATCH: $relPath expected=$expected actual=$actual" }
    }

  That should print nothing if everything matches. A hash mismatch is a hard
  stop — commit soak/KIT-HASH-MISMATCH.md with the expected vs actual hash
  and the exact file, and do not install. If port 8766 refuses the
  connection or times out despite the firewall rule above, commit
  soak/KIT-FETCH-BLOCKED.md with the exact error and STOP; do not try other
  ports or guess at a workaround — that would mean something changed on
  HALO's side since this directive was written, and the coordinator needs
  to know.

=== 3. Install + first run (you drive every screen with computer-use) ===

  1. Request access to the installer app with your computer-use tool before
     clicking anything.
  2. Run `C:\CivicCastSoak\kit\CivicCast (Native)_1.0.0-beta.3_x64-setup.exe`.
     Approve UAC yourself via computer-use — screenshot, locate the UAC
     dialog, click Yes. If a silent flag exists (check
     `C:\CivicCastSoak\kit\QUICKSTART-OPERATOR.md` for the current
     `/S /D=...` syntax) prefer it; otherwise drive the GUI wizard screen by
     screen with computer-use (screenshot -> click/type -> screenshot again).
  3. Wait for the installer to reach the dashboard/operator handoff. Open the
     nonce-bearing operator console URL from
     `C:\Users\<user>\AppData\Local\CivicCast\installer-state.json`
     (`http://127.0.0.1:8000/operator/?nonce=...`) and complete first-run /
     commissioning through computer-use the same way. Redact the nonce in
     anything you commit.
  4. Confirm `/api/health` returns 200 before proceeding.

=== 4. Configure the three soak channels with the REAL sample videos ===

  This soak exists to catch anomalies across concurrent video feeds with
  programs actually changing — not a synthetic color-bar loop. Use the four
  real videos you pulled into `C:\CivicCastSoak\kit\samples\`:
    - Help-Upgrade-the-LPM-Podcast-Studio, 1080p, 67s   (short, high-motion)
    - Help-Upgrade-the-LPM-Podcast-Studio, 360p, 67s    (short, low-res)
    - Longmont Weather Report, 360p, ~11 min
    - Serving Locally with Michelle, 1080p, ~39 min     (long-form)

  Configure THREE channels (public / education / government — reuse
  `sandbox-lab/soak-4h/channels.yaml` from `C:\CivicCastSoak\repo` as your
  starting encoder config, but replace its synthetic lavfi source with
  these four real files):
    - Each channel loops through all four videos.
    - Each channel switches to its next video on an independent schedule no
      coarser than every 20 minutes (this soak specifically wants to
      exercise a lot of program-change transitions over 48 hours, since
      that's where dropouts/back-sync/audio bugs show up). Stagger the three
      channels' switch times so they are NOT all changing at the same moment
      (e.g. offset public/education/government by ~7 minutes from each
      other) — simultaneous switches would under-test the scheduler/mixer's
      handling of independent, overlapping transitions.
    - Record the exact schedule (which video, which channel, what time,
      what offset) in `soak/CHANNEL-SCHEDULE.md` on your branch BEFORE
      starting the clock.

=== 5. Start the soak clock ===

  Start all three encoders/channels. Note the exact UTC start time — the
  soak clock begins at your FIRST post-install heartbeat, not at install
  completion.

=== 6. Heartbeat loop — every 30 minutes for the full 48 hours ===

  Reuse `sandbox-lab/soak-4h/scripts/heartbeat.ps1` and
  `sandbox-lab/soak-4h/scripts/verify-egress.ps1` from `C:\CivicCastSoak\repo`
  unmodified (they are engine-agnostic). Every heartbeat must:
    1. Sample process RSS for uvicorn/ffmpeg/python (leak check — flag any
       process whose RSS grew >15% from its first heartbeat).
    2. Probe /api/health for HTTP 200, keep the body.
    3. Run verify-egress.ps1 for a bounded TSDuck capture on all three UDP
       MPEG-TS sinks. PASS requires invalid syncs = 0, transport errors = 0,
       continuity discontinuities = 0 on every channel, every heartbeat. If
       TSDuck is unavailable, record "not-run" — never fake a pass.
    4. Check specifically for what this soak is looking for:
       stutter/dropped frames, audio drop/desync, A/V sync drift, caption
       drift. Confirm the channel that should be on-air per your
       CHANNEL-SCHEDULE.md actually is (no channel silently reverted to a
       prior video), and that audio and video timestamps on the TS capture
       are not drifting apart. Note CPU/mem/disk trend and any service
       restart or 5xx response.
    5. Write the heartbeat JSON locally AND commit + push it to
       `tester/soak72-9573d4a-<HOSTNAME>` (from `C:\CivicCastSoak\repo`)
       with EXACTLY this commit message convention (load-bearing — parsed
       literally by the coordinator's stall-watch):
         test: soak heartbeat <UTC-stamp> soak72-9573d4a
       Verify the remote branch resolves to your pushed commit before
       considering the heartbeat done — if it doesn't, retry the push.
     6 heartbeats/hour (30-min cadence) is intentional — a prior soak FAILED
     the whole run over exactly one gap slightly over 25 minutes. Do not
     skip a heartbeat to save time; if a heartbeat step is going to run
     long, start the next one's clock from when this one WOULD have fired,
     not from when it actually finished, and record the delay.

=== 6b. 4-hour rollup report (owner-required, separate from the 30-min heartbeats) ===

  Every 4 hours, in addition to the 30-min heartbeat JSONs, commit and push
  to YOUR branch a human-readable rollup:
    soak/SOAK-REPORT-<HOSTNAME>-<UTC-date-and-hour>.md
  covering the prior 4 hours: any stutter/dropped-frame/audio/sync/caption
  anomaly observed (even minor or ambiguous ones — note them, don't discard
  as noise), the CPU/mem/disk trend, any restart, any egress/TS failure, and
  which channel-schedule switches happened on time vs late/missed. Attach or
  reference the relevant heartbeat/egress JSON files for that window. Also
  push whatever raw logs (installer log, service logs, ffmpeg stderr
  captures) are relevant to any anomaly you flagged that window — don't make
  the coordinator ask for them later.

  At the 24-HOUR mark specifically (in addition to that hour's normal 4-hour
  rollup) — which is also roughly the halfway point of this 48h run — commit
  an extra checkpoint file `soak/CHECKPOINT-24H.md` summarizing the full
  first day: total heartbeats, any anomalies across all 24h, whether you'd
  call the first 24h clean or not, and confirmation you are continuing on to
  the full 48h. This is a checkpoint, not a stop — keep running past it.
  This checkpoint is REQUIRED: the owner leaves Friday morning
  (2026-09-05 ~08:00 MDT) and needs a readable status before then even if
  the full 48h run hasn't finished by the time they check.

=== 7. Directive polling — every 15 minutes, concurrently with the heartbeat loop ===

  Every 15 minutes, from `C:\CivicCastSoak\directives`:
    git -C C:\CivicCastSoak\directives fetch origin soak72-9573d4a-directives
    git -C C:\CivicCastSoak\directives show origin/soak72-9573d4a-directives:LATEST-TEST-DIRECTIVE.md
  Read whatever directive it currently points to. If it's new (not the one
  you last acted on), you must ACKNOWLEDGE it within one more poll cycle (15
  min) by committing a short ack note (from `C:\CivicCastSoak\repo`) to your
  own branch naming the directive file and what you're about to do about it,
  THEN act on it. Never act on a directive without acknowledging it first
  via your own branch. Only ever READ the directives branch/clone — never
  push to it, never write to any other tester's branch.
  Every directive you act on will carry a line reading exactly:
    Trigger: START NOW
  A directive without that exact line is informational only — do not start
  or restart the soak clock because of it.
  **Keep polling forever.** Publishing your final verdict at T+48h ends the
  mission's data collection, not your polling duty — the fleet serves other
  missions from the same machine. Do not disable or delete your polling loop
  "because the soak is done." Only Scott ends polling.

=== 8. Crash-recovery test (do this once, at roughly the halfway point, ~T+24h) ===

  1. Confirm you're mid-broadcast (channels on-air, health 200) and commit
     soak/PRE-CRASH-STATE.md with the current heartbeat index and a fresh
     verify-egress.ps1 pass on all three channels.
  2. Trigger an unattended, unclean stop: prefer a real hard power cut if
     this is a physical box you can safely re-power without anyone present
     (document that you did this); if that's not safely available on this
     box, use `Stop-Computer -Force` as the documented substitute and record
     which one you used.
  3. The box must come back up and recover ON ITS OWN — no human, no agent
     re-driving the GUI. That means: CivicCast's supervisor service starts
     itself, all three channels return to air, and no data was lost (the
     capture files show no discontinuity in the RECOVERED portion; the gap
     during the actual outage is expected and does not count against you).
  4. Time the recovery from power-back-on to health-200-and-all-three-
     channels-on-air. Commit soak/REBOOT-RESULT.md with: which stop method
     you used, exact timestamps, recovery duration, whether recovery was
     fully unattended, and a post-recovery verify-egress.ps1 pass on all
     three channels.
  5. Resume the normal 30-min heartbeat loop immediately after recovery is
     confirmed. A reboot gap in the heartbeat log is expected and is not a
     "missed heartbeat" as long as it's the single one you planned and
     documented — an unplanned second gap anywhere else in the run is a
     genuine finding, not something to explain away.
  If your CHECKPOINT-24H.md work and this crash-recovery test land close
  together in time, that's fine — do the crash-recovery test first if
  they'd otherwise overlap, then write CHECKPOINT-24H.md covering the
  recovered state.

=== 9. Evidence to commit (all to YOUR branch, tester/soak72-9573d4a-<HOSTNAME>, from C:\CivicCastSoak\repo) ===

  - soak/ACK-1.md (immediate, from step 1.3), soak/CLEANUP.md,
    soak/CHANNEL-SCHEDULE.md, soak/PRE-CRASH-STATE.md, soak/REBOOT-RESULT.md
  - One heartbeat JSON per 30-min interval for the full 48h run
  - egress-verify-<timestamp>.json per heartbeat (from verify-egress.ps1)
  - soak/SOAK-REPORT-<HOSTNAME>-<date-hour>.md every 4 hours
  - soak/CHECKPOINT-24H.md at the 24h mark (required)
  - Any ack notes from directive polling
  - The final verdict (next section)

=== 10. Stall / abort rules ===

  - If you cannot resolve a blocking GUI state yourself after real attempts
    with computer-use (not a single failed click — actually try alternate
    approaches), commit soak/STALLED.md naming the exact blocker, the last
    good heartbeat index, and STOP the soak clock. Do not silently keep
    "waiting." A stall is a reportable finding, not a private problem.
  - If you miss two consecutive heartbeats (>55 min of silence) for any
    reason, that is an automatic FAIL condition for this run — commit
    soak/STALLED.md immediately once you're able to write anything, with
    the reason if known.
  - If the directives branch itself becomes unreadable mid-run (see next
    section), do NOT stop the soak — keep heartbeating and keep the channels
    running. Only directive intake stops; the soak itself continues on the
    last confirmed directive.

=== If the directive channel looks broken ===

  This applies to `C:\CivicCastSoak\repo` (the full clone) if you ever try
  to fetch the directives branch or any other branch from it and it fails —
  it does NOT apply to `C:\CivicCastSoak\directives`, whose single-branch
  scope is deliberate (see step 1.2).

  If a fetch of `soak72-9573d4a-directives` or the `git show` of
  LATEST-TEST-DIRECTIVE.md fails ("invalid object name", "couldn't find
  remote ref", or similar) even after a retry a few minutes later:
    1. Do NOT guess an alternate branch name or an alternate directive
       number.
    2. Commit soak/CHANNEL-BROKEN.md to YOUR OWN branch with the exact
       commands you ran and their exact combined output (copy-paste, not a
       paraphrase).
    3. Keep the soak itself running and keep heartbeating on schedule —
       only directive intake is blocked, not the mission.
    4. This has happened before on a prior soak — it is very likely the
       clone's local git remote fetch refspec only tracks specific branches
       (a narrow/single-branch clone) rather than all of origin's branches,
       so a brand-new directives branch never gets a local remote-tracking
       ref no matter how many times you `fetch origin`. Try explicitly:
         git -C C:\CivicCastSoak\repo config --get-all remote.origin.fetch
       If it does not show `+refs/heads/*:refs/remotes/origin/*`, add it:
         git -C C:\CivicCastSoak\repo config --add remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
       then retry the fetch. Record whether this fixed it in
       soak/CHANNEL-BROKEN.md either way. If it's `C:\CivicCastSoak\directives`
       that's failing instead (the single-branch clone), just re-clone it —
       it's small and fast and carries no state you'd lose.

=== 11. Final verdict format (at T+48h, or at STALL/abort) ===

  Commit soak/final-verdict.json to your branch:

    {
      "schema": "civiccast-native-fleet-soak-v1",
      "mission": "soak72-9573d4a",
      "candidate": "9573d4a82e1e1d9993589f633bad6dacba792afb",
      "candidate_label": "kit-beta3-9573d4a",
      "hostname": "<HOSTNAME>",
      "planned_hours": 48,
      "start_utc": "...",
      "completed_utc": "...",
      "installer_exit_code": 0,
      "heartbeat_count": <N>,
      "heartbeat_gaps_over_25_minutes_excluding_the_one_planned_reboot": [...],
      "egress_failures": [...list any heartbeat where any channel failed TSDuck verify...],
      "channel_schedule_violations": [...any case a channel was not showing the scheduled video...],
      "stutter_or_dropout_events": [...],
      "audio_desync_events": [...],
      "caption_drift_events": [...],
      "crash_recovery": {
        "method": "hard-power-cut | Stop-Computer -Force",
        "unattended": true/false,
        "recovery_minutes": <n>,
        "data_loss": false
      },
      "verdict": "PASS | FAIL",
      "reasons": ["..."]
    }

  Honest failures over silent success, always. A FAIL with clear evidence is
  a successful soak run; a PASS with skipped checks is not. **This soak does
  NOT need a finished/green installer or an installed-product FAIL/PASS on
  every other CivicCast feature** — the only thing being judged is whether
  the station stays up and clean across three concurrent, changing video
  feeds for 48 hours. A clean install that then runs stably is enough scope;
  do not go hunting for or reporting unrelated product bugs outside what the
  heartbeat/egress checks above are built to catch (note them briefly if you
  trip over something serious, but the verdict is scoped to the soak itself).

## Any tool this directive cannot get you

You need internet access to `github.com` (for the two clones) and LAN access
to `192.168.0.135:8766` (for the kit). Beyond that, `winget install
--id Git.Git -e --scope user` is the only install this directive performs
for you — it assumes `winget` itself is present, which every current-image
Windows 11 box ships with by default. If `winget` is missing or blocked on
this specific box, that's a STALL per section 10 above: commit
soak/STALLED.md naming exactly that, don't try to sideload git another way
without recording what you did.

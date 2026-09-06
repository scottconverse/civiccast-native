# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# RestartClassifier.ps1 -- dot-sourceable planned/unplanned worker-restart
# classification for the sandbox soak lane, extracted from
# In-Sandbox-Soak.ps1 into its own file (matching SoakVerdict.ps1 /
# HostLiveness.ps1's pattern) so it is unit-testable with synthetic data
# (Test-RestartClassifier.ps1) without a live sandbox or station.
#
# THE BUG THIS EXTRACTION EXISTS FOR (round-8 finding 1, BLOCKER): the
# inline version's ring-sample function had a parameter named `$Pid`. $PID
# is a READ-ONLY AUTOMATIC VARIABLE in PowerShell (the current process
# id) -- PowerShell variable names are case-insensitive, so `$Pid` IS
# `$PID` to the parameter binder, and binding any value to it throws
# "Cannot overwrite variable Pid because it is read-only or constant"
# (confirmed directly: VariableNotWritable, SessionStateUnauthorized-
# AccessException) on EVERY call. With $ErrorActionPreference='Continue'
# at script scope, that error goes to the error stream and the call
# silently no-ops: the function body never runs, the ring is never
# populated, and nothing downstream ever finds out (confirmed directly:
# the script does not crash, it just silently never records a single ring
# sample). That is exactly why run 7's cycle JSON showed "sample_ring":
# [null] and Test-TransitioningInWindow always returned $false, so every
# pid change -- including a genuinely planned restart -- was misclassified
# unplanned_relaunch. This file uses $ProcessId throughout, and ships with
# a real unit test that calls it, so this exact class of error (an
# automatic-variable name shadowed by a parameter, silently swallowed by a
# non-strict error preference) fails a unit check the moment it recurs.
#
# STATE MODEL: every function here takes a $Context object (from
# New-RestartClassifierContext) instead of relying on ambient script-scope
# variables. This is what makes the whole thing testable in isolation --
# a test builds a fresh context, feeds it synthetic samples, and asserts
# on its Ring/PendingRestarts/RestartEvents afterward, with no dependency
# on the real driver's global state.
#
# SAMPLING CADENCE (round-8 finding 2, BLOCKER): a single state-plus-tsp
# "heavy cycle" (3 channels x up to a 40s-bounded 20s tsp probe each) can
# take 60-75+ seconds end to end, and the previous single-timer poll loop
# scheduled its NEXT heavy cycle at +60s from the PREVIOUS one's start --
# so once a cycle ran even slightly over 60s, the "light 15s sample"
# branch became mathematically unreachable (the heavy-cycle condition was
# already true again the moment the loop looped back around). Fixed by
# INTERLEAVING a full all-channel state sample before each of the three
# per-channel tsp probes inside a heavy cycle (one of the two fixes this
# review explicitly authorized, the other being a separate background
# sampler process) -- see In-Sandbox-Soak.ps1's poll loop. That gives
# ~3 ring samples spaced roughly by each channel's own tsp duration
# (~20-25s apart) across the ~60-75s heavy-cycle period, which is what
# makes a TRANSITIONING state shorter than the ~75s worst-case cycle
# period actually visible in the ring -- not a literal independent 15s
# timer (the README no longer claims one; see round-8 finding 9).
#
# EXEMPTION WINDOW (round-8 finding 3, BLOCKER): a fixed 60s "is this
# channel still inside its planned-restart grace window" exemption is
# shorter than the real ~75s heavy-cycle period, so a CORRECTLY classified
# planned restart could still get flagged as "not ON_AIR" by the very next
# per-cycle check before its own 60s recovery clock (measured against the
# PASS bound, which is a real product requirement and stays 60s) had even
# been evaluated once. Test-InActivePlannedRestartWindow now takes the
# actual measured cycle period and uses max(60s, 2x that period) as the
# EXEMPTION window (how long a channel is excused from the ON_AIR check
# while a restart is in flight) -- deliberately a SEPARATE number from the
# 60s PASS bound (how long a restart is ALLOWED to take before the run
# fails), which Get-SoakVerdict / SoakVerdict.ps1 still enforces unchanged.
#
# ROUND-10 finding 1 (HIGH): Test-PlannedRestartSignal's "immediately
# preceding" adjacency check used a HARDCODED -MaxGapSeconds 30 against a
# REAL sample spacing that runs ~20-25s under a fast cycle but is not
# guaranteed to stay under 30s (a slightly slower cycle pass, e.g. tsp
# taking a touch longer, puts the same genuinely-planned TRANSITIONING ->
# pid-change gap at 31s+ -- measured misclassified unplanned). Register-
# ChannelSample now computes the gap as max(60s, 2x the measured
# per-sample interval) -- the SAME max(60, 2x) shape
# Test-InActivePlannedRestartWindow already uses for its own exemption
# window, just applied to the adjacency check instead. Also: a dropped/
# failed state read (In-Sandbox-Soak.ps1's Get-ChannelStateSample returning
# ok=$false, recorded into the ring with state=$null and a last_error that
# STARTS WITH the literal "state read failed" -- that exact prefix is the
# contract between the two files, see Get-ChannelStateSample) is a HARNESS
# artifact, not a real sample of the channel's own state -- it must not
# break the "immediately preceding sample" chain (walking back must skip
# over it, not treat its absence-of-state as "not TRANSITIONING" and fail
# closed) NOR trip the crash-signal veto (its last_error text is about the
# HTTP read, never the product's own last_error field).
#
# ROUND-10 finding 5 (MEDIUM, "the important one"): sample-based
# classification (Test-PlannedRestartSignal, above) can only see WHATEVER
# STATE HAPPENED TO BE TRUE at each poll's exact instant -- a crash that
# begins and fully resolves inside one ~20-25s poll gap (worker crashes,
# daemon relaunches it, new pid reaches ON_AIR, all between two samples)
# is invisible to polling and would misclassify as planned if the LAST
# thing polling saw was TRANSITIONING. The daemon's own app log
# (control_plane-app.log) is a strictly better signal because it is
# written at EVERY state transition the daemon itself makes, not just
# whichever instant this lane happens to poll -- civiccast/egress/
# daemon.py:1064-1071 (`_write_state`, main bcb3ebe -- line citations in
# this file are pinned to that revision, re-verify against HEAD before
# trusting them blindly) is the ONE choke point every transition passes
# through, logged as:
#   "channel {id}: egress state -> {STATE} (source={label}, pid={pid}, last_error={err})"
# `last_error` is the literal text "-" when there is none. A PLANNED
# rollover (_poll_process's pending_reload branch, daemon.py:1399-1409)
# writes its STARTING line with NO last_error at all -- literal "-". A
# CRASH relaunch (_relaunch_after_crash -> _begin_relaunch, daemon.py:
# 1546-1554) writes ITS STARTING line with last_error set from
# _child_exit_error (daemon.py:1183-1188, always contains the literal
# substring "child exited non-zero") or, past the escalation streak
# threshold, _begin_relaunch's own force-fallback text (contains
# "crash-relaunches", daemon.py:1540-1543).
#
# ROUND-11 finding 1 (BLOCKER, the round-10 version of this function was
# STILL wrong): scanning the ring BACKWARD and stopping at the FIRST
# TRANSITIONING line is not sufficient -- daemon.py's own crash path
# ALSO produces a clean TRANSITIONING line, later in the same sequence,
# because `_begin_relaunch` writes its crash-flavored STARTING line
# (last_error containing "child exited non-zero") and THEN calls
# `_start()`, which unconditionally writes its OWN clean STARTING, then a
# clean TRANSITIONING (whenever the previous state was ON_AIR/FALLBACK_
# SLATE -- true for a crash restarting from ON_AIR) BEFORE the real pid is
# even bound, and finally the clean running-state write. Scanning backward
# and stopping at that clean TRANSITIONING reads EVERY crash-then-
# successful-relaunch exactly like a planned rollover.
#
# ROUND-12 finding 1 (BLOCKER, the round-11 window was STILL wrong):
# anchoring the window on "the last ON_AIR" breaks the moment `_start`
# writes the running state TWICE for the SAME rollover -- once at
# daemon.py:860-866 with pid=None (before the encoder has even launched),
# and again at daemon.py:992-999 with the REAL new pid (once the encoder
# is confirmed up). "Last ON_AIR strictly before the final entry" then
# lands on the pid=None ON_AIR, leaving a one-line "window" (just the
# final real-pid ON_AIR) with no STARTING in it -- $null, falls back to
# the sample-ring signal, and a genuine crash-loop can classify planned
# with log_evidence='missing'. Anchoring on STATE (ON_AIR) is fundamentally
# the wrong axis when the daemon can log the SAME state twice with
# different pids, or never reach ON_AIR at all for a FALLBACK_SLATE-stable
# channel.
#
# CORRECT RULE (anchor on PID, not state -- every `_write_state` line
# carries its own `pid=<n>` or `pid=-`): the WINDOW is every log line for
# this channel from the LAST line whose pid == the OLD pid (in ANY state --
# this is the old worker's own last-known-good report, whatever state it
# was in, which correctly handles a channel that was stably parked on
# FALLBACK_SLATE the whole time) through the FIRST subsequent ON_AIR line
# whose pid == the NEW pid, inclusive of every line in between regardless
# of what pid THEY carry (pid=- transient lines, or another worker's
# unrelated activity). UNPLANNED if ANY line in that window (excluding the
# anchor line itself -- see below) carries a non-"-" last_error or an
# ERROR/FALLBACK_SLATE state. PLANNED only if the window contains a
# STARTING line and everything strictly after the anchor is clean. The
# anchor line's OWN state/last_error is deliberately NOT itself evidence --
# only what happens AFTER it is (a channel legitimately, stably parked on
# FALLBACK_SLATE is not itself a crash; only a NEW FALLBACK_SLATE/ERROR
# appearing during the actual transition is). If the OLD pid never appears
# anywhere in the retained ring at all (expired past the 10-minute age
# limit, or simply never logged), this returns $null (no evidence) --
# Register-ChannelSample falls back to the sample-ring signal and marks
# log_evidence='missing'.

function New-RestartClassifierContext {
    <#
      .SYNOPSIS
      A fresh, isolated state container for one soak run (or one unit
      test). Never share a context across two independent runs/tests.
    #>
    param([int]$RestartTrackingMaxSeconds = 300)
    return [pscustomobject]@{
        Ring = @{}
        LogRing = @{}
        PendingRestarts = @{}
        LastPidForChannel = @{}
        RestartEvents = New-Object System.Collections.ArrayList
        # Round-11 finding 4: seamless content-reload aborts (a distinct
        # WARNING-line event class, never a _write_state line -- see
        # Add-ReloadAbortSample).
        ReloadAbortEvents = New-Object System.Collections.ArrayList
        RestartTrackingMaxSeconds = $RestartTrackingMaxSeconds
    }
}

function Add-LogRingSample {
    <#
      .SYNOPSIS
      Round-10 finding 5: append one PARSED daemon-log state-transition
      line for one channel (see this file's header for the exact log
      shape/citations). Deliberately separate from Add-RingSample's
      poll-sample ring -- log lines and poll samples arrive on independent
      cadences (a transition logs once, the moment it happens; polling
      only sees whatever was true at its next scheduled instant) and
      neither should be conflated with the other's history.

      .PARAMETER LastError
      The raw captured `last_error=...` text from the log line -- compare
      against the literal "-" sentinel (daemon.py's own "no error" marker),
      never against $null/empty (this is parsed log TEXT, not a
      PowerShell-native value).

      .PARAMETER LogPid
      Round-12 finding 1 (BLOCKER): the raw captured `pid=...` text from
      the log line -- "-" (daemon.py's own sentinel for pid=None) or a
      decimal pid string. Deliberately NOT named `$Pid` -- see this file's
      header on the $Pid/$PID automatic-variable-shadowing bug that this
      whole extraction exists to fail loudly on. Compare via string
      equality against a real pid's `"$RealPid"`, never parse as [int] (a
      "-" would throw). This is what Test-PlannedRestartFromLog anchors
      its window on instead of ON_AIR state -- see this file's header.

      .PARAMETER ObservedUtc
      Round-11 finding 2 (HIGH): THIS SCRIPT's own clock at the moment the
      line was read/parsed -- never the log's own %(asctime)s text (see
      this file's header on Test-PlannedRestartFromLog for why that is
      deliberately never parsed: local-time, would need a timezone
      reconciliation against this script's UTC clock not worth risking).
      Used ONLY to age-expire ring entries (10 minutes) so a channel that
      goes quiet for a long stretch does not carry an ancient, no-longer-
      relevant TRANSITIONING/ON_AIR line forward into a much later
      classification. Defaults to "now" so existing callers/tests that
      never pass it keep working unchanged.

      .PARAMETER MaxRingSize
      Round-13 finding 5 (HIGH): a FIXED 30-line cap holds only ~60s of
      real daemon traffic -- `_poll_process` logs one state line PER
      CHANNEL on every ~2s automation tick, UNCONDITIONALLY, even when
      nothing changed (a channel sitting healthy on ON_AIR still writes a
      fresh "egress state -> ON_AIR" line every tick). Update-DaemonLogRing
      is only called once per interleaved PASS (every ~20-25s, 3 passes
      per heavy cycle), so between calls dozens of these routine lines can
      accumulate and get pushed through a 30-line cap all at once -- easily
      evicting the OLD pid's own anchor line before its matching NEW pid's
      ON_AIR ever shows up, especially once the measured cycle period runs
      well past the ~60-75s baseline (a slow install/schedule phase, or a
      station under load). The caller (In-Sandbox-Soak.ps1) now sizes this
      from the measured cycle period: ceil(period_s/2)*2 + 30, floored at
      60 -- enough capacity for one full period's worth of ~2s-tick lines
      PLUS the original 30-line safety margin. Default 30 preserves
      existing callers'/tests' behavior unchanged when not specified.
    #>
    param($Context, [string]$ChannelId, [string]$State, [string]$LastError, [string]$LogPid = '-', [datetime]$ObservedUtc = (Get-Date).ToUniversalTime(), [int]$MaxRingSize = 30)
    if (-not $Context.LogRing.ContainsKey($ChannelId)) { $Context.LogRing[$ChannelId] = New-Object System.Collections.ArrayList }
    $null = $Context.LogRing[$ChannelId].Add([ordered]@{ state = $State; last_error = $LastError; pid = $LogPid; observed_utc = $ObservedUtc })
    while ($Context.LogRing[$ChannelId].Count -gt $MaxRingSize) { $Context.LogRing[$ChannelId].RemoveAt(0) }
    # Age expiry: drop entries older than 10 minutes relative to THIS
    # sample's own observation time (monotonic with the ring's append
    # order, since entries are always added in real-time order).
    $cutoff = $ObservedUtc.AddMinutes(-10)
    while ($Context.LogRing[$ChannelId].Count -gt 0 -and $Context.LogRing[$ChannelId][0].observed_utc -lt $cutoff) {
        $Context.LogRing[$ChannelId].RemoveAt(0)
    }
}

function Add-ReloadAbortSample {
    <#
      .SYNOPSIS
      Round-11 finding 4 (MEDIUM) / round-12 finding 3 (HIGH, two more
      variants found) / round-13 finding 3 (a SEVENTH matching line found,
      excluded rather than counted -- see below): a seamless content-
      reload abort is invisible to everything above -- it is NOT a
      `_write_state` line at all, it is one of SIX distinct daemon.py
      WARNING-level MESSAGE TEMPLATES (main bcb3ebe:1946 "declined", :2111
      "falling back to restart instead of stamping ON_AIR" (a worker
      exited before an "applied" settlement could be committed), :2132
      "did not land", :2143 "...treating as aborted and falling back to
      restart", :2156 "no settlement within", and :1860 "Content-reload
      source preparation FAILED..." -- no "Seamless" prefix at all) that
      all contain the substring "falling back to restart" somewhere in the
      line. A channel that hits any of these DID fall back to a real
      worker restart -- exactly what -SeamlessReload exists to prove never
      happens -- so this needs its own event class, never silently folded
      into (or missed by) the planned/unplanned restart classification
      above.

      A SEVENTH line also matches the same substring test: every one of
      the six WARNING lines is immediately followed by a separate INFO-
      level echo from `_discard_pending_reload_settlement` (daemon.py:
      1732-1738, "Content-reload for %s (reload_id=%s) discarded: %s."),
      because the shared `_fall_back_to_restart_reload` path (daemon.py:
      2180-2191) that ALL SIX aborts fall through to always discards with
      `reason="falling back to restart"` -- so this echo line ALSO reads
      "...discarded: falling back to restart." for every real abort. This
      is not a seventh independent event, just a mechanical restatement of
      the SAME abort -- In-Sandbox-Soak.ps1's parsing excludes it (by its
      unique literal "discarded:" text) so one real abort is recorded
      once, not twice. See In-Sandbox-Soak.ps1's $script:daemonReloadAbortRegex
      for the actual parsing and exclusion.
    #>
    param($Context, [string]$ChannelId, [string]$Reason)
    $null = $Context.ReloadAbortEvents.Add([ordered]@{ channel_id = $ChannelId; reason = $Reason })
}

function Test-PlannedRestartFromLog {
    <#
      .SYNOPSIS
      Round-10 finding 5 (MEDIUM, "the important one") / round-11 finding 1
      / round-12 finding 1 (both BLOCKER, this function's earlier forms
      were STILL wrong): classify a pid change from the daemon's OWN log
      lines for this channel, when any are available, instead of (or in
      addition to) inferring it from polled state -- see this file's
      header for the full citation of why this catches a crash-and-recover
      that happened entirely inside one poll gap, which polling alone
      cannot, and for the two prior anchoring mistakes this fixes (round-
      10's "stop at first TRANSITIONING scanning backward", round-11's
      "anchor on the second-to-last ON_AIR" -- both broke on real daemon
      behavior `_start` actually exhibits).

      WINDOW definition (round-12): anchor on PID, not state. The window
      is every log line for this channel from the LAST line whose pid ==
      $OldPid (in ANY state -- the old worker's own last-known-good
      report) through the FIRST subsequent line whose state == 'ON_AIR'
      AND pid == $NewPid, inclusive of everything in between regardless of
      what pid THOSE lines carry (transient pid=- lines are normal and
      expected mid-transition). No timestamp comparison is used or needed
      -- log lines arrive in the file's own append order, and this
      deliberately does NOT parse/compare the log's own %(asctime)s text
      (local-time, would need a timezone reconciliation against this
      script's UTC clock not worth risking).

      The anchor line's own STATE is NOT itself treated as crash evidence
      (round-13 finding 2, narrowed from round-12's original "state/
      last_error both excluded") -- only a NEW ERROR/FALLBACK_SLATE state
      appearing strictly AFTER it counts. This is what correctly handles a
      channel stably parked on FALLBACK_SLATE the whole time (its own
      steady STATE is not a crash). The anchor's own last_error IS still
      checked, though: a dirty last_error on the anchor itself (e.g. an
      unresolved crash-flavored message still sitting on the old pid's
      last logged line) is real evidence and must not be silently ignored
      just because it happens to be the anchor.

      .PARAMETER OldPid
      .PARAMETER NewPid
      The real (integer) pids either side of the change, as already known
      to the sample-based caller (Register-ChannelSample's
      $prevPidBeforeThisSample / $NewPid) -- compared against the ring's
      own captured pid TEXT via string equality (a ring entry's pid is
      "-" or a decimal string, never parsed as [int]).

      .OUTPUTS
      $null   -- no evidence either way ($OldPid never appears anywhere in
                 the retained ring at all -- expired past the 10-minute
                 age limit, or simply never logged -- or $NewPid never
                 reached a logged ON_AIR yet) -- caller should fall back to
                 the sample-ring signal (Test-PlannedRestartSignal) and
                 record log_evidence='missing'.
      $true   -- log evidence supports a planned rollover (the window
                 contains a STARTING line and everything strictly after
                 the anchor is clean).
      $false  -- log evidence shows a crash (ANY line strictly after the
                 anchor is ERROR/FALLBACK_SLATE or carries a non-"-"
                 last_error).
    #>
    param($Context, [string]$ChannelId, $OldPid, $NewPid)
    if (-not $Context.LogRing.ContainsKey($ChannelId)) { return $null }
    $lines = @($Context.LogRing[$ChannelId])
    if ($lines.Count -eq 0) { return $null }

    $oldPidText = "$OldPid"
    $newPidText = "$NewPid"

    # Last line (ANY state) whose pid == old pid -- scan from the END
    # backward for the MOST RECENT occurrence (the process typically logs
    # many identical-pid lines while healthy; we want the LAST one before
    # it died/relaunched).
    $oldPidIdx = -1
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ("$($lines[$i].pid)" -eq $oldPidText) { $oldPidIdx = $i; break }
    }
    if ($oldPidIdx -lt 0) { return $null }

    # First ON_AIR line AFTER that whose pid == new pid.
    $newPidOnAirIdx = -1
    for ($i = $oldPidIdx + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i].state -eq 'ON_AIR' -and "$($lines[$i].pid)" -eq $newPidText) { $newPidOnAirIdx = $i; break }
    }
    if ($newPidOnAirIdx -lt 0) { return $null }

    # Round-13 finding 2: the anchor line's own STATE is excluded from the
    # dirty check (a stable FALLBACK_SLATE baseline is not itself a crash
    # -- see .SYNOPSIS and scenario (e)/(f)), but its own last_error is
    # NOT excluded -- a dirty last_error on the anchor (e.g. a STARTING
    # line at the OLD pid that already carries a crash-flavored last_error
    # from an EARLIER, unresolved failure) is still real evidence of
    # trouble and must not be silently ignored just because it happens to
    # be the anchor.
    $anchorErr = "$($lines[$oldPidIdx].last_error)"
    if ($anchorErr -ne '-' -and -not [string]::IsNullOrWhiteSpace($anchorErr)) { return $false }

    # The STATE dirty-check (ERROR/FALLBACK_SLATE) and the STARTING-presence
    # check run on everything STRICTLY AFTER the anchor through the
    # terminal ON_AIR, inclusive of the terminal.
    $window = @($lines[($oldPidIdx + 1)..$newPidOnAirIdx])
    $sawStarting = $false
    foreach ($l in $window) {
        if ($l.state -eq 'ERROR' -or $l.state -eq 'FALLBACK_SLATE') { return $false }
        $err = "$($l.last_error)"
        if ($err -ne '-' -and -not [string]::IsNullOrWhiteSpace($err)) { return $false }
        if ($l.state -eq 'STARTING') { $sawStarting = $true }
    }
    if ($sawStarting) { return $true }
    return $null
}

function Add-RingSample {
    <#
      .PARAMETER ProcessId
      Deliberately NOT named $Pid -- see this file's header.
    #>
    param($Context, [string]$ChannelId, [datetime]$Utc, $State, $ProcessId, $UpdatedAt, $LastError)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { $Context.Ring[$ChannelId] = New-Object System.Collections.ArrayList }
    $null = $Context.Ring[$ChannelId].Add([ordered]@{ utc = $Utc.ToUniversalTime().ToString('o'); state = $State; pid = $ProcessId; updated_at = $UpdatedAt; last_error = $LastError })
    while ($Context.Ring[$ChannelId].Count -gt 12) { $Context.Ring[$ChannelId].RemoveAt(0) }
}

function Test-TransitioningInWindow {
    param($Context, [string]$ChannelId, [datetime]$BeforeUtc, [int]$WindowSeconds = 180)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { return $false }
    foreach ($s in @($Context.Ring[$ChannelId])) {
        if ($s.state -ne 'TRANSITIONING') { continue }
        try {
            $sUtc = [datetime]::Parse($s.utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
        } catch { continue }
        if ($sUtc -le $BeforeUtc -and ($BeforeUtc - $sUtc).TotalSeconds -le $WindowSeconds) { return $true }
    }
    return $false
}

function Test-PlannedRestartSignal {
    <#
      .SYNOPSIS
      Round-9 "CLASSIFIER TRUTH" fix: TRANSITIONING-preceded-the-pid-change
      alone is NOT sufficient evidence of a planned restart. Measured on
      609273d (item 60): the daemon writes TRANSITIONING and the worker
      then CRASHES ~1s later -- the old rule ("TRANSITIONING within 3 min
      before pid change => planned") called that crash planned. A REAL
      planned (flag-OFF) restart at main 250026b is: TRANSITIONING ->
      worker exits 0 after EOS -> daemon _start -> STARTING -> ON_AIR. A
      crash is: non-zero exit / last_error set / state ERROR or
      FALLBACK_SLATE, or a daemon "relaunch after crash" log line.

      Round-9 finding N7 tightens this further: TRANSITIONING must be the
      LAST non-ON_AIR-pid-change-adjacent state observed for the OLD pid --
      i.e. the sample IMMEDIATELY PRECEDING the pid-change sample in the
      ring, not merely "seen at some point in the last 180s" -- AND within
      one sample interval (~30s default) of the pid change. A wide 180s
      lookback could match a stale TRANSITIONING from an entirely earlier,
      unrelated event; the tightened rule only credits the state
      transition that immediately, contiguously precedes THIS specific pid
      change.

      Classifies planned ONLY if:
        1. The ring sample immediately before $BeforeUtc (the pid-change
           sample itself, already added to the ring before this is called)
           has state == 'TRANSITIONING', AND
        2. That sample's timestamp is within $MaxGapSeconds of $BeforeUtc, AND
        3. NO sample between that TRANSITIONING sample and $BeforeUtc shows
           state in ('ERROR','FALLBACK_SLATE') or a non-null/non-empty
           last_error (defense-in-depth -- with the tightened window there
           should be no room for anything to occur between two adjacent
           samples, but this is checked rather than assumed).
      Round-11 finding 6 (LOW): the daemon's own log line format DOES exist
      and IS implemented -- see Test-PlannedRestartFromLog below, which is
      the PRIMARY signal (Register-ChannelSample tries it first); this
      function is the FALLBACK used only when the log ring has no evidence
      for this channel at all.
    #>
    param($Context, [string]$ChannelId, [datetime]$BeforeUtc, [int]$MaxGapSeconds = 30)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { return $false }
    $samples = @($Context.Ring[$ChannelId] | ForEach-Object {
        $sUtc = $null
        try { $sUtc = [datetime]::Parse($_.utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime() } catch { }
        if ($sUtc) { [pscustomobject]@{ utc = $sUtc; state = $_.state; last_error = $_.last_error } }
    } | Sort-Object utc)

    # Round-10 finding 1 (HIGH, part 2): a dropped/failed state read is a
    # HARNESS artifact (In-Sandbox-Soak.ps1's Get-ChannelStateSample
    # returning ok=$false records state=$null, last_error starting with
    # the literal "state read failed" -- that exact prefix is this file's
    # contract with the driver) -- it is NOT a real observation of the
    # channel and must not break the "immediately preceding sample" chain
    # (skip over it when walking back for lastPrior) nor trip the
    # crash-signal veto below (its last_error text describes the HTTP read
    # failing, never the product's own last_error field).
    $isReadFailureSample = { param($s) "$($s.last_error)" -like 'state read failed*' }
    $realSamples = @($samples | Where-Object { -not (& $isReadFailureSample $_) })

    # The sample AT $BeforeUtc is the pid-change sample itself (already
    # added to the ring by Add-RingSample before this is called) -- the
    # "last non-ON_AIR state of the OLD pid" is the sample immediately
    # PRECEDING it, i.e. the most recent REAL (non-read-failure) one
    # strictly earlier than $BeforeUtc.
    $priorSamples = @($realSamples | Where-Object { $_.utc -lt $BeforeUtc })
    if ($priorSamples.Count -eq 0) { return $false }
    $lastPrior = $priorSamples[-1]

    if ($lastPrior.state -ne 'TRANSITIONING') { return $false }
    if (($BeforeUtc - $lastPrior.utc).TotalSeconds -gt $MaxGapSeconds) { return $false }

    foreach ($s in $realSamples) {
        if ($s.utc -le $lastPrior.utc -or $s.utc -gt $BeforeUtc) { continue }
        if ($s.state -eq 'ERROR' -or $s.state -eq 'FALLBACK_SLATE') { return $false }
        if (-not [string]::IsNullOrWhiteSpace("$($s.last_error)")) { return $false }
    }
    return $true
}

function Register-ChannelSample {
    <#
      .SYNOPSIS
      Called for EVERY sample (each interleaved pass, at whatever cadence
      the caller actually achieves) -- records it into the ring, checks
      any pending restart for recovery-or-give-up (evaluated from THIS
      sample's own real timestamp, i.e. from the ring, never from a fixed
      cycle boundary), then checks THIS sample for a new pid change and
      classifies it via Test-PlannedRestartSignal.

      .PARAMETER Engine
      The engine already resolved for $NewPid by the CALLER (e.g.
      In-Sandbox-Soak.ps1's Get-EngineForWorkerPid, which needs
      Win32_Process and so cannot live in this pure, synthetic-data-
      testable file). Passing it in, already resolved, is what keeps this
      file testable with plain strings instead of needing to mock WMI.

      .PARAMETER LastError
      The state row's own last_error field for THIS sample -- feeds
      Test-PlannedRestartSignal's crash-signal check (round-9
      "CLASSIFIER TRUTH").

      .PARAMETER MeasuredCyclePeriodSeconds
      Round-10 finding 1 (HIGH): the actual observed time between the
      driver's heavy cycles (same number Test-InActivePlannedRestartWindow
      already takes) -- used to compute the "immediately preceding sample"
      adjacency gap as max(60s, 2x the per-sample interval), replacing a
      previously HARDCODED 30s that a real ~20-25s sample spacing could
      exceed on a slightly slower cycle (measured: a genuinely planned
      restart at +31s misclassified unplanned). Each heavy cycle
      interleaves 3 samples per channel (see this file's header), so the
      per-sample interval is estimated as $MeasuredCyclePeriodSeconds / 3.
      Default 60 (matching Test-InActivePlannedRestartWindow's own default)
      so a caller with no measurement yet still gets a sane, generous
      answer -- max(60, 2*(60/3)) = 60.
    #>
    param($Context, [string]$ChannelId, [datetime]$NowUtc, $State, [Nullable[int]]$NewPid, $UpdatedAt, $Engine, $LastError, [double]$MeasuredCyclePeriodSeconds = 60)

    # Round-9 finding N1 (BLOCKER): a SECOND pid change arriving while a
    # PREVIOUS one for the same channel is still pending (unresolved) used
    # to overwrite $Context.PendingRestarts[$ChannelId] outright, silently
    # ERASING the first event -- measured: 2 relaunches collapsed into 1
    # recorded event; a crash immediately followed by a legitimate rollover
    # could read as PASS with unplanned_relaunch_count=0. Flush the
    # existing pending restart as its OWN event (recovered=$false,
    # superseded=$true, its ORIGINAL classification preserved) BEFORE
    # recording the new one, so a crash is never silently absorbed by
    # whatever restart happens to come after it.
    $prevPidBeforeThisSample = $(if ($Context.LastPidForChannel.ContainsKey($ChannelId)) { $Context.LastPidForChannel[$ChannelId] } else { $null })
    $pidChangedThisSample = ($null -ne $NewPid -and $null -ne $prevPidBeforeThisSample -and $prevPidBeforeThisSample -ne $NewPid)
    if ($pidChangedThisSample -and $Context.PendingRestarts.ContainsKey($ChannelId)) {
        $superseded = $Context.PendingRestarts[$ChannelId]
        $null = $Context.RestartEvents.Add([ordered]@{
            channel_id = $ChannelId; detected_utc = $superseded.detected_utc.ToUniversalTime().ToString('o')
            old_pid = $superseded.old_pid; new_pid = $superseded.new_pid
            classification = $superseded.classification
            recovered = $false; recovery_gap_seconds = $null; superseded = $true; incomplete = $false
            log_evidence = $(if ($superseded.log_evidence) { $superseded.log_evidence } else { 'missing' })
        })
        $Context.PendingRestarts.Remove($ChannelId)
    }

    Add-RingSample -Context $Context -ChannelId $ChannelId -Utc $NowUtc -State $State -ProcessId $NewPid -UpdatedAt $UpdatedAt -LastError $LastError

    if ($Context.PendingRestarts.ContainsKey($ChannelId)) {
        $pending = $Context.PendingRestarts[$ChannelId]
        if ($State -eq 'ON_AIR' -and $Engine -eq 'gstreamer') {
            $gap = ($NowUtc - $pending.detected_utc).TotalSeconds
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $true; recovery_gap_seconds = [math]::Round($gap, 1); superseded = $false; incomplete = $false
                log_evidence = $(if ($pending.log_evidence) { $pending.log_evidence } else { 'missing' })
            })
            $Context.PendingRestarts.Remove($ChannelId)
        } elseif ((($NowUtc) - $pending.detected_utc).TotalSeconds -gt $Context.RestartTrackingMaxSeconds) {
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $false; recovery_gap_seconds = $null; superseded = $false; incomplete = $false
                log_evidence = $(if ($pending.log_evidence) { $pending.log_evidence } else { 'missing' })
            })
            $Context.PendingRestarts.Remove($ChannelId)
        }
    }

    if ($pidChangedThisSample) {
        # Round-10 finding 5: the daemon's own log lines are the PRIMARY
        # signal -- try them first. Only fall back to the sample-ring
        # signal (Test-PlannedRestartSignal) when the log ring has no
        # evidence at all for this channel (log unreadable, or no
        # TRANSITIONING line landed in the retained window) -- see this
        # file's header for why the log wins when both are available (it
        # sees transitions polling can miss entirely inside one gap).
        $logVerdict = Test-PlannedRestartFromLog -Context $Context -ChannelId $ChannelId -OldPid $prevPidBeforeThisSample -NewPid $NewPid
        if ($null -ne $logVerdict) {
            $isPlanned = $logVerdict
            $logEvidence = 'log'
        } else {
            # Round-10 finding 1: max(60s, 2x the measured per-sample
            # interval) -- see this function's .PARAMETER doc above.
            $effectiveMaxGapSeconds = [Math]::Max(60, 2 * ($MeasuredCyclePeriodSeconds / 3))
            $isPlanned = Test-PlannedRestartSignal -Context $Context -ChannelId $ChannelId -BeforeUtc $NowUtc -MaxGapSeconds $effectiveMaxGapSeconds
            $logEvidence = 'missing'
        }
        $classification = $(if ($isPlanned) { 'planned_restart' } else { 'unplanned_relaunch' })
        $Context.PendingRestarts[$ChannelId] = [ordered]@{ detected_utc = $NowUtc; old_pid = $prevPidBeforeThisSample; new_pid = $NewPid; classification = $classification; log_evidence = $logEvidence }
    }
    if ($null -ne $NewPid) { $Context.LastPidForChannel[$ChannelId] = $NewPid }
}

function Test-InActivePlannedRestartWindow {
    <#
      .SYNOPSIS
      Whether $ChannelId is inside an ACTIVE (not yet recovered)
      planned-restart EXEMPTION window -- the licensed exception
      SoakVerdict.ps1's Test-SoakCycle grants from the ON_AIR check.

      .PARAMETER MeasuredCyclePeriodSeconds
      The actual observed time between the driver's heavy cycles. The
      exemption window is max(60s, 2x this) -- deliberately NOT the same
      60s the PASS contract uses to judge whether a restart recovered in
      time (see this file's header, "EXEMPTION WINDOW"). Default 60 so a
      caller with no measurement yet (the very first cycle) still gets a
      sane answer.
    #>
    param($Context, [string]$ChannelId, [datetime]$NowUtc, [double]$MeasuredCyclePeriodSeconds = 60)
    if (-not $Context.PendingRestarts.ContainsKey($ChannelId)) { return $false }
    $pending = $Context.PendingRestarts[$ChannelId]
    if ($pending.classification -ne 'planned_restart') { return $false }
    $exemptionWindowSeconds = [Math]::Max(60, 2 * $MeasuredCyclePeriodSeconds)
    return (($NowUtc - $pending.detected_utc).TotalSeconds -le $exemptionWindowSeconds)
}

function Get-FlushedRestartEvents {
    <#
      .SYNOPSIS
      Flush any restart still pending (soak ended before it resolved
      either way) into RestartEvents as recovered=$false, then return the
      full event list as a plain array. Call once, at the end of the
      poll loop.

      CALLING CONVENTION (round-9 finding N6, BLOCKER -- a regression this
      review caught in the round-8 fix): ALWAYS call this as
      `@(Get-FlushedRestartEvents -Context $ctx)` -- never a bare
      `$x = Get-FlushedRestartEvents ...`. `return @($Context.RestartEvents)`
      ENUMERATES the array onto the function's output stream (N separate
      pipeline objects, not one array object), and the caller's own `@()`
      collects however many objects actually flow through -- confirmed
      directly to work correctly for N=0, 1, 2, and 3 with this exact
      calling shape. The PREVIOUS version of this function used
      `return ,@(...)` (a leading unary comma) to fix a DIFFERENT, narrower
      problem (a bare, unwrapped `$x = Get-Foo` call silently collapsing a
      1-element array down to its bare element) -- but the comma forces the
      function to emit exactly ONE pipeline object (an array containing the
      real array as its single element), so the driver's actual calling
      shape (`$restartEventsArray = @(Get-FlushedRestartEvents ...)`,
      In-Sandbox-Soak.ps1) received a 1-element array whose sole element
      was the REAL N-element array, for every N -- confirmed directly.
      Two real relaunches collapsed to Count=1 (not 2), max_restart_gap_seconds
      read empty, the >60s recovery-time FAIL rule stopped firing, and
      restart-events.json serialized as a nested `{"value":[...]}` shape.
      The fix is symmetric with the ORIGINAL problem it was chasing: keep
      the plain `@(...)` return AND always call this function through an
      `@()` wrapper -- never through a bare assignment, which is the one
      calling shape this plain form does not handle safely for N=1.

      Round-10 finding 11 (LOW, defense-in-depth): the return value is now
      explicitly typed `[object[]]` before returning -- this does NOT by
      itself change PowerShell's enumeration-on-return behavior (a `return`
      of an [object[]]-typed variable still enumerates onto the pipeline
      exactly like `return @(...)` does; the calling convention above is
      still the thing that actually matters and is UNCHANGED and still
      REQUIRED), but makes the function's declared output shape explicit
      for a future reader/reviewer rather than implicit in the `@(...)`
      call alone.

      .PARAMETER SoakEndUtc
      Round-11 finding 3 (HIGH): flushing an unresolved restart as
      recovered=$false unconditionally penalized a restart that was
      detected in the FINAL seconds of the soak window -- it never had a
      fair chance to reach ON_AIR before this lane simply stopped
      watching, yet the flush read exactly like a restart that had a full
      60s+ and still failed. An event whose detected_utc is within 60s of
      $SoakEndUtc (the actual soak end -- the driver's real deadline/last-
      observed instant, not just "whenever this function happens to run")
      is flushed as `incomplete=$true` instead: still recorded, still
      visible in the report, but EXCLUDED from SoakVerdict.ps1's
      60s-recovery FAIL rule (see that file's Get-SoakVerdict). An event
      older than 60s at $SoakEndUtc had every chance the PASS contract
      promises and simply never recovered -- that stays a real,
      unqualified FAIL. Defaults to "now" (this function's own call time)
      so existing callers/tests that never pass it keep their previous
      behavior for a truly at-the-boundary flush.
    #>
    # Deliberately UNTYPED (not [Nullable[datetime]]): binding a real
    # [datetime] argument to a [Nullable[datetime]] parameter does not
    # reliably produce a boxed Nullable with a working .Value accessor
    # under PowerShell's own binder (confirmed directly: calling .Value on
    # it returns $null, and .ToUniversalTime() on THAT throws) -- see
    # HostLiveness.ps1 for a DIFFERENT, narrower case where
    # [AllowNull()][Nullable[datetime]] was the right fix (an explicit
    # -X $null argument); this is the opposite shape (a real value must
    # always come through intact), so untyped-with-a-$null-default is used
    # instead and the value is cast explicitly where read.
    param($Context, $SoakEndUtc = $null)
    $endUtc = $(if ($SoakEndUtc) { ([datetime]$SoakEndUtc).ToUniversalTime() } else { (Get-Date).ToUniversalTime() })
    foreach ($channelId in @($Context.PendingRestarts.Keys)) {
        $pending = $Context.PendingRestarts[$channelId]
        $ageAtEndSeconds = ($endUtc - $pending.detected_utc.ToUniversalTime()).TotalSeconds
        $incomplete = ($ageAtEndSeconds -le 60)
        $null = $Context.RestartEvents.Add([ordered]@{
            channel_id = $channelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
            old_pid = $pending.old_pid; new_pid = $pending.new_pid
            classification = $pending.classification
            recovered = $false; recovery_gap_seconds = $null; superseded = $false; incomplete = $incomplete
            log_evidence = $(if ($pending.log_evidence) { $pending.log_evidence } else { 'missing' })
        })
        $Context.PendingRestarts.Remove($channelId)
    }
    [object[]]$out = @($Context.RestartEvents)
    return $out
}

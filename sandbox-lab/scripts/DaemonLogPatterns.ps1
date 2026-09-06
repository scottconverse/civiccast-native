# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# DaemonLogPatterns.ps1 -- the literal patterns/formatters that BOTH
# In-Sandbox-Soak.ps1 (the real driver) and Test-RestartClassifier.ps1 (the
# unit tests) must agree on byte-for-byte, dot-sourced by both instead of
# each keeping its own hand-typed copy.
#
# Round-13 finding 6 (MEDIUM): this file did not exist yet -- the test file
# re-typed the driver's own $script:daemonReloadAbortRegex and the
# "state read failed: ..." string formula as separate literals. A future
# edit to either the regex or the formula in the driver could silently
# drift out of sync with the test's copy, and neither file's own test
# suite would ever catch it (the test would keep passing against its own,
# now-stale copy while the real driver behaved differently). Extracted
# here so there is exactly ONE copy of each; both files dot-source this
# one, so a future edit is automatically exercised by the real tests
# instead of a stand-in.

# civiccast/egress/daemon.py:1064-1071's exact format string (main
# bcb3ebe -- re-verify against HEAD before trusting this citation blindly):
#   "channel %s: egress state -> %s (source=%s, pid=%s, last_error=%s)"
$script:DaemonLogLineRegex = [regex]'channel (?<ch>\S+): egress state -> (?<state>\S+) \(source=.*?, pid=(?<pid>\S+), last_error=(?<err>.*)\)\s*$'

# Round-11 finding 4 / round-12 finding 3 / round-13 finding 4: a seamless
# content-reload abort is NOT a `_write_state` line -- it is one of six
# distinct daemon.py WARNING-level message templates (main bcb3ebe:1946
# "declined", :2111 "falling back to restart instead of stamping ON_AIR",
# :2132 "did not land", :2143 "...treating as aborted and falling back to
# restart", :2156 "no settlement within", :1860 "Content-reload source
# preparation FAILED..." -- no "Seamless" prefix at all) that all contain
# the substring "falling back to restart" somewhere later in the same
# civiccast.egress-logged line as "for <channel_id>". The leading `.*` is
# LAZY (`.*?`), anchoring on the FIRST "for" in the line -- round-13
# finding 4: daemon.py:1946's reason parenthetical `(%s)` is an arbitrary
# exception repr that can itself contain the word "for", which a GREEDY
# leading `.*` would prefer instead of the real channel mention earlier in
# the line.
$script:DaemonReloadAbortRegex = [regex]'civiccast\.egress\S*:\s*(?<reason>.*?\bfor (?<ch>\S+)\b.*falling back to restart.*)$'

# Round-14 finding 5 (MEDIUM): `_discard_pending_reload_settlement`'s own
# INFO-level echo (daemon.py:1732-1738, "Content-reload for %s
# (reload_id=%s) discarded: %s.") is the ONLY other line that can also
# satisfy $DaemonReloadAbortRegex's substring test, and ONLY when its own
# `reason` parameter happens to itself contain "falling back to restart"
# -- measured (round-14): none of the four abort call sites that reach
# `_fall_back_to_restart_reload` actually pass that reason text (each
# discards with its OWN specific reason -- "worker exited before
# settlement could be committed", "worker reported {result}",
# "unrecognized settlement result {result!r}", "no settlement within
# {N}s" -- BEFORE calling `_fall_back_to_restart_reload`, whose own
# defensive `_discard_pending_reload_settlement(reason="falling back to
# restart")` call is then a no-op: `pending` is already popped, so its own
# log line never fires). The declined (:1946) and source-preparation-
# FAILED (:1860) paths never arm a pending reload settlement at all, so
# there is nothing to discard for them either. So the double-count this
# guarded against in earlier rounds does not actually occur in practice --
# kept anyway as a narrow, defensive exclusion in case that ever changes,
# anchored on the echo's OWN FIXED shape (not a bare "discarded:" substring
# search, which could wrongly exclude a real abort whose OWN reason text
# happens to contain the word "discarded").
$script:DaemonReloadDiscardEchoRegex = [regex]'Content-reload for \S+ \(reload_id=\S+\) discarded:'

# Round-16 finding (worker-stdout/-SeamlessReload cross-check): daemon.py's
# own confirmation that a seamless content-reload was ARMED for a channel
# (main bcb3ebe:1973-1979, `_LOG.info("Seamless content-reload armed for
# %s (reload_id=%s, switch_at_end_of_current=%s); awaiting settlement.",
# channel_id, reload_id, ...)`). Matched as a substring, not an anchored
# full-line pattern (same convention as $DaemonReloadAbortRegex above) --
# this must survive whatever timestamp/logger-name prefix the actual log
# line carries, which this lane does not control or need to know.
# In-Sandbox-Soak.ps1 records every channel this ever fires for
# ($script:reloadArmedChannels) and, under -SeamlessReload, FAILs the run
# if that channel's own worker-stdout reload_committed_count stayed 0 for
# the whole soak -- an armed-but-never-committed reload is exactly the
# fallback-to-restart failure mode -SeamlessReload exists to prove absent.
$script:DaemonReloadArmedRegex = [regex]'Seamless content-reload armed for (?<ch>\S+) \(reload_id=(?<reload_id>[^,]+),'

function New-StateReadFailureLastError {
    <#
      .SYNOPSIS
      Round-13 finding 1 (BLOCKING): the EXACT formula In-Sandbox-Soak.ps1's
      Get-ChannelStateSample uses to build the "state read failed: ..."
      text RestartClassifier.ps1's read-failure filter matches on
      (`-like 'state read failed*'`). Extracted here (round-14 finding 6)
      so the driver and the unit tests call the SAME function instead of
      each typing the string literal separately.
    #>
    param($Status, $ErrorText)
    return "state read failed: status=$Status error=$ErrorText"
}

function Get-ReloadArmedNeverCommittedChannels {
    <#
      .SYNOPSIS
      Round-2 finding 2 (HIGH): the -SeamlessReload armed-never-committed
      cross-check (see $DaemonReloadArmedRegex's own header above), pulled
      out of In-Sandbox-Soak.ps1 as a pure function so its own filtering
      logic is directly unit-testable (Test-RestartClassifier.ps1) against
      synthetic worker-stdout-counts snapshots, instead of only ever being
      exercised by a live sandbox run.

      Extracting this also fixes the bug that motivated it: the driver's
      previous inline version read $script:workerStdoutCountsByChannel at
      whatever point the poll loop happened to stop -- the LAST in-loop
      Update-WorkerStdoutCounters call runs once per channel per cycle,
      before the cycle's tsp probe and rollup, so a reload committed
      during the final ~60-75s cycle window (after that call, before the
      loop actually exited) was invisible to THIS check even though
      In-Sandbox-Soak.ps1 already performs one more full drain of the
      daemon log ring after the loop (Update-DaemonLogRing's own final
      call). The fix is at the CALL SITE (a final per-channel
      Update-WorkerStdoutCounters drain added right after that same daemon
      log drain, before this function is ever invoked) -- this function
      itself simply needs to be callable standalone so that fix's effect
      (a late-arriving commit correctly removing a channel from the
      returned list, so it never spuriously fails a -SeamlessReload run)
      is provable without a live worker process.

      .PARAMETER ArmedChannelIds
      Channel ids the daemon log confirmed "Seamless content-reload
      armed" for at least once ($script:reloadArmedChannels.Keys).

      .PARAMETER WorkerStdoutCountsByChannel
      Hashtable keyed by channel id, each value an object/hashtable with
      at least a `reload_committed_count` property/key
      ($script:workerStdoutCountsByChannel, or a synthetic stand-in in
      tests) -- the SAME per-channel cumulative counts
      Update-WorkerStdoutCounters accumulates from
      ConvertFrom-WorkerStdoutLines.

      .OUTPUTS
      string[] -- channel ids that were armed but whose own
      reload_committed_count is still 0 (or entirely absent from
      WorkerStdoutCountsByChannel), in the same order as ArmedChannelIds.
    #>
    param(
        [AllowEmptyCollection()]
        [array]$ArmedChannelIds = @(),
        $WorkerStdoutCountsByChannel = @{}
    )
    return @(
        $ArmedChannelIds | Where-Object {
            $wc = $WorkerStdoutCountsByChannel[$_]
            (-not $wc) -or ($wc.reload_committed_count -eq 0)
        }
    )
}

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-WorkerEnv.ps1 -- pytest-free PowerShell unit checks for WorkerEnv.ps1
# (sandbox-lab lane follow-up D's -WorkerEnv feature): string/array parse
# forms, NAME=VALUE splitting, invalid-character rejection, dedupe
# (later-wins), empty-value ("NAME=") unset semantics, registry-list
# merging, and the rendered-.wsb-LogonCommand quoting round trip. No
# sandbox, no filesystem, no live registry, no live service required.
#
# Run: pwsh -File sandbox-lab/scripts/Test-WorkerEnv.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkerEnv.ps1')

$script:failures = 0
$script:total = 0

function Assert-Equal {
    param([string]$Name, $Expected, $Actual)
    $script:total++
    if ("$Expected" -ne "$Actual") {
        $script:failures++
        Write-Host "[FAIL] $Name -- expected '$Expected', got '$Actual'" -ForegroundColor Red
    } else {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
}

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail = '')
    $script:total++
    if ($Condition) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } else {
        $script:failures++
        Write-Host "[FAIL] $Name $Detail" -ForegroundColor Red
    }
}

# ================================================================ parsing --
# scenario 1: single string, two entries, semicolon-separated.
$p1 = ConvertTo-WorkerEnvEntries -WorkerEnv @('CIVICCAST_STALL_TIMEOUT_S=60;CIVICCAST_EGRESS_EMBED_CAPTIONS=1')
Assert-Equal 'p1 error count' 0 $p1.errors.Count
Assert-Equal 'p1 entry count' 2 $p1.entries.Count
Assert-Equal 'p1 entry0 name' 'CIVICCAST_STALL_TIMEOUT_S' $p1.entries[0].Name
Assert-Equal 'p1 entry0 value' '60' $p1.entries[0].Value
Assert-Equal 'p1 entry0 IsUnset' $false $p1.entries[0].IsUnset
Assert-Equal 'p1 entry1 name' 'CIVICCAST_EGRESS_EMBED_CAPTIONS' $p1.entries[1].Name

# scenario 2: array form, one NAME=VALUE per element -- the SDK's
# "-WorkerEnv @('A=1','B=2')" call shape.
$p2 = ConvertTo-WorkerEnvEntries -WorkerEnv @('A=1', 'B=2')
Assert-Equal 'p2 error count' 0 $p2.errors.Count
Assert-Equal 'p2 entry count' 2 $p2.entries.Count
Assert-Equal 'p2 entry0' 'A' $p2.entries[0].Name
Assert-Equal 'p2 entry1' 'B' $p2.entries[1].Name

# scenario 3: the two call shapes produce IDENTICAL parsed entries for
# equivalent content -- a single string with an embedded ';' and an array
# whose one element is that same string must parse the same way (file
# header's own claim).
$p3a = ConvertTo-WorkerEnvEntries -WorkerEnv @('X=1;Y=2')
$p3b = ConvertTo-WorkerEnvEntries -WorkerEnv @('X=1', 'Y=2')
Assert-Equal 'p3 entry counts match' $p3a.entries.Count $p3b.entries.Count
Assert-Equal 'p3 entry0 values match' $p3a.entries[0].Value $p3b.entries[0].Value
Assert-Equal 'p3 entry1 values match' $p3a.entries[1].Value $p3b.entries[1].Value

# scenario 4: empty value -- the explicit unset/remove form.
$p4 = ConvertTo-WorkerEnvEntries -WorkerEnv @('CIVICCAST_CAPTION_TAP_DIR=')
Assert-Equal 'p4 error count' 0 $p4.errors.Count
Assert-Equal 'p4 entry count' 1 $p4.entries.Count
Assert-Equal 'p4 IsUnset' $true $p4.entries[0].IsUnset
Assert-Equal 'p4 value is empty string' '' $p4.entries[0].Value

# scenario 5: a synthetic multi-feature string exercising every parse
# shape at once -- five entries, one of them empty-value (unset), one
# with ':' and ',' in its value (GST_DEBUG), one with a Windows path
# (GST_DEBUG_FILE). Round-2 review NOTE: this is no longer the literal
# README-recommended experiment command (CIVICCAST_CAPTION_TAP_DIR=
# cannot actually disable the caption-tap leg -- see
# $recommendedExperiment below and README.md for why); it stays here
# purely as a rich PARSING exercise (unset form + multiple value shapes
# in one string), independent of what the product actually does with it.
$experiment = 'CIVICCAST_STALL_TIMEOUT_S=60;CIVICCAST_CAPTION_TAP_DIR=;CIVICCAST_EGRESS_EMBED_CAPTIONS=1;GST_DEBUG=concat:4,tee:4,appsink:4,mpegtsmux:4;GST_DEBUG_FILE=C:\CivicCastSoak\gst-debug.log'
$p5 = ConvertTo-WorkerEnvEntries -WorkerEnv @($experiment)
Assert-Equal 'p5 (synthetic multi-feature string) error count' 0 $p5.errors.Count
Assert-Equal 'p5 entry count' 5 $p5.entries.Count
Assert-Equal 'p5 GST_DEBUG value' 'concat:4,tee:4,appsink:4,mpegtsmux:4' ($p5.entries | Where-Object { $_.Name -eq 'GST_DEBUG' }).Value
Assert-Equal 'p5 GST_DEBUG_FILE value' 'C:\CivicCastSoak\gst-debug.log' ($p5.entries | Where-Object { $_.Name -eq 'GST_DEBUG_FILE' }).Value
Assert-Equal 'p5 CIVICCAST_CAPTION_TAP_DIR is unset' $true ($p5.entries | Where-Object { $_.Name -eq 'CIVICCAST_CAPTION_TAP_DIR' }).IsUnset

# scenario 5b: the ACTUAL README-recommended experiment as of round 2 --
# only the three entries that really propagate all the way to the
# GStreamer worker (CIVICCAST_STALL_TIMEOUT_S, GST_DEBUG, GST_DEBUG_FILE).
# CIVICCAST_CAPTION_TAP_DIR/CIVICCAST_EGRESS_EMBED_CAPTIONS are
# deliberately absent: civiccast/native/station_runtime.py:1362/1376
# hardcodes both unconditionally into the per-launch `spec.env`, and
# civiccast/native/supervisor/service.py's child-launch merge is
# `{**os.environ, **spec.env}` -- spec.env applied LAST always wins, so a
# registry-level removal/override of either is inert by the time a child
# process (including the GStreamer worker, several launches downstream)
# actually sees its environment.
$recommendedExperiment = 'CIVICCAST_STALL_TIMEOUT_S=60;GST_DEBUG=concat:4,tee:4,appsink:4,mpegtsmux:4;GST_DEBUG_FILE=C:\CivicCastSoak\gst-debug.log'
$p5b = ConvertTo-WorkerEnvEntries -WorkerEnv @($recommendedExperiment)
Assert-Equal 'p5b (README-recommended experiment) error count' 0 $p5b.errors.Count
Assert-Equal 'p5b entry count' 3 $p5b.entries.Count

# scenario 6: malformed entry (no '=' at all) -- a parse error, not a
# silently dropped/guessed entry.
$p6 = ConvertTo-WorkerEnvEntries -WorkerEnv @('NOTANASSIGNMENT')
Assert-Equal 'p6 error count' 1 $p6.errors.Count
Assert-Equal 'p6 entry count' 0 $p6.entries.Count

# scenario 7: invalid NAME (starts with a digit).
$p7 = ConvertTo-WorkerEnvEntries -WorkerEnv @('1BAD=x')
Assert-Equal 'p7 error count' 1 $p7.errors.Count
Assert-True 'p7 error mentions invalid name' ($p7.errors[0] -match 'invalid environment variable name')

# scenario 8: unsupported characters ('<', '>', '&', '|', '^', '%', '"')
# are REJECTED, never silently escaped -- one representative case each.
# '%' added in round-2 review: cmd.exe expands %NAME% tokens inside a
# double-quoted argument regardless of quoting (measured directly:
# 'C:\%USERNAME%\d.log' is delivered as 'C:\scott\d.log' -- see the
# real-execution round-trip scenarios below).
foreach ($bad in @('A=1<2', 'A=1>2', 'A=1&2', 'A=1|2', 'A=1^2', 'A=1%2', 'A=1"2')) {
    $pr = ConvertTo-WorkerEnvEntries -WorkerEnv @($bad)
    Assert-Equal "p8 rejects '$bad'" 1 $pr.errors.Count
}

# scenario 8b: round-2 review finding -- a value ending in a single
# trailing backslash is REJECTED (collides with this lane's own closing
# quote under the Win32 argv-tokenizer's backslash-then-quote escaping
# rule; measured directly: 'C:\CivicCastSoak\' is delivered as
# 'C:\CivicCastSoak"', swallowing everything after it into the same
# argument -- see the real-execution round-trip scenarios below). A
# value NOT ending in '\' (even one with backslashes elsewhere, or an
# EVEN number of trailing backslashes) is unaffected.
$p8b1 = ConvertTo-WorkerEnvEntries -WorkerEnv @('GST_DEBUG_FILE=C:\CivicCastSoak\')
Assert-Equal 'p8b1 rejects a single trailing backslash' 1 $p8b1.errors.Count
$p8b2 = ConvertTo-WorkerEnvEntries -WorkerEnv @('GST_DEBUG_FILE=C:\CivicCastSoak\gst-debug.log')
Assert-Equal 'p8b2 accepts a normal file path (no trailing backslash)' 0 $p8b2.errors.Count
$p8b3 = ConvertTo-WorkerEnvEntries -WorkerEnv @('A=1')
Assert-Equal 'p8b3 (sanity: a value with no backslash at all is unaffected)' 0 $p8b3.errors.Count
# an EMPTY value (the unset form) never ends in '\' -- must not be
# mistakenly caught by this rule.
$p8b4 = ConvertTo-WorkerEnvEntries -WorkerEnv @('CIVICCAST_CAPTION_TAP_DIR=')
Assert-Equal 'p8b4 (empty/unset value is unaffected by the trailing-backslash rule)' 0 $p8b4.errors.Count

# scenario 8c: round-3 review finding 4 -- non-ASCII / non-printable
# characters are REJECTED at parse time, not silently mangled by a
# downstream ASCII-only transport. MEASURED directly (round 3): writing
# a rendered command containing 'A=café日本' to a plain-ASCII
# file produced 'A=caf???' -- a lossy, silent transform that would then
# have been misattributed to "the transport mangled it" instead of "this
# value was never representable in the first place".
$p8c1 = ConvertTo-WorkerEnvEntries -WorkerEnv @('A=café日本')
Assert-Equal 'p8c1 rejects non-ASCII (café日本)' 1 $p8c1.errors.Count
Assert-True 'p8c1 error message names the real reason (printable ASCII), not a generic parse error' ($p8c1.errors[0] -match 'ASCII')
# A control character (e.g. a literal tab) is non-printable ASCII too --
# also rejected, not just multi-byte/non-Latin text.
$p8c2 = ConvertTo-WorkerEnvEntries -WorkerEnv @("A=1$([char]9)2")
Assert-Equal 'p8c2 rejects a control character (tab)' 1 $p8c2.errors.Count
# Sanity: plain printable ASCII (letters, digits, punctuation already
# allowed elsewhere) is unaffected by this rule.
$p8c3 = ConvertTo-WorkerEnvEntries -WorkerEnv @('GST_DEBUG_FILE=C:\CivicCastSoak\gst-debug.log')
Assert-Equal 'p8c3 (sanity: plain ASCII path is unaffected)' 0 $p8c3.errors.Count

# scenario 9: empty/whitespace/absent input -> no entries, no errors.
Assert-Equal 'p9a ($null) entry count' 0 (ConvertTo-WorkerEnvEntries -WorkerEnv $null).entries.Count
Assert-Equal 'p9b (empty array) entry count' 0 (ConvertTo-WorkerEnvEntries -WorkerEnv @()).entries.Count
Assert-Equal 'p9c (whitespace string) entry count' 0 (ConvertTo-WorkerEnvEntries -WorkerEnv @('   ')).entries.Count

# scenario 10: a VALUE containing '=' (e.g. a query-string-shaped value) --
# only the FIRST '=' is the split point.
$p10 = ConvertTo-WorkerEnvEntries -WorkerEnv @('A=k=v')
Assert-Equal 'p10 name' 'A' $p10.entries[0].Name
Assert-Equal 'p10 value keeps the second =' 'k=v' $p10.entries[0].Value

# ================================================================ dedupe --
# scenario 11: later entry for the same NAME (case-insensitive) wins;
# first-seen position is kept in the output order.
$d1 = Get-DedupedWorkerEnvEntries -Entries @(
    [pscustomobject]@{ Name = 'A'; Value = '1'; IsUnset = $false }
    [pscustomobject]@{ Name = 'B'; Value = '2'; IsUnset = $false }
    [pscustomobject]@{ Name = 'a'; Value = '3'; IsUnset = $false }
)
Assert-Equal 'd1 deduped count' 2 $d1.Count
Assert-Equal 'd1 A (position 0) has the LATER value' '3' $d1[0].Value
Assert-Equal 'd1 B (position 1) unaffected' '2' $d1[1].Value

# ============================================================= merge/reg --
# NOTE: every Merge-WorkerEnvIntoRegistryList call below is wrapped in
# @(...) at the CAPTURE site, not just inside the function's own `return
# @(...)` -- PowerShell collapses a 1-element array crossing a function
# return boundary back to a bare scalar the moment it's assigned
# (`$v = f` where f streams exactly one item yields a plain string, not a
# 1-element array; confirmed directly against this exact function).
# Production call sites (In-Sandbox-Soak.ps1) MUST do the same -- this is
# exactly the kind of silent single-entry collapse that would write a
# non-array value into Set-ItemProperty's -Type MultiString.

# scenario 12: fresh registry (no existing Environment at all) -- output is
# exactly the requested non-unset entries.
$m1 = @(Merge-WorkerEnvIntoRegistryList -ExistingEnv @() -Entries @(
    [pscustomobject]@{ Name = 'A'; Value = '1'; IsUnset = $false }
))
Assert-Equal 'm1 count' 1 $m1.Count
Assert-Equal 'm1 value' 'A=1' $m1[0]

# scenario 13: existing entries untouched by name are kept verbatim;
# a matching name is overwritten (never duplicated); an unset entry
# removes its name entirely and contributes nothing.
$m2 = @(Merge-WorkerEnvIntoRegistryList -ExistingEnv @('PATH=C:\x', 'A=old', 'REMOVE_ME=stale') -Entries @(
    [pscustomobject]@{ Name = 'A'; Value = 'new'; IsUnset = $false }
    [pscustomobject]@{ Name = 'REMOVE_ME'; Value = ''; IsUnset = $true }
    [pscustomobject]@{ Name = 'NEW_VAR'; Value = 'x'; IsUnset = $false }
))
Assert-True 'm2 keeps unrelated PATH entry' ($m2 -contains 'PATH=C:\x')
Assert-True 'm2 overwrites A (no duplicate, no stale "A=old")' (($m2 -contains 'A=new') -and (-not ($m2 -contains 'A=old')))
Assert-True 'm2 removes REMOVE_ME entirely' (-not @($m2 | Where-Object { $_ -match '^REMOVE_ME=' }).Count)
Assert-True 'm2 adds NEW_VAR' ($m2 -contains 'NEW_VAR=x')
Assert-Equal 'm2 final count (PATH + A=new + NEW_VAR; REMOVE_ME dropped)' 3 $m2.Count

# scenario 14: a malformed EXISTING line (no '=' at all) is left untouched,
# never dropped by this function.
$m3 = @(Merge-WorkerEnvIntoRegistryList -ExistingEnv @('NOTANASSIGNMENT') -Entries @(
    [pscustomobject]@{ Name = 'A'; Value = '1'; IsUnset = $false }
))
Assert-True 'm3 keeps the malformed existing line' ($m3 -contains 'NOTANASSIGNMENT')
Assert-True 'm3 still adds the requested entry' ($m3 -contains 'A=1')

# scenario 15: Merge internally dedupes its own $Entries argument too (a
# caller combining -SeamlessReload's synthetic entry with a -WorkerEnv
# list that happens to also name the same variable should not end up
# with two "CIVICCAST_EGRESS_SEAMLESS_RELOAD=..." lines).
$m4 = @(Merge-WorkerEnvIntoRegistryList -ExistingEnv @() -Entries @(
    [pscustomobject]@{ Name = 'X'; Value = 'first'; IsUnset = $false }
    [pscustomobject]@{ Name = 'X'; Value = 'second'; IsUnset = $false }
))
Assert-Equal 'm4 count (deduped internally)' 1 $m4.Count
Assert-Equal 'm4 value (later wins)' 'X=second' $m4[0]

# =============================================================== format --
$f1 = Format-WorkerEnvArg -Entries @(
    [pscustomobject]@{ Name = 'A'; Value = '1'; IsUnset = $false }
    [pscustomobject]@{ Name = 'B'; Value = ''; IsUnset = $true }
)
Assert-Equal 'f1 canonical form (unset entry round-trips as NAME=)' 'A=1;B=' $f1

# scenario 16: a full parse -> dedupe -> format round trip reproduces the
# coordinator's exact experiment string byte-for-byte (order preserved).
$rtParsed = ConvertTo-WorkerEnvEntries -WorkerEnv @($experiment)
$rtDeduped = Get-DedupedWorkerEnvEntries -Entries $rtParsed.entries
$rtFormatted = Format-WorkerEnvArg -Entries $rtDeduped
Assert-Equal 'rt (experiment string round-trips through parse->dedupe->format)' $experiment $rtFormatted

# scenario 17: format -> re-parse -> format is stable (idempotent) even
# after an unset entry is involved.
$rtParsed2 = ConvertTo-WorkerEnvEntries -WorkerEnv @($rtFormatted)
$rtFormatted2 = Format-WorkerEnvArg -Entries (Get-DedupedWorkerEnvEntries -Entries $rtParsed2.entries)
Assert-Equal 'rt2 (format is idempotent under re-parse)' $rtFormatted $rtFormatted2

# ======================================================= quoting/rendering
# scenario 18: empty canonical arg renders to '' (no -WorkerEnv token at
# all), matching -SeamlessReload/-CaptionsOff's own empty-when-unset
# template-placeholder convention.
Assert-Equal 'q1 empty canonical arg renders to empty string' '' (Get-QuotedWorkerEnvArgToken -CanonicalArg '')
Assert-Equal 'q1b $null canonical arg renders to empty string' '' (Get-QuotedWorkerEnvArgToken -CanonicalArg $null)

# scenario 19: a non-empty canonical arg renders as -WorkerEnv "...".
$q2 = Get-QuotedWorkerEnvArgToken -CanonicalArg 'A=1;B=2'
Assert-Equal 'q2 rendered token' '-WorkerEnv "A=1;B=2"' $q2

# Round-2 review REPLACED the regex-only Test-RenderedWorkerEnvRoundTrip
# with one that actually EXECUTES the rendered command through a real
# cmd.exe -> powershell.exe -File parse (see that function's own header
# for why -- a regex reports what text was WRITTEN, never what a real
# parse actually DELIVERS, and two real quoting bugs slipped past the old
# regex version undetected: %NAME% expansion and a trailing-backslash/
# closing-quote collision). Scenarios 20-23 below now spawn a real
# short-lived child process each; scenarios 20b/20c are the adversarial
# proof that this real-execution version actually catches what the old
# regex version measurably did not.

# scenario 20: the rendered token, embedded in a full LogonCommand string
# (the actual shape Run-SandboxSoak.ps1 builds), round-trips through a
# REAL cmd.exe/powershell.exe execution.
$fakeCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $q2"
$rt1 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $fakeCommand -ExpectedCanonicalArg 'A=1;B=2'
Assert-True 'rt1 round trip ok' $rt1.ok "(reason: $($rt1.reason))"
Assert-Equal 'rt1 found matches expected' 'A=1;B=2' $rt1.found

# scenario 20b (round-2 review, adversarial/defense-in-depth): a value
# containing '%USERNAME%' can never reach this point through
# ConvertTo-WorkerEnvEntries -> Get-QuotedWorkerEnvArgToken any more (both
# now reject '%' outright) -- this proves the round-trip check ITSELF
# would still catch it even if it somehow did, by hand-building the
# rendered command the same way a caller that skipped validation would.
# MEASURED directly against this real executor: '%USERNAME%' is expanded
# by cmd.exe to the real logged-on user name before powershell.exe ever
# sees the argument -- the expected value can never match what a real
# parse delivers, so this MUST report ok=$false. (The old regex-only
# version reported this exact case as a PASS, since it only ever compared
# rendered TEXT, never an actual parse.)
$badPercentCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  -WorkerEnv "GST_DEBUG_FILE=C:\%USERNAME%\d.log"'
$rt1b = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $badPercentCommand -ExpectedCanonicalArg 'GST_DEBUG_FILE=C:\%USERNAME%\d.log'
Assert-True 'rt1b (%USERNAME%-expansion bug) is CAUGHT, not passed' (-not $rt1b.ok) "(found: '$($rt1b.found)')"
Assert-True 'rt1b found value no longer contains a literal %' ($null -eq $rt1b.found -or $rt1b.found -notmatch '%')

# scenario 20c (round-2 review, adversarial/defense-in-depth): same
# principle for a value ending in a single trailing backslash --
# ConvertTo-WorkerEnvEntries/Get-QuotedWorkerEnvArgToken both reject this
# now too, so this hand-builds the rendered command to prove the
# round-trip check independently catches the Win32 argv-tokenizer's
# backslash-then-quote collision even if a future caller bypassed the
# upstream guards. MEASURED directly: the trailing '\' immediately before
# the closing '"' does not close the argument -- the quote survives as a
# LITERAL character in the delivered value instead.
$badBackslashCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  -WorkerEnv "GST_DEBUG_FILE=C:\CivicCastSoak\"'
$rt1c = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $badBackslashCommand -ExpectedCanonicalArg 'GST_DEBUG_FILE=C:\CivicCastSoak\'
Assert-True 'rt1c (trailing-backslash/quote collision) is CAUGHT, not passed' (-not $rt1c.ok) "(found: '$($rt1c.found)')"

# scenario 20d (round-3 review finding 5): a LEGITIMATE value that
# happens to contain the literal text "-File <something>" -- this is a
# perfectly valid -WorkerEnv value (no rejected characters at all: just
# letters, a space, a colon, backslashes, a dot) and must round-trip
# successfully, NOT be mistaken for a second -File flag. MEASURED
# directly against the PREVIOUS implementation (`-replace
# '-File\s+\S+', ...`, global/unanchored): this exact value got rewritten
# a second time INSIDE the quoted -WorkerEnv token, corrupting it and
# reporting a false round-trip FAILURE for a string a real cmd.exe/
# powershell.exe parse actually delivers correctly (inside the quotes,
# "-File ..." is just literal text). The fix anchors the substitution to
# the FIRST "-File " occurrence from the start of the string only.
$tricky = 'A=-File C:\evil.ps1'
$trickyQuoted = Get-QuotedWorkerEnvArgToken -CanonicalArg $tricky
$trickyCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $trickyQuoted"
$rt1d = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $trickyCommand -ExpectedCanonicalArg $tricky
Assert-True 'rt1d (a value containing literal "-File ...") round-trips correctly, not a false failure' $rt1d.ok "(reason: $($rt1d.reason))"
Assert-Equal 'rt1d found matches the tricky value exactly' $tricky $rt1d.found
# Also prove it survives full parse validation (no rejected characters):
# ConvertTo-WorkerEnvEntries must accept it cleanly.
$trickyParsed = ConvertTo-WorkerEnvEntries -WorkerEnv @($tricky)
Assert-Equal 'rt1d value parses with zero errors (a legitimate value, not one this lane should ever reject)' 0 $trickyParsed.errors.Count

# scenario 21: the full synthetic multi-feature string ($experiment),
# rendered and round-tripped end to end through a real execution.
$expQuoted = Get-QuotedWorkerEnvArgToken -CanonicalArg $experiment
$expCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $expQuoted"
$rt2 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $expCommand -ExpectedCanonicalArg $experiment
Assert-True 'rt2 (synthetic multi-feature string) round trip ok' $rt2.ok "(reason: $($rt2.reason))"

# scenario 21b: the ACTUAL README-recommended experiment ($recommendedExperiment),
# rendered and round-tripped end to end -- this is exactly what
# Run-SandboxSoak.ps1's own -DryRun performs for the command README.md
# documents.
$recQuoted = Get-QuotedWorkerEnvArgToken -CanonicalArg $recommendedExperiment
$recCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $recQuoted"
$rt2b = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $recCommand -ExpectedCanonicalArg $recommendedExperiment
Assert-True 'rt2b (README-recommended experiment) round trip ok' $rt2b.ok "(reason: $($rt2b.reason))"

# scenario 22: no -WorkerEnv requested at all -- rendered command has no
# token, and the round-trip check with an empty expected arg reports ok
# WITHOUT spawning anything (short-circuits before any child process).
$noWorkerEnvCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  "
$rt3 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $noWorkerEnvCommand -ExpectedCanonicalArg ''
Assert-True 'rt3 (no -WorkerEnv) round trip ok' $rt3.ok "(reason: $($rt3.reason))"

# scenario 23: a mismatch against a value that DID actually round-trip
# correctly is still DETECTED (proves this isn't just "any real
# execution reports ok" -- it genuinely compares the delivered value
# against what the caller expected).
$rt4 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $fakeCommand -ExpectedCanonicalArg 'A=1;B=999'
Assert-True 'rt4 (deliberate mismatch) is caught' (-not $rt4.ok)

# scenario 24: Get-QuotedWorkerEnvArgToken throws on an arg containing an
# unsafe character -- defense in depth even though ConvertTo-
# WorkerEnvEntries already rejects these at parse time, so a caller can
# never reach the render step with one.
$threw = $false
try { Get-QuotedWorkerEnvArgToken -CanonicalArg 'A=1<2' | Out-Null } catch { $threw = $true }
Assert-True 'q3 throws on an unsafe character reaching render (defense in depth)' $threw

# ========================================================= GST_DEBUG_FILE
# scenario 25: GST_DEBUG_FILE present among entries.
$g1 = Get-GstDebugFilePath -Entries $rtDeduped
Assert-Equal 'g1 (from the synthetic multi-feature string) GST_DEBUG_FILE path' 'C:\CivicCastSoak\gst-debug.log' $g1

# scenario 26: absent -- returns $null, not an empty string or a throw.
$g2 = Get-GstDebugFilePath -Entries @([pscustomobject]@{ Name = 'A'; Value = '1'; IsUnset = $false })
Assert-Equal 'g2 (absent) is $null' '' "$g2"

# scenario 27: GST_DEBUG_FILE explicitly unset (NAME= form) does not count
# as "present" for the directory-creation trigger.
$g3 = Get-GstDebugFilePath -Entries @([pscustomobject]@{ Name = 'GST_DEBUG_FILE'; Value = ''; IsUnset = $true })
Assert-Equal 'g3 (unset GST_DEBUG_FILE) is $null' '' "$g3"

Write-Host ""
Write-Host "WorkerEnv unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0

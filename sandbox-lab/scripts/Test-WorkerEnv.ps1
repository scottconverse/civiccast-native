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

# scenario 5: the exact experiment string from the coordinator's brief --
# five entries, one of them empty-value (unset), one with ':' and ',' in
# its value (GST_DEBUG), one with a Windows path (GST_DEBUG_FILE).
$experiment = 'CIVICCAST_STALL_TIMEOUT_S=60;CIVICCAST_CAPTION_TAP_DIR=;CIVICCAST_EGRESS_EMBED_CAPTIONS=1;GST_DEBUG=concat:4,tee:4,appsink:4,mpegtsmux:4;GST_DEBUG_FILE=C:\CivicCastSoak\gst-debug.log'
$p5 = ConvertTo-WorkerEnvEntries -WorkerEnv @($experiment)
Assert-Equal 'p5 (coordinator experiment string) error count' 0 $p5.errors.Count
Assert-Equal 'p5 entry count' 5 $p5.entries.Count
Assert-Equal 'p5 GST_DEBUG value' 'concat:4,tee:4,appsink:4,mpegtsmux:4' ($p5.entries | Where-Object { $_.Name -eq 'GST_DEBUG' }).Value
Assert-Equal 'p5 GST_DEBUG_FILE value' 'C:\CivicCastSoak\gst-debug.log' ($p5.entries | Where-Object { $_.Name -eq 'GST_DEBUG_FILE' }).Value
Assert-Equal 'p5 CIVICCAST_CAPTION_TAP_DIR is unset' $true ($p5.entries | Where-Object { $_.Name -eq 'CIVICCAST_CAPTION_TAP_DIR' }).IsUnset

# scenario 6: malformed entry (no '=' at all) -- a parse error, not a
# silently dropped/guessed entry.
$p6 = ConvertTo-WorkerEnvEntries -WorkerEnv @('NOTANASSIGNMENT')
Assert-Equal 'p6 error count' 1 $p6.errors.Count
Assert-Equal 'p6 entry count' 0 $p6.entries.Count

# scenario 7: invalid NAME (starts with a digit).
$p7 = ConvertTo-WorkerEnvEntries -WorkerEnv @('1BAD=x')
Assert-Equal 'p7 error count' 1 $p7.errors.Count
Assert-True 'p7 error mentions invalid name' ($p7.errors[0] -match 'invalid environment variable name')

# scenario 8: unsupported characters ('<', '>', '&', '|', '^', '"') are
# REJECTED, never silently escaped -- one representative case each.
foreach ($bad in @('A=1<2', 'A=1>2', 'A=1&2', 'A=1|2', 'A=1^2', 'A=1"2')) {
    $pr = ConvertTo-WorkerEnvEntries -WorkerEnv @($bad)
    Assert-Equal "p8 rejects '$bad'" 1 $pr.errors.Count
}

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

# scenario 20: the rendered token, embedded in a full LogonCommand string
# (the actual shape Run-SandboxSoak.ps1 builds), round-trips through
# Test-RenderedWorkerEnvRoundTrip.
$fakeCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $q2"
$rt1 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $fakeCommand -ExpectedCanonicalArg 'A=1;B=2'
Assert-True 'rt1 round trip ok' $rt1.ok "(reason: $($rt1.reason))"
Assert-Equal 'rt1 found matches expected' 'A=1;B=2' $rt1.found

# scenario 21: the coordinator's own experiment string, rendered and
# round-tripped end to end -- this is exactly what Run-SandboxSoak.ps1's
# own -DryRun performs.
$expQuoted = Get-QuotedWorkerEnvArgToken -CanonicalArg $experiment
$expCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  $expQuoted"
$rt2 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $expCommand -ExpectedCanonicalArg $experiment
Assert-True 'rt2 (coordinator experiment) round trip ok' $rt2.ok "(reason: $($rt2.reason))"

# scenario 22: no -WorkerEnv requested at all -- rendered command has no
# token, and the round-trip check with an empty expected arg reports ok.
$noWorkerEnvCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes 15 -OnAirBoundMinutes 12  "
$rt3 = Test-RenderedWorkerEnvRoundTrip -RenderedCommand $noWorkerEnvCommand -ExpectedCanonicalArg ''
Assert-True 'rt3 (no -WorkerEnv) round trip ok' $rt3.ok "(reason: $($rt3.reason))"

# scenario 23: a mismatch is DETECTED, not silently accepted (a quoting
# regression must fail -DryRun, not pass it).
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
Assert-Equal 'g1 (from coordinator experiment) GST_DEBUG_FILE path' 'C:\CivicCastSoak\gst-debug.log' $g1

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

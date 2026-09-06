# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# WorkerEnv.ps1 -- dot-sourceable pure logic for sandbox-lab lane follow-up
# D's -WorkerEnv feature (arbitrary environment-variable injection into the
# CivicCastSupervisor service, and therefore into the GStreamer egress
# workers, which inherit the daemon's process environment wholesale --
# civiccast/egress/gst/strategy.py's _default_worker_launcher builds `env =
# {key: value for key, value in os.environ.items() if key not in ("SWAPS",
# "INTERVAL")}` and passes that straight to subprocess.Popen). Extracted the
# same way ServiceStartFailureCheck.ps1/CaptionsOffCheck.ps1/
# WorkerStdoutParser.ps1/CpuSampler.ps1 already were, so every rule below is
# unit-testable (Test-WorkerEnv.ps1) with synthetic string/array inputs and
# synthetic REG_MULTI_SZ arrays -- no sandbox, no live registry, no service
# required.
#
# Parsing contract (both Run-SandboxSoak.ps1 -WorkerEnv and In-Sandbox-
# Soak.ps1 -WorkerEnv declare `[string[]]$WorkerEnv` -- PowerShell coerces a
# single bare string into a 1-element array automatically, so
# `-WorkerEnv "A=1;B=2"` and `-WorkerEnv @('A=1;B=2')` already arrive here
# as the identical `@('A=1;B=2')`, and there is no need to special-case
# "was this a string or an array" -- ConvertTo-WorkerEnvEntries joins every
# array element with ';' first, then splits the whole thing on ';' once.
# `-WorkerEnv @('A=1','B=2')` joins to 'A=1;B=2' and splits back into the
# same two entries -- both call shapes the coordinator asked for land on
# the same parse path):
#
#   - each ';'-separated segment is one NAME=VALUE pair; the FIRST '=' is
#     the split point (a VALUE may itself contain '=', e.g. a URL query
#     string -- GST_DEBUG's own ':'/',' syntax never uses '=' at all, so
#     this is conservative, not merely convenient);
#   - NAME must match ^[A-Za-z_][A-Za-z0-9_]*$ (every real name this lane
#     uses -- CIVICCAST_*, GST_DEBUG, GST_DEBUG_FILE -- already satisfies
#     this; a name outside it is a parse error, not a best-effort guess);
#   - an EMPTY VALUE (`NAME=`) is the explicit "remove/unset" form (item 3
#     of the follow-up-D brief): civiccast/captions/tap.py:67-73's own
#     `os.environ.get("CIVICCAST_CAPTION_TAP_DIR", "").strip(); if not
#     root: return None` shows the product treats an empty string the same
#     as absent for THAT variable, but this lane cannot assume every
#     variable a future experiment injects has the same fallback -- so
#     `NAME=` is defined here, once, as "delete this service's own
#     REG_MULTI_SZ entry for NAME instead of writing an empty one",
#     working identically for any variable regardless of its own
#     empty-string handling;
#   - `<`, `>`, `&`, `|`, `^`, and a literal `"` are rejected outright in
#     either NAME or VALUE: the .wsb <LogonCommand> is executed via
#     cmd.exe, whose redirection/pipe/escape metacharacter scan runs
#     BEFORE (and independently of) the quote-aware argv tokenizing
#     powershell.exe itself performs on its own -File arguments -- `<`/`>`
#     are treated as real redirection operators by cmd.exe EVEN INSIDE a
#     double-quoted token (the documented `tuning-harness-launcher-traps`
#     gotcha: "cmd.exe eats <> in task args"). Rather than attempt a
#     caret-escaping scheme this lane cannot round-trip-prove end to end,
#     values containing any of these characters are refused at parse time
#     -- a real GST_DEBUG_FILE Windows path never needs any of them.

function ConvertTo-WorkerEnvEntries {
    <#
      .SYNOPSIS
      Parse a -WorkerEnv value (string or array; see file header) into an
      ordered list of NAME=VALUE entries, or a list of parse-error strings.
      Pure function -- no filesystem, no registry, no network.

      .OUTPUTS
      [pscustomobject] @{
        entries = @([pscustomobject]@{ Name; Value; IsUnset })  -- IN
                    THE ORDER GIVEN, not yet deduped (see
                    Get-DedupedWorkerEnvEntries for that)
        errors  = @([string])  -- one line per unparsable/rejected segment;
                    empty when every segment parsed cleanly
      }
    #>
    param([string[]]$WorkerEnv)

    $entries = @()
    $errors = @()
    if (-not $WorkerEnv -or $WorkerEnv.Count -eq 0) {
        return [pscustomobject]@{ entries = $entries; errors = $errors }
    }
    $joined = ($WorkerEnv -join ';')
    if ([string]::IsNullOrWhiteSpace($joined)) {
        return [pscustomobject]@{ entries = $entries; errors = $errors }
    }
    $segments = @($joined -split ';' | Where-Object { $_.Trim().Length -gt 0 })
    foreach ($seg in $segments) {
        $item = $seg.Trim()
        $eqIdx = $item.IndexOf('=')
        if ($eqIdx -lt 1) {
            $errors += "unparsable -WorkerEnv entry (expected NAME=VALUE): '$item'"
            continue
        }
        $name = $item.Substring(0, $eqIdx).Trim()
        $value = $item.Substring($eqIdx + 1)
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            $errors += "invalid environment variable name '$name' in entry '$item' (must match ^[A-Za-z_][A-Za-z0-9_]*`$)"
            continue
        }
        if ($name -match '[<>&|^%"]' -or $value -match '[<>&|^%"]') {
            $errors += "entry '$item' contains a character (one of < > & | ^ % or a literal quote) that cannot survive the .wsb LogonCommand's cmd.exe quoting -- rejected, not best-effort escaped"
            continue
        }
        # Round-2 review finding (item 3): a value ending in a single
        # trailing backslash collides with the closing quote this lane
        # itself appends in Get-QuotedWorkerEnvArgToken -- the Win32
        # argv-tokenizer rule for a quoted argument is that N backslashes
        # immediately before a '"' collapse to floor(N/2) literal
        # backslashes, and an ODD N additionally makes that '"' a literal
        # character rather than the string terminator. Measured directly:
        # a value of 'C:\CivicCastSoak\' rendered as ...\CivicCastSoak\"
        # parses back as ...\CivicCastSoak" (the quote does not close,
        # and the rest of the command line is swallowed into the same
        # argument). Rejected universally (not just for whichever entry
        # happens to land last in the joined string) because dedupe/merge
        # ordering is not something a caller should have to reason about
        # to know whether a given value is safe.
        if ($value -match '\\$') {
            $errors += "entry '$item' has a value ending in a single trailing backslash ('\'), which collides with the closing quote this lane appends around the rendered -WorkerEnv arg (Win32 argv-tokenizer backslash-then-quote escaping) -- rejected, not best-effort escaped; if this is a directory path, name the file inside it instead of the bare directory"
            continue
        }
        $entries += [pscustomobject]@{ Name = $name; Value = $value; IsUnset = ($value.Length -eq 0) }
    }
    return [pscustomobject]@{ entries = $entries; errors = $errors }
}

function Get-DedupedWorkerEnvEntries {
    <#
      .SYNOPSIS
      Dedupe a list of parsed entries by NAME (case-insensitive -- Windows
      environment-variable names are case-insensitive), later entry wins,
      first-seen position kept for stable, reproducible output ordering.
    #>
    param([object[]]$Entries)
    $map = [ordered]@{}
    foreach ($e in @($Entries)) {
        if (-not $e) { continue }
        $key = "$($e.Name)".ToUpperInvariant()
        $map[$key] = $e
    }
    return @($map.Values)
}

function Merge-WorkerEnvIntoRegistryList {
    <#
      .SYNOPSIS
      Given a service's existing Environment REG_MULTI_SZ contents (an
      array of "NAME=VALUE" strings, exactly what Get-ItemProperty ...
      .Environment returns) and a deduped list of requested entries,
      return the new array to write back: any existing entry whose NAME
      matches a requested entry is dropped (its slot in the array is not
      preserved -- matching the existing -SeamlessReload precedent's own
      `Where-Object { $_ -notmatch '^NAME=' }` filter-then-append
      pattern), an unset (`IsUnset=$true`) requested entry contributes
      NOTHING to the output (that is the removal itself), and every other
      requested entry is appended as "NAME=VALUE". A malformed existing
      line (no '=' at all) is left untouched -- this function only ever
      acts on lines it can parse a NAME out of.

      .OUTPUTS
      [string[]] -- the new REG_MULTI_SZ value.
    #>
    param([string[]]$ExistingEnv, [object[]]$Entries)
    $deduped = Get-DedupedWorkerEnvEntries -Entries $Entries
    $namesTouched = @($deduped | ForEach-Object { "$($_.Name)".ToUpperInvariant() })
    $kept = @(
        @($ExistingEnv) | Where-Object {
            $m = [regex]::Match([string]$_, '^([^=]+)=')
            if (-not $m.Success) { return $true }
            -not ($namesTouched -contains $m.Groups[1].Value.ToUpperInvariant())
        }
    )
    $added = @($deduped | Where-Object { -not $_.IsUnset } | ForEach-Object { "$($_.Name)=$($_.Value)" })
    return @($kept + $added)
}

function Format-WorkerEnvArg {
    <#
      .SYNOPSIS
      Render a (deduped) entry list back to the canonical ';'-joined
      "NAME=VALUE;NAME2=" string form -- what gets threaded through the
      .wsb LogonCommand's -WorkerEnv "..." token and what the guest
      receives verbatim as its own -WorkerEnv value. An unset entry
      round-trips as "NAME=" (empty value), which the guest's own
      ConvertTo-WorkerEnvEntries parses right back into IsUnset=$true --
      the removal request survives the host->guest hop losslessly.
    #>
    param([object[]]$Entries)
    return (@($Entries) | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ';'
}

function Get-QuotedWorkerEnvArgToken {
    <#
      .SYNOPSIS
      Wrap a canonical WorkerEnv arg string in the double quotes the
      LogonCommand needs, refusing (never silently escaping) any character
      that cannot survive cmd.exe's redirection/pipe scan -- see the file
      header. Returns '' (render nothing, no -WorkerEnv token at all) for
      an empty canonical arg, matching the existing -SeamlessReload/
      -CaptionsOff template placeholders' own empty-when-unset convention.
    #>
    param([string]$CanonicalArg)
    if ([string]::IsNullOrEmpty($CanonicalArg)) { return '' }
    if ($CanonicalArg -match '["<>&|^%]') {
        throw "canonical -WorkerEnv arg contains a character unsafe to embed in the .wsb LogonCommand (a literal quote, or one of < > & | ^ %): '$CanonicalArg'"
    }
    # Round-2 review finding (item 3): the canonical arg is the string this
    # function wraps in a closing '"' -- if IT ends in an odd number of
    # backslashes (in practice: one, since ConvertTo-WorkerEnvEntries
    # already rejects any single entry's value ending in '\', so this can
    # only still happen for an unset entry's trailing 'NAME=' -- which
    # never ends in '\' either -- kept here purely as defense in depth for
    # a future caller that builds a CanonicalArg some other way), the
    # closing quote would not actually close the argument. See
    # ConvertTo-WorkerEnvEntries's own matching comment for the exact
    # Win32 argv-tokenizer rule and the measured repro.
    if ($CanonicalArg -match '\\+$') {
        $trailing = [regex]::Match($CanonicalArg, '\\+$').Value
        if (($trailing.Length % 2) -eq 1) {
            throw "canonical -WorkerEnv arg ends in an odd number of trailing backslashes, which would collide with this function's own closing quote: '$CanonicalArg'"
        }
    }
    return '-WorkerEnv "' + $CanonicalArg + '"'
}

function Test-RenderedWorkerEnvRoundTrip {
    <#
      .SYNOPSIS
      Round-trip check for -DryRun (and Test-WorkerEnv.ps1): actually
      EXECUTE the rendered LogonCommand text through cmd.exe (the real
      transport a .wsb LogonCommand uses) and powershell.exe's own -File
      argv delivery, substituting a tiny throwaway capture script in
      place of whatever -File target the command names -- every other
      token, including the -WorkerEnv "..." token under test, is left
      completely untouched. Confirms it reproduces the exact canonical
      arg that was rendered in.

      Round-2 review REPLACED an earlier regex-only version after it was
      shown to pass two real quoting bugs a static regex has no way to
      catch: cmd.exe expands %NAME% tokens inside a double-quoted
      argument regardless of quoting (measured: a value of
      `C:\%USERNAME%\d.log` is delivered to the guest as `C:\scott\d.log`
      -- the OLD regex-only round trip reported this as a PASS, since it
      only ever compared the rendered TEXT, never what a real parse of
      that text actually produces), and a value ending in a single
      trailing backslash collides with the closing quote under the Win32
      argv-tokenizer's backslash-then-quote escaping rule (measured:
      `C:\CivicCastSoak\` is delivered as `C:\CivicCastSoak"`, silently
      swallowing everything after it into the same argument). Both are
      now also rejected outright at parse time (ConvertTo-
      WorkerEnvEntries) as defense in depth -- but this function no
      longer TRUSTS that rejection; it proves the ACTUAL delivered value
      by running the real two-layer parse, so a future cmd.exe/
      PowerShell quoting quirk this lane has not thought of yet still
      gets CAUGHT here instead of silently passing a regex that only
      checks its own assumptions.

      .OUTPUTS
      [pscustomobject] @{ ok; found; reason }
    #>
    param([string]$RenderedCommand, [string]$ExpectedCanonicalArg)

    if ($RenderedCommand -notmatch '-WorkerEnv\s') {
        if ([string]::IsNullOrEmpty($ExpectedCanonicalArg)) {
            return [pscustomobject]@{ ok = $true; found = $null; reason = 'no -WorkerEnv token present in the rendered command, and none was expected (empty/absent -WorkerEnv)' }
        }
        return [pscustomobject]@{ ok = $false; found = $null; reason = "no '-WorkerEnv ' token found in the rendered command, but a non-empty arg ('$ExpectedCanonicalArg') was expected" }
    }
    if ([string]::IsNullOrEmpty($ExpectedCanonicalArg)) {
        return [pscustomobject]@{ ok = $false; found = $null; reason = 'a -WorkerEnv token is present in the rendered command, but none was expected' }
    }

    $tempDir = [System.IO.Path]::GetTempPath()
    $token = [guid]::NewGuid().ToString('N')
    $captureScriptPath = Join-Path $tempDir "workerenv-rt-capture-$token.ps1"
    $outPath = [System.IO.Path]::ChangeExtension($captureScriptPath, '.out.txt')
    $batchPath = Join-Path $tempDir "workerenv-rt-$token.cmd"

    # This capture script declares NO parameters at all -- every token the
    # real cmd.exe -> powershell.exe -File parse hands it lands, verbatim,
    # in $args (PowerShell's automatic unbound-argument variable), so this
    # observes exactly what that real two-layer parse delivers rather than
    # a guess at it. Entirely single-quoted (@'...'@): nothing here is
    # interpolated by THIS scope, so there is zero risk of this test
    # harness repeating the exact `\"`-inside-a-double-quoted-string
    # authoring mistake that broke WorkerEnv.ps1's own error message
    # earlier in this lane's history. It computes its own output path from
    # its own script path at RUN time via ``$PSCommandPath``.
    $captureScript = @'
$idx = -1
for ($i = 0; $i -lt $args.Count; $i++) { if ($args[$i] -eq '-WorkerEnv') { $idx = $i; break } }
$outPath = [System.IO.Path]::ChangeExtension($PSCommandPath, '.out.txt')
if ($idx -ge 0 -and ($idx + 1) -lt $args.Count) {
    Set-Content -Path $outPath -Value "WORKERENV_RT_RESULT=$($args[$idx + 1])" -Encoding UTF8
} else {
    Set-Content -Path $outPath -Value 'WORKERENV_RT_RESULT=<absent>' -Encoding UTF8
}
'@
    Set-Content -Path $captureScriptPath -Value $captureScript -Encoding UTF8

    # Substitute ONLY the -File target -- every other token in the
    # rendered command, including the -WorkerEnv "..." token under test,
    # is byte-for-byte untouched, so this proves exactly how THAT text
    # survives the real parse. Written to a .cmd file and executed
    # directly (rather than passed as a -ArgumentList to cmd.exe from
    # here) so there is no SECOND layer of PowerShell-side argument
    # re-quoting between this test harness and the cmd.exe parse under
    # test -- the .cmd file's bytes are exactly what cmd.exe reads.
    $testCommand = $RenderedCommand -replace '-File\s+\S+', "-File `"$captureScriptPath`""
    Set-Content -Path $batchPath -Value $testCommand -Encoding ASCII

    $result = [pscustomobject]@{ ok = $false; found = $null; reason = 'unset' }
    try {
        if (Test-Path $outPath) { Remove-Item -Path $outPath -Force -ErrorAction SilentlyContinue }
        $p = Start-Process -FilePath $batchPath -PassThru -WindowStyle Hidden -ErrorAction Stop
        $null = $p.Handle
        $exited = $p.WaitForExit(15000)
        if (-not $exited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
            $result = [pscustomobject]@{ ok = $false; found = $null; reason = 'the real cmd.exe/powershell.exe round-trip child did not exit within 15s' }
        } elseif (-not (Test-Path $outPath)) {
            $result = [pscustomobject]@{ ok = $false; found = $null; reason = "the round-trip child exited but never wrote its output file -- see $batchPath" }
        } else {
            $rawOut = Get-Content -Path $outPath -Raw -ErrorAction SilentlyContinue
            $m = [regex]::Match($rawOut, '^WORKERENV_RT_RESULT=(.*?)\r?\n?$', [System.Text.RegularExpressions.RegexOptions]::Singleline)
            if (-not $m.Success) {
                $result = [pscustomobject]@{ ok = $false; found = $null; reason = "unparsable round-trip output: '$rawOut'" }
            } else {
                $found = $m.Groups[1].Value
                if ($found -eq '<absent>') {
                    $result = [pscustomobject]@{ ok = $false; found = $null; reason = 'the real parser never found a -WorkerEnv token followed by a value at all' }
                } else {
                    $ok = ($found -ceq $ExpectedCanonicalArg)
                    $result = [pscustomobject]@{ ok = $ok; found = $found; reason = $(if ($ok) { 'match (proven by an actual cmd.exe/powershell.exe argv round trip, not a regex)' } else { "expected '$ExpectedCanonicalArg', the REAL parser actually delivered '$found'" }) }
                }
            }
        }
    } catch {
        $result = [pscustomobject]@{ ok = $false; found = $null; reason = "round-trip execution failed: $_" }
    } finally {
        foreach ($f in @($captureScriptPath, $outPath, $batchPath)) {
            try { if (Test-Path $f) { Remove-Item -Path $f -Force -ErrorAction SilentlyContinue } } catch { }
        }
    }
    return $result
}

function Get-GstDebugFilePath {
    <#
      .SYNOPSIS
      Item 2's trigger check: does this (deduped, non-unset) entry list
      set GST_DEBUG_FILE, and if so, to what path. Returns $null when
      absent -- the caller (In-Sandbox-Soak.ps1) uses this both to create
      the containing directory before the service restart and to know
      what to copy into logs\checkpoint-cycleN\ / logs\final\.
    #>
    param([object[]]$Entries)
    $hit = @($Entries) | Where-Object { $_ -and (-not $_.IsUnset) -and ("$($_.Name)".ToUpperInvariant() -eq 'GST_DEBUG_FILE') } | Select-Object -Last 1
    if ($hit) { return $hit.Value }
    return $null
}

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Host-Launch-Sandbox-Test.ps1
# Runs ON THE HOST (not in Sandbox). Generates CivicCastSandboxTest.wsb from
# CivicCastSandboxTest.wsb.template (Windows Sandbox requires absolute host
# paths in its MappedFolder entries, so the template is rendered against
# -Root on every launch rather than checked in as a fixed .wsb), launches
# Windows Sandbox with it, polls the host-visible output folder for the
# in-sandbox script's DONE.json, then prints the collected summary. Times out
# rather than hanging forever (e.g. if a UAC consent dialog is blocking the
# unattended run inside the sandbox).
#
# Imported into civiccast-native/sandbox-lab/ from the standalone proven
# harness at C:\Users\scott\Desktop\Code\sandbox-lab\ (Gate A project). Only
# change from the original: -Root is now a parameter (default = this script's
# own directory) instead of a hardcoded absolute path, and the .wsb is
# generated from a template instead of being a static checked-in file.
#
# HARDENED 2026-08-17 (inherited from the original harness): polls for
# DONE.json (not DONE.marker). DONE.json is the LAST file
# In-Sandbox-Report.ps1 writes, written only after summary.json's final
# flush -- DONE.marker alone was ambiguous (a stale copy, or a marker written
# before summary.json finished, could in theory race). This script's own
# polling loop below is also the reason a real Gate A run should reliably
# produce a DONE.json: it waits for the authoritative marker instead of
# racing ahead on an intermediate result line the way the old manual
# Watch-Run.ps1 monitor did (see sandbox-lab/scripts/Watch-Run.ps1's own
# header comment and docs/ops/gate-a.md's "Known harness quirk" section for
# the history of why the Aug-19 reference run's own output is missing
# DONE.json despite every other check passing).
#
# HARDENED 2026-08-24: Windows Sandbox is a SHARED single-instance resource
# on this machine -- an independent build system (not ours) also launches
# Windows Sandbox here at unpredictable times, and only one instance can run
# system-wide at a time. This script must never launch into a sandbox it
# does not own, wait on it ambiguously, or kill it. Before launching (see
# "Guard: wait for a free sandbox" below) it checks for any of the sandbox
# process names and, if found, polls up to -SandboxWaitMinutes for them to
# clear rather than launching on top of them. At teardown it only stops the
# process PIDs it recorded as ITS OWN right after its own Start-Process call
# -- never a blanket stop-by-name, which could kill the other party's run.
#
# HARDENED <gate-a-mapped-folder-stalls>: quiet-share fallback. In-sandbox
# writes now go to a local dir that a separate shipper process mirrors into
# this mapped folder every ~25s, heartbeat file included -- so on a healthy
# run SOMETHING under output\ changes at least every half minute, right
# through the T5 soak's otherwise-silent 5-minute beats. If nothing changes
# for -QuietShareMinutes while the VM is still alive, the guest-to-host
# channel is broken (or the guest is wholly wedged) and no amount of further
# waiting will produce evidence. This script now says so with its own marker
# and a distinct exit code instead of burning the remaining hours of
# -TimeoutMinutes on a run that can never report.
#
# The two guards are complementary and both live in the poll section below:
# SANDBOX-BUSY.txt means this run never launched (someone else held the
# resource); HOST-QUIET-SHARE.txt means it launched and then stopped being
# able to report. Neither is a station-acceptance finding.
#
# HARDENED <gate-a-teardown-drain> 2026-08-26: Gate A run 32926056071
# finished (job SUCCESS) at ~04:17Z while vmmemWindowsSandbox (15.6 GB) was
# still tearing down, still holding VSMB handles on this run's own mapped
# folders. A second Gate A run (32929704614) dispatched one minute later hit
# a checkout EBUSY on sandbox-lab/scripts ("EBUSY: resource busy or locked,
# rmdir ...") plus permission warnings under
# hoststore\install\dependencies\ollama and runtime\python312.zip -- the VM
# finished exiting on its own a few minutes after that. Stop-Process below
# (step 5) only REQUESTS the VM stop; it returns as soon as the request is
# accepted, not once the VM and its VSMB handles are actually gone. Step 6
# below drains that teardown -- bounded, so a VM that never lets go cannot
# hang this script forever -- before handing control back to the caller
# (Run-GateA.ps1, then the workflow's next Checkout step).
param(
    [string]$Root = $PSScriptRoot,
    # Must stay ABOVE In-Sandbox-Report.ps1's own -MaxScriptMinutes (150) so
    # the in-sandbox watchdog is always the first bound to fire and the host
    # remains the last resort, not the first. These two numbers are one
    # setting in two places -- change them together.
    [int]$TimeoutMinutes = 170,
    # Minutes for In-Sandbox-Report.ps1's T5 soak loop (it defaults to 20 when
    # SOAK_MINUTES.txt is absent). Written into output\SOAK_MINUTES.txt AFTER
    # this script's own output-dir wipe (step 1) so a caller (Run-GateA.ps1)
    # does not need a separate hook point to seed it -- pass -SoakMinutes
    # here instead of writing the file directly.
    [int]$SoakMinutes = 20,
    # Minutes to wait for Windows Sandbox to become free before giving up.
    # Windows Sandbox is a single-instance-per-machine resource shared with
    # an independent, unrelated build system on this box -- if it is already
    # occupied when this script starts, it polls rather than launching on
    # top of the other run. See "Guard: wait for a free sandbox" below.
    [int]$SandboxWaitMinutes = 90,
    # No change anywhere under output\ for this long, with the VM still
    # alive, is declared a harness error. The shipper's heartbeat tick is
    # ~25s, so this is ~36x the expected quiet interval -- generous enough
    # that a slow host or a stalled tick cannot trip it, tight enough to end
    # a dead run in minutes instead of hours.
    [int]$QuietShareMinutes = 15,

    # Bound on step 6's teardown-drain, in seconds. After Stop-Process (step
    # 5) is issued against this run's own recorded sandbox PIDs, the drain
    # polls until BOTH the VM process is gone AND every one of this run's
    # mapped host folders is confirmed rename-able (VSMB handle released)
    # before returning. 300s (5 minutes) is generous relative to the few
    # minutes run 32926056071's VM took to actually exit after job success,
    # while still bounding this script's own runtime.
    [int]$TeardownDrainSeconds = 300,

    # Poll interval, in seconds, for the teardown drain above.
    [int]$TeardownDrainPollSeconds = 5,

    # HARDENED <gate-a-orphan-guard> 2026-08-26: minutes a WindowsSandbox
    # server/client process may sit with NO vmmemWindowsSandbox (the actual
    # VM) before the pre-launch busy guard stops treating it as someone
    # else's live session and classifies it an ORPHAN instead. A real launch
    # spawns vmmemWindowsSandbox within seconds to a couple of minutes of the
    # server process, so 10 minutes of continuous vmmem absence is not
    # something a live launch produces. See the busy-guard section below and
    # docs/ops/gate-a.md, "Shared Windows Sandbox: the busy guard -- orphan
    # detection".
    [int]$OrphanGraceMinutes = 10
)

$ErrorActionPreference = 'Stop'

$OutDir = Join-Path $Root 'output'
$TemplatePath = Join-Path $Root 'CivicCastSandboxTest.wsb.template'
$WsbPath = Join-Path $Root 'CivicCastSandboxTest.wsb'
$DoneMarker = Join-Path $OutDir 'DONE.json'
$SummaryPath = Join-Path $OutDir 'summary.json'
# Read by scripts/gate_a_verdict.py, which reports a run carrying this file
# as HARNESS_ERROR -- never as a station-acceptance FAIL. A broken evidence
# channel says nothing about the product.
$QuietShareMarker = Join-Path $OutDir 'HOST-QUIET-SHARE.txt'

# Process names that indicate a Windows Sandbox VM is running (either ours or
# someone else's -- there is only ever one system-wide). Used both by the
# pre-launch busy guard and by the end-of-run teardown's own-PID filter.
$SandboxProcessNames = @(
    'WindowsSandboxClient',
    'WindowsSandboxRemoteSession',
    'WindowsSandboxServer',
    'vmmemWindowsSandbox'
)

Write-Host "=== CivicCast Native Gate A -- Windows Sandbox station-acceptance harness ===" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (-not (Test-Path $TemplatePath)) {
    Write-Error "Missing .wsb template at $TemplatePath"
    exit 1
}

function Resolve-PhysicalPath {
    <#
      Walk a path through any reparse points (NTFS junctions / directory
      symlinks) to the real directory behind it, and return that.

      Why <gate-a-run7-findings>: Gate A's kit reaches the VM through TWO
      chained junctions --
        sandbox-lab\kit-download  ->  sandbox-lab\kit-staging\<sha>  ->  C:\CivicCastTester\kit-staging\<sha>
      -- because Run-GateA.ps1 points kit-download at whatever -KitDir
      resolved to, and the workflow's "reuse a locally pre-staged kit" step
      had already made THAT a junction. `Resolve-Path` does not follow
      reparse points, so the .wsb ends up asking Windows Sandbox to share a
      junction whose target is itself a junction.

      To be clear about what this is and is not: this is NOT the proven
      cause of run7's missing station bundle. Run6 passed with the byte-
      identical two-hop chain (its own workflow log shows the same "Reusing
      locally staged kit" and the same "kit-download -> ...kit-staging\<sha>
      (junction)" lines), so the chain cannot by itself explain run7. It is
      hardening: handing VSMB the physical directory removes a reparse hop
      it has no reason to be asked to traverse, and it makes the .wsb say
      what is actually being shared.
    #>
    param([string]$Path, [int]$MaxHops = 8)
    $current = $Path
    for ($hop = 0; $hop -lt $MaxHops; $hop++) {
        $item = $null
        try { $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop } catch { break }
        if (-not $item.LinkType) { break }
        $target = @($item.Target) | Select-Object -First 1
        if (-not $target) { break }
        if (-not [System.IO.Path]::IsPathRooted($target)) {
            $target = Join-Path (Split-Path -Parent $current) $target
        }
        $current = $target
    }
    try { return (Get-Item -LiteralPath $current -Force -ErrorAction Stop).FullName } catch { return $current }
}

# 0. Render the .wsb from the template. Windows Sandbox's MappedFolder
#    HostFolder elements must be absolute host paths -- they cannot be
#    relative to the .wsb file's own location -- so this file is regenerated
#    on every launch against the resolved $Root rather than checked in as a
#    static file with a stale developer-machine path baked in.
#
#    Every HostFolder is additionally resolved through any reparse points to
#    the PHYSICAL directory before it is written into the .wsb -- see
#    Resolve-PhysicalPath above for what that fixes and, just as important,
#    what it does not.
$templateContent = Get-Content -Path $TemplatePath -Raw
$rendered = $templateContent.Replace('{{ROOT}}', $Root)
# Explicit match loop rather than a MatchEvaluator scriptblock: Windows
# PowerShell 5.1's scriptblock-to-delegate conversion is not something this
# harness should depend on, and the substitution is trivial to do by hand.
$mappedRx = [regex]'(?s)<HostFolder>\s*(.*?)\s*</HostFolder>'
$resolutionNotes = New-Object System.Collections.Generic.List[string]
$declaredPaths = @($mappedRx.Matches($rendered) | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
foreach ($declared in $declaredPaths) {
    $physical = Resolve-PhysicalPath -Path $declared
    if ($physical -ne $declared) {
        $resolutionNotes.Add("$declared  ->  $physical")
        $rendered = $rendered.Replace("<HostFolder>$declared</HostFolder>", "<HostFolder>$physical</HostFolder>")
    }
}
Set-Content -Path $WsbPath -Value $rendered -Encoding UTF8
Write-Host "Rendered $WsbPath from template (Root=$Root)"
if ($resolutionNotes.Count -gt 0) {
    Write-Host "Resolved $($resolutionNotes.Count) MappedFolder path(s) through reparse points before mapping:"
    foreach ($note in $resolutionNotes) { Write-Host "  $note" }
} else {
    Write-Host "No MappedFolder HostFolder path needed reparse-point resolution."
}

# Final, resolved set of MappedFolder host directories for this run -- read
# back from $rendered (post reparse-point substitution) rather than the
# earlier $declaredPaths, so this is exactly what VSMB actually shares into
# the VM. Step 6's teardown-drain probes this same list.
$mappedHostFolders = @($mappedRx.Matches($rendered) | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)

# 1. Stamp a clean output dir so a stale DONE.marker from a previous run can
#    never be mistaken for this run's completion.
if (Test-Path $OutDir) {
    Get-ChildItem -Path $OutDir -Force | Where-Object { $_.Name -ne '.gitkeep' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$launchStamp = Get-Date
Set-Content -Path (Join-Path $OutDir '_HOST_LAUNCHED.marker') -Value $launchStamp.ToString('o') -Encoding UTF8
Set-Content -Path (Join-Path $OutDir 'SOAK_MINUTES.txt') -Value "$SoakMinutes" -Encoding UTF8
Write-Host "Output dir stamped clean: $OutDir (SOAK_MINUTES=$SoakMinutes)"

# 1b. Guard: wait for a free sandbox. Windows Sandbox only ever runs ONE
#     instance system-wide -- if any of $SandboxProcessNames is already
#     running, it belongs to a different, independent process on this box
#     (this repo's Gate A harness is not the only thing that launches
#     Windows Sandbox here). Never launch on top of a REAL session, never
#     touch it -- poll every 30s up to -SandboxWaitMinutes for it to clear,
#     logging progress to SANDBOX-WAIT.txt, and give up cleanly (exit 3) if
#     it is still busy at the deadline.
#
#     HARDENED <gate-a-orphan-guard> 2026-08-26: Gate A run 32930110802's
#     busy guard declared BUSY for the entire 90-minute -SandboxWaitMinutes
#     window on the strength of ONE process -- WindowsSandboxServer, PID
#     17548, 81 MB working set, started hours earlier during a prior run's
#     slow teardown (see <gate-a-teardown-drain> above; PR #48 shrinks how
#     often this can happen but cannot make it impossible). There was no
#     vmmemWindowsSandbox (the actual VM -- multi-GB when a session is
#     real), no WindowsSandboxClient window, and `wsb list` reported zero
#     sessions throughout. The old guard could not tell an orphaned
#     leftover server process from someone else's real session and burned
#     the whole wait window on dead weight.
#
#     The fix is evidence-based, not name-based: every poll records BOTH the
#     full $SandboxProcessNames process list AND whether vmmemWindowsSandbox
#     specifically is among them (name, PID, working-set bytes, start time
#     for each -- see Get-SandboxBusyEvidence / Format-SandboxProcessEvidence
#     below). vmmemWindowsSandbox present, at any point, means a real VM is
#     running -- genuinely busy, keep waiting exactly as before. Only
#     WindowsSandboxServer/Client/RemoteSession present, with NO
#     vmmemWindowsSandbox for -OrphanGraceMinutes (default 10 -- a real
#     launch spawns vmmemWindowsSandbox within seconds to a couple of
#     minutes of the server process, so that many minutes of continuous
#     vmmem absence is not something a live launch produces), is classified
#     ORPHAN: it writes output\SANDBOX-ORPHAN.txt with the full evidence and
#     PROCEEDS to launch -- a stale leftover server process does not hold
#     the machine-wide single-instance slot the way a real VM does, so it
#     does not block a new session. If the launch then genuinely collides
#     with something this guard could not see, the existing "no VM process a
#     few seconds after launch" failure path (exit 1, below) reports that
#     honestly; this guard never overrides it.
#
#     PROCEED-NOT-KILL, always: this guard NEVER calls Stop-Process against
#     any PID it merely observed here, orphan or not -- only this script's
#     own teardown (step 5, far below) stops processes, and only the PIDs
#     THIS run recorded as its own right after its own Start-Process call.
#     An orphan classification changes whether this script waits before
#     launching; it never authorizes touching a process this run did not
#     start.
$waitLogPath = Join-Path $OutDir 'SANDBOX-WAIT.txt'
$orphanMarkerPath = Join-Path $OutDir 'SANDBOX-ORPHAN.txt'

function Get-SandboxBusyEvidence {
    <#
      One evidence snapshot for the busy guard: every $SandboxProcessNames
      process currently running, split into vmmemWindowsSandbox (the actual
      VM) and everything else (server/client/remote-session shells, which
      can legitimately outlive the VM during teardown -- see
      <gate-a-teardown-drain> above -- or be left behind as an orphan when a
      teardown never finished draining).
    #>
    $all = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
    $vmmem = @($all | Where-Object { $_.ProcessName -eq 'vmmemWindowsSandbox' })
    $other = @($all | Where-Object { $_.ProcessName -ne 'vmmemWindowsSandbox' })
    [PSCustomObject]@{
        All        = $all
        Vmmem      = $vmmem
        Other      = $other
        VmmemAlive = ($vmmem.Count -gt 0)
    }
}

function Format-SandboxProcessEvidence {
    <# Human-readable pid/name/working-set/start-time evidence line, used both
       in SANDBOX-WAIT.txt's periodic log and in SANDBOX-ORPHAN.txt. #>
    param([object[]]$Procs)
    if (-not $Procs -or $Procs.Count -eq 0) { return '<none>' }
    ($Procs | ForEach-Object {
        $startUtc = try { $_.StartTime.ToUniversalTime().ToString('o') } catch { 'unknown' }
        $wsMb = [Math]::Round($_.WorkingSet64 / 1MB, 1)
        "pid=$($_.Id) name=$($_.ProcessName) ws_mb=$wsMb start_utc=$startUtc"
    }) -join '; '
}

$evidence = Get-SandboxBusyEvidence
if ($evidence.All.Count -gt 0) {
    Write-Warning "Windows Sandbox process(es) already present: $(Format-SandboxProcessEvidence $evidence.All). It is a SHARED single-instance resource on this machine -- gathering evidence (vmmemWindowsSandbox present = genuinely busy; absent for >= $OrphanGraceMinutes minute(s) = orphan, proceed) rather than waiting blind."
    $waitDeadline = (Get-Date).AddMinutes($SandboxWaitMinutes)
    $lastLogTime = [DateTime]::MinValue
    $logIntervalSeconds = 120
    # Seeded from the OLDEST currently-present non-vmmem process's own start
    # time, the first poll that finds vmmem absent -- not from "now" -- so an
    # already-hours-old orphan (exactly run 32930110802's shape: PID 17548
    # started hours before this guard ever looked at it) is classified from
    # this run's very first evidence read instead of forcing every future
    # run to burn a fresh -OrphanGraceMinutes wait on top of an already-stale
    # process. Reset to $null the instant vmmemWindowsSandbox is observed, so
    # a genuine in-flight launch (server process visible a moment before its
    # own VM spawns) is never mistaken for an orphan.
    $orphanSinceUtc = $null
    $orphanMinutes = 0
    $orphanDetected = $false

    while (((Get-Date) -lt $waitDeadline) -and $evidence.All.Count -gt 0) {
        $now = Get-Date

        if ($evidence.VmmemAlive) {
            $orphanSinceUtc = $null
        } else {
            if (-not $orphanSinceUtc) {
                $oldestOther = @($evidence.Other | Sort-Object StartTime | Select-Object -First 1)
                if ($oldestOther.Count -gt 0) {
                    try { $orphanSinceUtc = $oldestOther[0].StartTime.ToUniversalTime() } catch { $orphanSinceUtc = $now.ToUniversalTime() }
                } else {
                    $orphanSinceUtc = $now.ToUniversalTime()
                }
            }
            $orphanMinutes = ((Get-Date).ToUniversalTime() - $orphanSinceUtc).TotalMinutes
            if ($orphanMinutes -ge $OrphanGraceMinutes) {
                $orphanDetected = $true
                break
            }
        }

        if (($now - $lastLogTime).TotalSeconds -ge $logIntervalSeconds) {
            $vmmemDetail = if ($evidence.VmmemAlive) { Format-SandboxProcessEvidence $evidence.Vmmem } else { '<absent>' }
            $orphanNote = if ($evidence.VmmemAlive) { 'vmmem_alive=true (genuinely busy)' } else { "vmmem_alive=false orphan_minutes=$([Math]::Round($orphanMinutes, 1)) grace_minutes=$OrphanGraceMinutes" }
            Add-Content -Path $waitLogPath -Value "$($now.ToString('o')) waiting -- other=[$(Format-SandboxProcessEvidence $evidence.Other)] vmmem=[$vmmemDetail] $orphanNote" -Encoding UTF8
            $lastLogTime = $now
        }

        Start-Sleep -Seconds 30
        $evidence = Get-SandboxBusyEvidence
    }

    if ($orphanDetected) {
        $orphanBody = @(
            "orphan_detected_utc=$((Get-Date).ToUniversalTime().ToString('o'))",
            "orphan_since_utc=$($orphanSinceUtc.ToString('o'))",
            "orphan_minutes=$([Math]::Round($orphanMinutes, 1))",
            "grace_minutes=$OrphanGraceMinutes",
            "other_processes: $(Format-SandboxProcessEvidence $evidence.Other)",
            "vmmem_processes: $(Format-SandboxProcessEvidence $evidence.Vmmem)",
            "reason=WindowsSandbox server/client process(es) present with no vmmemWindowsSandbox (the actual VM) for at least $OrphanGraceMinutes minute(s) -- a real launch spawns vmmemWindowsSandbox within seconds to a couple of minutes, so this is a leftover from a prior run's teardown, not another party's live session.",
            "action=proceeding with launch WITHOUT stopping the orphaned process(es) -- proceed-not-kill; if this collides with something this guard could not see, the existing post-launch VM check reports that honestly."
        ) -join [Environment]::NewLine
        Set-Content -Path $orphanMarkerPath -Value $orphanBody -Encoding UTF8
        Add-Content -Path $waitLogPath -Value "$((Get-Date).ToString('o')) classified ORPHAN after $([Math]::Round($orphanMinutes, 1)) minute(s) with no vmmemWindowsSandbox -- proceeding to launch. See SANDBOX-ORPHAN.txt." -Encoding UTF8
        Write-Warning "Windows Sandbox process(es) present but no vmmemWindowsSandbox for >= $OrphanGraceMinutes minute(s) (other=[$(Format-SandboxProcessEvidence $evidence.Other)]) -- classified ORPHAN, not busy. Wrote $orphanMarkerPath. Proceeding to launch WITHOUT touching the orphaned process(es)."
    } elseif ($evidence.All.Count -gt 0) {
        $finalLine = "$((Get-Date).ToString('o')) still busy after ${SandboxWaitMinutes}m wait -- giving up. other=[$(Format-SandboxProcessEvidence $evidence.Other)] vmmem=[$(Format-SandboxProcessEvidence $evidence.Vmmem)]"
        Add-Content -Path $waitLogPath -Value $finalLine -Encoding UTF8
        Set-Content -Path (Join-Path $OutDir 'SANDBOX-BUSY.txt') -Value $finalLine -Encoding UTF8
        Write-Warning "Windows Sandbox is still busy after waiting $SandboxWaitMinutes minute(s). Not launching -- this is a shared resource owned by another process (vmmemWindowsSandbox observed), not ours to touch. Exiting cleanly (code 3) without starting or stopping anything."
        exit 3
    } else {
        Add-Content -Path $waitLogPath -Value "$((Get-Date).ToString('o')) sandbox became free -- proceeding to launch." -Encoding UTF8
        Write-Host "Windows Sandbox is now free. Proceeding with launch." -ForegroundColor Green
    }
}

# 2. Launch Windows Sandbox with the .wsb config. WindowsSandbox.exe opens the
#    config and starts the VM; it returns once the sandbox window is up (it
#    does not block for the LogonCommand to finish).
Write-Host "Launching Windows Sandbox ($WsbPath)..."
Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList "`"$WsbPath`"" | Out-Null
# NOTE: WindowsSandbox.exe is a launcher stub -- it starts the VM (vmwp.exe /
# WindowsSandboxServer.exe / WindowsSandboxRemoteSession.exe) and exits almost
# immediately by design. Its own exit code/HasExited is NOT a signal of
# success or failure; the real VM lifecycle is tracked by those child
# processes and, ultimately, by the DONE.json marker below.
Start-Sleep -Seconds 5
$vmAlive = Get-Process -Name 'WindowsSandboxRemoteSession', 'WindowsSandboxServer', 'vmwp' -ErrorAction SilentlyContinue
if (-not $vmAlive) {
    Write-Error "No Windows Sandbox VM process found running a few seconds after launch. Sandbox feature may not be enabled, or the .wsb failed to parse."
    exit 1
}
Write-Host "Windows Sandbox VM is running (PID(s): $(($vmAlive | Select-Object -ExpandProperty Id) -join ', ')). Waiting for in-sandbox report to finish (timeout ${TimeoutMinutes}m)..."

# Record THIS run's own sandbox process PIDs, right after our own launch, for
# a safe teardown below. The busy-guard above already proved no sandbox
# process of any of these names was running immediately before this script
# launched one, and Windows Sandbox is strictly single-instance system-wide,
# so every PID captured here belongs to the VM this script just started --
# never to some other, independent process. Teardown stops only these
# recorded PIDs, never a blanket stop-by-name.
$launchedProcs = Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue
$launchedPids = @($launchedProcs | Select-Object -ExpandProperty Id)
Write-Host "Recorded this run's own sandbox process PID(s) for teardown: $(if ($launchedPids.Count -gt 0) { $launchedPids -join ', ' } else { '<none yet>' })"

# 3. Poll for the done-marker. This is the authoritative completion signal --
#    unlike the old manual Watch-Run.ps1 monitor (kept in scripts/ for
#    interactive debugging only), this loop does not declare done on an
#    intermediate result line; it waits for DONE.json itself, up to the
#    timeout.
function Get-NewestOutputActivityUtc {
    # Newest write anywhere under output\, or $null if the folder is empty.
    # The in-sandbox shipper touches _SHIPPER-HEARTBEAT.txt on every tick,
    # so on a live run this advances continuously even between evidence
    # files. Best-effort: a transient enumeration failure while the guest
    # is mid-write must not be mistaken for a quiet share, so it returns
    # $null and the caller simply keeps the previous reading.
    try {
        $newest = Get-ChildItem -Path $OutDir -Recurse -File -Force -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if ($newest) { return $newest.LastWriteTimeUtc }
    } catch {}
    return $null
}

function Test-DirectoryHandlesFree {
    <#
      Probe whether a directory is free of open handles by renaming it away
      and back -- the exact operation ("rmdir"/rename of the directory
      itself) that failed with EBUSY on run 32929704614's checkout. A
      write-a-file-inside probe would not catch a handle held on the
      directory object itself (e.g. a read-only MappedFolder like
      sandbox-lab\scripts, which VSMB still opens a handle on even though
      the guest cannot write to it), so this renames the directory, not a
      file inside it.

      Returns $true if the directory doesn't exist (nothing to drain) or the
      rename round-trip succeeded; $false if either rename failed. Best-
      effort restores the original name before returning false so a failed
      probe never leaves the tree in a renamed state.
    #>
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $true }
    $parent = Split-Path -Parent $Path
    $leaf = Split-Path -Leaf $Path
    $probeLeaf = "$leaf.drain-probe-$([guid]::NewGuid().ToString('N'))"
    $probePath = Join-Path $parent $probeLeaf
    try {
        Rename-Item -LiteralPath $Path -NewName $probeLeaf -ErrorAction Stop
    } catch {
        return $false
    }
    try {
        Rename-Item -LiteralPath $probePath -NewName $leaf -ErrorAction Stop
        return $true
    } catch {
        # The away-rename succeeded but the rename-back failed -- try once
        # more before giving up, so a transient hiccup doesn't strand the
        # directory under its probe name.
        Start-Sleep -Milliseconds 500
        try {
            Rename-Item -LiteralPath $probePath -NewName $leaf -ErrorAction Stop
        } catch {
            Write-Warning "Teardown-drain probe could not rename $probePath back to $leaf -- left renamed for manual recovery: $_"
        }
        return $false
    }
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$found = $false
$quietShare = $false
# Seeded from the launch stamp this script just wrote, so the quiet-share
# clock starts at a real, known-good write rather than at $null.
$lastActivityUtc = $launchStamp.ToUniversalTime()
$lastActivitySeenAt = Get-Date
$quietDetail = $null

while ((Get-Date) -lt $deadline) {
    if (Test-Path $DoneMarker) {
        $found = $true
        break
    }

    $activity = Get-NewestOutputActivityUtc
    if ($activity -ne $null -and $activity -gt $lastActivityUtc) {
        $lastActivityUtc = $activity
        $lastActivitySeenAt = Get-Date
    }

    $quietMinutes = ((Get-Date) - $lastActivitySeenAt).TotalMinutes
    if ($quietMinutes -ge $QuietShareMinutes) {
        # Liveness of OUR OWN VM, by the PIDs recorded right after our own
        # launch -- consistent with this script's shared-resource discipline
        # (never reason about, or act on, a sandbox process we did not
        # start). Falls back to the name check only if no PID was captured.
        if ($launchedPids.Count -gt 0) {
            $vm = @(Get-Process -Id $launchedPids -ErrorAction SilentlyContinue)
        } else {
            $vm = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
        }
        $vmAliveNow = ($vm.Count -gt 0)
        $quietDetail = "quiet_minutes=$([Math]::Round($quietMinutes, 1)) threshold_minutes=$QuietShareMinutes last_output_write_utc=$($lastActivityUtc.ToString('o')) vm_alive=$vmAliveNow"
        $quietShare = $true
        break
    }

    Start-Sleep -Seconds 10
}

if ($quietShare) {
    # Distinguish a broken evidence channel from a product failure. This
    # marker is what makes gate_a_verdict.py report HARNESS_ERROR instead of
    # FAIL, and it is written on the HOST's own real disk -- the one write
    # in this whole system that cannot be affected by the wedged share.
    $markerBody = @(
        "host_quiet_share_utc=$((Get-Date).ToUniversalTime().ToString('o'))",
        $quietDetail,
        "reason=nothing under output\ changed for at least $QuietShareMinutes minutes while the sandbox VM was alive -- the in-sandbox shipper's ~25s heartbeat never arrived, so the guest-to-host mapped-folder channel (or the guest itself) is wedged",
        "verdict_class=harness-error (NOT a station-acceptance FAIL -- no product conclusion can be drawn from a run whose evidence never reached the host)"
    ) -join [Environment]::NewLine
    Set-Content -Path $QuietShareMarker -Value $markerBody -Encoding UTF8
    Write-Warning "Mapped output folder went quiet: $quietDetail"
    Write-Warning "Declared a HARNESS ERROR (not a station-acceptance FAIL) and wrote $QuietShareMarker."
    Write-Warning "Leaving the sandbox window open for manual inspection -- the guest's own local evidence dir (C:\CivicCastLocalOut inside the VM) may still be intact."
    # Exit 4, NOT 3: 3 already means "gave up waiting for a busy sandbox and
    # never launched" (see the busy guard above). Two different harness
    # conditions must not share an exit code -- one means the run never
    # started, the other that it started and lost its evidence channel.
    exit 4
}

if (-not $found) {
    Write-Warning "Timed out after $TimeoutMinutes minutes waiting for $DoneMarker."
    Write-Warning "Sandbox may still be running (e.g. blocked on a UAC dialog or a long extraction). Leaving the sandbox window open for manual inspection."
    if (Test-Path (Join-Path $OutDir '_BEFORE_INSTALL.marker')) {
        Write-Host "Evidence: installer launch WAS reached before the timeout (_BEFORE_INSTALL.marker present)."
    } else {
        Write-Host "Evidence: installer launch was NOT reached before the timeout (_BEFORE_INSTALL.marker absent)."
    }
    exit 2
}

Write-Host "Done-marker found. Sandbox report completed." -ForegroundColor Green

# 4. Read and print the summary.
if (Test-Path $SummaryPath) {
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    $summary | ConvertTo-Json -Depth 8 | Write-Host
} else {
    Write-Warning "DONE.json present but summary.json is missing at $SummaryPath."
}

# 5. Close the sandbox VM (it does not auto-close after LogonCommand exits).
#    HARDENED 2026-08-24: only stop processes whose PID this run itself
#    recorded right after its own launch ($launchedPids above) -- never a
#    blanket Stop-Process by name. If that list is empty or none of its PIDs
#    are still alive under a sandbox process name (stale), log it and leave
#    everything alive rather than guessing.
Write-Host ""
Write-Host "Closing the Sandbox VM..."
if ($launchedPids.Count -gt 0) {
    $currentSandboxProcs = Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue
    $ownProcs = $currentSandboxProcs | Where-Object { $launchedPids -contains $_.Id }
    if ($ownProcs) {
        $ownPidList = ($ownProcs | Select-Object -ExpandProperty Id) -join ', '
        Write-Host "Stopping this run's own sandbox process(es) (PID(s): $ownPidList)..."
        $ownProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    } else {
        Write-Warning "None of this run's recorded sandbox PID(s) ($($launchedPids -join ', ')) are still running under a sandbox process name -- nothing to stop (already exited, or the PID list is stale). Leaving any other sandbox processes untouched."
    }
} else {
    Write-Warning "No sandbox PID(s) were recorded for this run -- leaving any running sandbox processes untouched rather than stopping by process name."
}

# 6. Drain the teardown before returning control. See the
#    <gate-a-teardown-drain> header comment at the top of this file for the
#    observed failure this fixes.
#
#    Ownership guard: only wait on a sandbox VM if THIS invocation actually
#    launched one. That is exactly the $launchedPids.Count -gt 0 condition
#    below -- every other exit path in this script (the busy guard's exit 3,
#    the quiet-share detector's exit 4, and the plain-timeout exit 2) returns
#    before this point, so this code is unreachable on a run that never
#    launched a sandbox or that never confirmed its own launch. A run that
#    took the busy-guard path never touches vmmemWindowsSandbox at all -- it
#    belongs to the other party sharing this box, exactly as that guard's own
#    header documents.
if ($launchedPids.Count -gt 0) {
    Write-Host ""
    Write-Host "Draining sandbox teardown (bounded ${TeardownDrainSeconds}s) before returning control..."
    $drainDeadline = (Get-Date).AddSeconds($TeardownDrainSeconds)
    $drained = $false
    $lastDrainDetail = $null
    while ($true) {
        $stillAlive = @(Get-Process -Id $launchedPids -ErrorAction SilentlyContinue)
        $vmGone = ($stillAlive.Count -eq 0)

        $handlesFree = $true
        $busyFolder = $null
        foreach ($folder in $mappedHostFolders) {
            if (-not (Test-DirectoryHandlesFree -Path $folder)) {
                $handlesFree = $false
                $busyFolder = $folder
                break
            }
        }

        if ($vmGone -and $handlesFree) {
            $drained = $true
            break
        }

        $lastDrainDetail = "vm_gone=$vmGone handles_free=$handlesFree busy_folder=$busyFolder remaining_pids=$(($stillAlive | Select-Object -ExpandProperty Id) -join ', ')"
        if ((Get-Date) -ge $drainDeadline) { break }
        Start-Sleep -Seconds $TeardownDrainPollSeconds
    }

    if ($drained) {
        Write-Host "Teardown drain complete -- VM process gone and all mapped folders confirmed free of handles." -ForegroundColor Green
    } else {
        # Runner hygiene only. The product verdict was already decided above
        # (or, on a non-zero exit path, is decided by Run-GateA.ps1's
        # judge/forensics run against the evidence already copied) -- this
        # marker never changes it, and this script's own exit code stays 0
        # here regardless. It lands in $OutDir so Run-GateA.ps1's
        # unconditional evidence copy (step 6/7 of its own header) carries it
        # into evidence\<source_sha>\<utc-timestamp>\ alongside everything
        # else, without needing a second hook point.
        $timeoutBody = @(
            "teardown_drain_timeout_utc=$((Get-Date).ToUniversalTime().ToString('o'))",
            "bound_seconds=$TeardownDrainSeconds poll_seconds=$TeardownDrainPollSeconds",
            "last_detail: $lastDrainDetail",
            "mapped_folders_probed: $($mappedHostFolders -join '; ')",
            "reason=the sandbox VM and/or its VSMB handles on the mapped folders above were still not released after waiting ${TeardownDrainSeconds}s past Stop-Process -- runner hygiene only, not a station-acceptance finding. A following job's Checkout step may still hit EBUSY; see docs/ops/gate-a.md, 'Teardown drain'."
        ) -join [Environment]::NewLine
        Set-Content -Path (Join-Path $OutDir 'TEARDOWN-DRAIN-TIMEOUT.txt') -Value $timeoutBody -Encoding UTF8
        Write-Warning "Teardown drain timed out after ${TeardownDrainSeconds}s ($lastDrainDetail). Wrote TEARDOWN-DRAIN-TIMEOUT.txt to $OutDir. This is runner hygiene, not a station-acceptance finding -- the verdict above is unaffected."
    }
} else {
    Write-Host "No sandbox PID(s) were recorded for this run -- skipping the teardown drain (nothing this run confirmed launching)."
}

Write-Host "Done. Full evidence (transcript, install-progress.log, summary.json) is in $OutDir" -ForegroundColor Cyan
exit 0

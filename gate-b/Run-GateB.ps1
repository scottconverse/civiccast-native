# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Gate B -- the 24-hour unattended reboot soak, orchestrated from the host.
#
# Provision a persistent Hyper-V VM, install the candidate inside it, put the
# three PEG channels on air, sample every five minutes for 24 hours, REBOOT
# the VM at the halfway mark, prove the station comes back to broadcasting
# with nobody there, TSDuck-verify the egress on both sides of that reboot,
# then hand the whole evidence directory to scripts/gate_b_verdict.py and let
# code decide.
#
# ---------------------------------------------------------------------------
# THE DIVISION OF LABOUR, AND WHY THE HOST ISSUES THE REBOOT
# ---------------------------------------------------------------------------
# The guest agent (scripts/In-Vm-GateB-Agent.ps1) installs, goes on air and
# beats. It is NOT told when the reboot is coming, and it does not perform it.
# The HOST does, with Restart-VM.
#
# That is not an implementation convenience, it is what makes the evidence
# mean anything. A station that reboots itself on a schedule it knows about
# can prepare for it; §12's requirement is that the box survives a reboot,
# which in the field arrives as a power event or a patch cycle, unannounced.
# Issuing it from outside the guest is the closest a VM can get to that, and
# it also gives the harness an unforgeable record of WHEN it happened
# (REBOOT-RESULT.txt) that the guest could not have written for itself.
#
# ---------------------------------------------------------------------------
# EVIDENCE MOVES BY PULL, NEVER BY PUSH
# ---------------------------------------------------------------------------
# The host copies evidence OUT of the VM over PowerShell Direct on its own
# schedule. The guest never writes into anything the host owns. See
# Provision-GateBVm.ps1's header for the full argument; the short version is
# that Gate A's push-through-a-mapped-folder design cost it three silent hangs
# and a measured install slowdown, and a 24-hour run cannot absorb that class
# of failure. Every pull is bounded and retried; a pull that fails is logged
# and the next one is attempted, because one bad pull is not a reason to end a
# soak that is otherwise running fine.
#
# ---------------------------------------------------------------------------
# EXIT CODES (same three-value contract as Gate A's Run-GateA.ps1)
# ---------------------------------------------------------------------------
#   0  PASS
#   1  FAIL -- a real reboot-soak finding; see gate-b-verdict.json
#   2  NOT A FINDING AT ALL: Hyper-V unavailable (HYPERV_UNAVAILABLE), a host
#      error or a lost VM (HARNESS_ERROR), bad inputs, or a missing judge.
#      None of these is ever a statement about the candidate.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$KitDir,

    [Parameter(Mandatory = $true)]
    [string]$GuestCredentialPath,

    [string]$BaseVhdx,
    [string]$WindowsIso,

    [string]$SourceSha,
    [string]$RunId,

    [string]$Root = $PSScriptRoot,
    [string]$VmName = 'CivicCastGateB',
    [string]$VmRoot = 'C:\CivicCastGateB',

    # The plan. Defaults ARE the §12 floor: 24h, reboot at the halfway mark,
    # 5-minute beats. gate_b_verdict.py's `plan` check refuses anything below
    # this floor, so a shorter run is honestly reported as a FAIL rather than
    # quietly graded as if it were the real thing -- which is exactly what
    # makes -SoakMinutes safe to expose for rehearsals.
    [int]$SoakMinutes = 1440,
    [int]$BeatIntervalMinutes = 5,
    [int]$RebootAtMinutes = 720,
    [int]$RebootGapBudgetMinutes = 20,
    [int]$RecoveryBudgetMinutes = 15,
    [int]$BeatSlackMinutes = 2,

    # How often the host pulls evidence out of the VM. Frequent enough that a
    # VM lost at hour 23 still yields 23 hours of beats; infrequent enough
    # that the pull is nowhere near the station's critical path.
    [int]$EvidencePullMinutes = 30,

    # The host's own outer bound: 25 hours. It must EXCEED the 1440-minute
    # soak (so the harness never kills the run it is supervising) and must
    # stay STRICTLY BELOW the workflow's 1560-minute job timeout (so this
    # script is always the first bound to fire and always gets to write its
    # verdict -- a job GitHub kills produces no verdict document at all, only
    # a red X). Equal values would be a coin toss between the two, which is
    # the same class of mistake as Gate A's watchdog once outliving its host
    # poll deadline. See docs/ops/gate-b.md, "Budget ordering";
    # tests/gate_b/test_gate_b_harness_contract.py asserts the strict
    # ordering so it cannot drift back.
    [int]$HostDeadlineMinutes = 1500,

    [int]$InstallTimeoutMinutes = 120,
    [int]$GuestReadyMinutes = 30,

    [switch]$ReuseExistingVm
)

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $Root
$UtcStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
if (-not $SourceSha) { $SourceSha = 'unknown-local' }
$EvidenceDir = Join-Path $Root "evidence\$SourceSha\$UtcStamp"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

$HostLog = Join-Path $EvidenceDir 'gate-b-host.log'

function Write-HostLog {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date).ToUniversalTime().ToString('o'), $Message
    Write-Host $line
    try { $line | Add-Content -LiteralPath $HostLog -Encoding UTF8 } catch { }
}

function Exit-NotAFinding {
    <#
        Every path that is NOT a statement about the candidate ends here:
        write the marker the judge keys on, run the judge anyway so the
        evidence directory always carries a verdict document, and exit 2.
    #>
    param(
        [string]$Marker,
        [string]$Message
    )
    Write-HostLog "NOT-A-FINDING: $Message"
    if ($Marker) {
        $Message | Set-Content -LiteralPath (Join-Path $EvidenceDir $Marker) -Encoding UTF8
    }
    Invoke-Judge | Out-Null
    exit 2
}

function Invoke-Judge {
    $judge = Join-Path $RepoRoot 'scripts\gate_b_verdict.py'
    if (-not (Test-Path -LiteralPath $judge)) {
        Write-HostLog "judge not found at $judge -- no verdict can be produced"
        return $null
    }
    $verdictPath = Join-Path $EvidenceDir 'gate-b-verdict.json'
    $runIdArg = $RunId
    if (-not $runIdArg) { $runIdArg = '' }
    & uv run --project $RepoRoot python $judge $EvidenceDir --source-sha $SourceSha --run-id "$runIdArg" --out $verdictPath
    $script:JudgeExit = $LASTEXITCODE
    Write-HostLog "judge exit code: $script:JudgeExit"
    return $verdictPath
}

Write-HostLog "gate-b run starting: sha=$SourceSha run_id=$RunId evidence=$EvidenceDir"

# --- The declared plan, written FIRST -------------------------------------
# Written before anything can fail, so even a run that dies during
# provisioning carries the plan it intended to execute. The judge grades
# against this document, not against its own defaults.
$runDoc = [ordered]@{
    schema        = 'civiccast-gate-b-run-v1'
    run_started_utc = (Get-Date).ToUniversalTime().ToString('o')
    source_sha    = $SourceSha
    run_id        = $RunId
    vm_name       = $VmName
    kit_dir       = $KitDir
    plan          = [ordered]@{
        soak_minutes              = $SoakMinutes
        beat_interval_minutes     = $BeatIntervalMinutes
        reboot_at_minutes         = $RebootAtMinutes
        reboot_gap_budget_minutes = $RebootGapBudgetMinutes
        recovery_budget_minutes   = $RecoveryBudgetMinutes
        beat_slack_minutes        = $BeatSlackMinutes
    }
    host_deadline_minutes = $HostDeadlineMinutes
    evidence_pull_minutes = $EvidencePullMinutes
}
$runDoc | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'gate-b-run.json') -Encoding UTF8

if ($SoakMinutes -lt 1440) {
    Write-Warning "SoakMinutes=$SoakMinutes is below the 3.0 MASTER spec §12 floor of 1440. This run is a REHEARSAL: gate_b_verdict.py will report FAIL on its `plan` check, by design."
}

# --- Prerequisites: Hyper-V, before anything else -------------------------
$prereq = Join-Path $Root 'Test-GateBPrereqs.ps1'
& $prereq -OutDir $EvidenceDir | Out-Null
$prereqExit = $LASTEXITCODE
if ($prereqExit -ne 0) {
    # Test-GateBPrereqs.ps1 has already written HYPERV-UNAVAILABLE.txt into
    # the evidence directory with the one command that fixes it. The judge
    # turns that marker into HYPERV_UNAVAILABLE -- never a FAIL.
    Write-HostLog "Hyper-V prerequisites not satisfied (exit $prereqExit); see HYPERV-UNAVAILABLE.txt"
    Invoke-Judge | Out-Null
    exit 2
}
Import-Module Hyper-V -ErrorAction SilentlyContinue

# --- Provision ------------------------------------------------------------
$provisionArgs = @{
    GuestCredentialPath = $GuestCredentialPath
    KitDir              = $KitDir
    VmName              = $VmName
    VmRoot              = $VmRoot
    GuestReadyMinutes   = $GuestReadyMinutes
}
if ($BaseVhdx) {
    $provisionArgs['BaseVhdx'] = $BaseVhdx
} elseif ($WindowsIso) {
    $provisionArgs['WindowsIso'] = $WindowsIso
} else {
    Exit-NotAFinding -Marker 'GATE-B-HOST-ERROR.txt' -Message "neither -BaseVhdx nor -WindowsIso was supplied. Gate B needs a Windows image to build its VM from; see docs/ops/gate-b.md, 'What the operator must supply'."
}
if ($ReuseExistingVm) { $provisionArgs['ReuseExistingVm'] = $true }

Write-HostLog "provisioning VM '$VmName'"
& (Join-Path $Root 'Provision-GateBVm.ps1') @provisionArgs
if ($LASTEXITCODE -ne 0) {
    Exit-NotAFinding -Marker 'GATE-B-HOST-ERROR.txt' -Message "Provision-GateBVm.ps1 exited $LASTEXITCODE; no VM to soak. See gate-b-host.log."
}

$guestCredential = Import-CliXml -LiteralPath $GuestCredentialPath

function New-GuestSession {
    <#
        A fresh PowerShell Direct session, retried across the window a reboot
        occupies. Sessions do NOT survive the guest restarting, so every
        caller gets a new one rather than holding one open -- a held session
        across a reboot is a broken session the code would then have to
        detect, which is more moving parts than simply not holding one.
    #>
    param([int]$TimeoutMinutes = 5)

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        try {
            return New-PSSession -VMName $VmName -Credential $guestCredential -ErrorAction Stop
        } catch {
            Start-Sleep -Seconds 10
        }
    }
    return $null
}

function Copy-EvidenceFromGuest {
    <#
        Pull the guest's evidence directory to the host. Bounded and
        non-fatal: a failed pull is logged and the run continues, because the
        next pull is 30 minutes away and the beats it will carry include the
        ones this pull missed (beats.jsonl is append-only and copied whole).

        state.json is NEVER pulled. It holds the station admin credential the
        agent generated for its own post-reboot login, and evidence
        directories become CI artifacts.
    #>
    param([string]$Label)

    $session = New-GuestSession -TimeoutMinutes 3
    if (-not $session) {
        Write-HostLog "evidence pull ($Label): no guest session; skipping this pull"
        return $false
    }
    try {
        foreach ($name in @('beats.jsonl', 'summary.json', 'ACTIVATION-RESULT.txt', 'DONE.json',
                            'agent.log', 'STATION-UP-WAIT.txt', 'station-auth.log',
                            'channel-start.log', 'AGENT-INSTALL-FAILED.txt')) {
            $remote = "C:\CivicCastGateB\out\$name"
            $exists = Invoke-Command -Session $session -ScriptBlock { param($p) Test-Path -LiteralPath $p } -ArgumentList $remote
            if (-not $exists) { continue }
            try {
                Copy-Item -FromSession $session -LiteralPath $remote -Destination (Join-Path $EvidenceDir $name) -Force -ErrorAction Stop
            } catch {
                Write-HostLog "evidence pull ($Label): $name failed: $_"
            }
        }
        # The supervisor's own logs -- the second, independent instrument for
        # the no_unplanned_restarts check.
        $logsDir = Join-Path $EvidenceDir 'supervisor-logs'
        New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
        $remoteLogs = Invoke-Command -Session $session -ScriptBlock {
            $root = Join-Path $env:ProgramData 'CivicCast\logs'
            if (-not (Test-Path -LiteralPath $root)) { return @() }
            return @(Get-ChildItem -LiteralPath $root -Filter '*.log' -File -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName)
        }
        foreach ($remoteLog in @($remoteLogs)) {
            try {
                Copy-Item -FromSession $session -LiteralPath $remoteLog -Destination $logsDir -Force -ErrorAction Stop
            } catch {
                Write-HostLog "evidence pull ($Label): supervisor log $remoteLog failed: $_"
            }
        }
        Write-HostLog "evidence pull ($Label) complete"
        return $true
    } finally {
        Remove-PSSession $session -ErrorAction SilentlyContinue
    }
}

function Invoke-EgressVerify {
    <#
        Run the EXISTING TSDuck verifier inside the guest and pull its report.

        sandbox-lab/soak-4h/scripts/verify-egress.ps1 is reused byte-for-byte
        rather than reimplemented. It listens on 127.0.0.1:9001/9002/9003 and
        analyses whatever arrives, so it is engine-agnostic by construction --
        which is precisely what lets it serve as evidence about the product
        GStreamer engine even though it was written for the ffmpeg-driven 4h
        soak. Reimplementing it would mean two TSDuck pass/fail definitions in
        one repository, and eventually two answers.
    #>
    param([string]$OutName, [int]$Seconds = 15)

    $session = New-GuestSession -TimeoutMinutes 5
    if (-not $session) {
        Write-HostLog "egress verify ($OutName): no guest session"
        return $false
    }
    try {
        $result = Invoke-Command -Session $session -ScriptBlock {
            param($seconds)
            $env:RUN_ROOT = 'C:\CivicCastGateB\egress'
            New-Item -ItemType Directory -Force -Path $env:RUN_ROOT | Out-Null
            $script = 'C:\CivicCastGateB\scripts\verify-egress.ps1'
            if (-not (Test-Path -LiteralPath $script)) { return @{ ok = $false; detail = 'verifier not staged in the guest' } }
            $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -HeartbeatIndex 1 -Seconds $seconds -Stamp $stamp *> 'C:\CivicCastGateB\egress\verify.log'
            $artifact = Join-Path $env:RUN_ROOT "egress-verify\egress-verify-$stamp.json"
            if (-not (Test-Path -LiteralPath $artifact)) { return @{ ok = $false; detail = "no artifact at $artifact" } }
            return @{ ok = $true; path = $artifact }
        } -ArgumentList $Seconds
        if (-not $result.ok) {
            Write-HostLog "egress verify ($OutName) produced no artifact: $($result.detail)"
            return $false
        }
        Copy-Item -FromSession $session -LiteralPath $result.path -Destination (Join-Path $EvidenceDir $OutName) -Force -ErrorAction Stop
        Write-HostLog "egress verify ($OutName) captured"
        return $true
    } catch {
        Write-HostLog "egress verify ($OutName) failed: $_"
        return $false
    } finally {
        Remove-PSSession $session -ErrorAction SilentlyContinue
    }
}

# --- Stage the harness into the guest and start the agent -----------------
Write-HostLog "staging the harness into the guest"
$session = New-GuestSession -TimeoutMinutes $GuestReadyMinutes
if (-not $session) {
    Exit-NotAFinding -Marker 'GATE-B-HOST-ERROR.txt' -Message "the guest never answered PowerShell Direct after provisioning."
}
try {
    Invoke-Command -Session $session -ScriptBlock {
        New-Item -ItemType Directory -Force -Path 'C:\CivicCastGateB\scripts' | Out-Null
        New-Item -ItemType Directory -Force -Path 'C:\CivicCastGateB\out' | Out-Null
    }
    $staged = @(
        @{ Local = (Join-Path $Root 'scripts\In-Vm-GateB-Agent.ps1');            Remote = 'C:\CivicCastGateB\scripts\In-Vm-GateB-Agent.ps1' }
        @{ Local = (Join-Path $Root 'scripts\Register-GateBStartupTask.ps1');    Remote = 'C:\CivicCastGateB\scripts\Register-GateBStartupTask.ps1' }
        # The SHARED module, not a copy of Gate A's inline code. One
        # install/activation contract, two gates.
        @{ Local = (Join-Path $RepoRoot 'sandbox-lab\common\CivicCastStationHarness.psm1'); Remote = 'C:\CivicCastGateB\scripts\CivicCastStationHarness.psm1' }
        # The EXISTING TSDuck verifier, byte-for-byte.
        @{ Local = (Join-Path $RepoRoot 'sandbox-lab\soak-4h\scripts\verify-egress.ps1');   Remote = 'C:\CivicCastGateB\scripts\verify-egress.ps1' }
    )
    foreach ($item in $staged) {
        if (-not (Test-Path -LiteralPath $item.Local)) {
            Exit-NotAFinding -Marker 'GATE-B-HOST-ERROR.txt' -Message "harness file missing on the host: $($item.Local)"
        }
        Copy-Item -ToSession $session -LiteralPath $item.Local -Destination $item.Remote -Force -ErrorAction Stop
    }
    Write-HostLog "harness staged ($($staged.Count) files)"

    # Launch the agent DETACHED inside the guest. Invoke-Command would block
    # this host script for the whole 24 hours on one VMBus session -- a single
    # point of failure with a day-long window, and the exact "hold one channel
    # open forever" shape the pull design exists to avoid.
    Invoke-Command -Session $session -ScriptBlock {
        param($soak, $interval, $installTimeout)
        $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\CivicCastGateB\scripts\In-Vm-GateB-Agent.ps1"' +
                     " -LaunchedBy bootstrap -SoakMinutes $soak -BeatIntervalMinutes $interval -InstallTimeoutMinutes $installTimeout"
        Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden | Out-Null
    } -ArgumentList $SoakMinutes, $BeatIntervalMinutes, $InstallTimeoutMinutes
    Write-HostLog "agent launched inside the guest (detached)"
} finally {
    Remove-PSSession $session -ErrorAction SilentlyContinue
}

# --- The host's own supervision loop --------------------------------------
$hostStart = (Get-Date).ToUniversalTime()
$hostDeadline = $hostStart.AddMinutes($HostDeadlineMinutes)
$rebootIssued = $false
$rebootIssuedUtc = $null
$preRebootVerified = $false
$postRebootVerified = $false
$nextPull = (Get-Date).AddMinutes($EvidencePullMinutes)
$soakStartUtc = $null

Write-HostLog "host supervision loop: deadline $($hostDeadline.ToString('o'))"

while ((Get-Date).ToUniversalTime() -lt $hostDeadline) {
    Start-Sleep -Seconds 60

    # The VM must exist and be running. Losing it outside the planned reboot
    # ends the run as a HARNESS_ERROR -- a soak the environment cut short
    # supports no conclusion about the candidate.
    $vm = Get-VM -Name $VmName -ErrorAction SilentlyContinue
    if (-not $vm) {
        Copy-EvidenceFromGuest -Label 'vm-lost' | Out-Null
        Exit-NotAFinding -Marker 'VM-LOST.txt' -Message "the VM '$VmName' no longer exists at $((Get-Date).ToUniversalTime().ToString('o'))."
    }
    if ($vm.State -ne 'Running' -and -not ($rebootIssued -and -not $postRebootVerified)) {
        Copy-EvidenceFromGuest -Label 'vm-stopped' | Out-Null
        Exit-NotAFinding -Marker 'VM-LOST.txt' -Message "the VM '$VmName' is in state '$($vm.State)' outside the planned reboot window."
    }

    # Learn the soak's true start from the guest's own state -- the agent
    # starts the clock when the station is BROADCASTING, not when the
    # installer launched, so the host cannot compute the reboot mark from its
    # own wall clock without silently rebooting early by the install's
    # duration.
    if (-not $soakStartUtc) {
        $session = New-GuestSession -TimeoutMinutes 2
        if ($session) {
            try {
                $soakStartUtc = Invoke-Command -Session $session -ScriptBlock {
                    if (-not (Test-Path -LiteralPath 'C:\CivicCastGateB\state.json')) { return $null }
                    try {
                        $state = Get-Content -LiteralPath 'C:\CivicCastGateB\state.json' -Raw | ConvertFrom-Json
                        return $state.soak_start_utc
                    } catch { return $null }
                }
            } finally {
                Remove-PSSession $session -ErrorAction SilentlyContinue
            }
            if ($soakStartUtc) { Write-HostLog "soak clock started at $soakStartUtc (station broadcasting)" }
        }
    }

    if ($soakStartUtc) {
        $elapsed = ((Get-Date).ToUniversalTime() - [datetime]::Parse($soakStartUtc).ToUniversalTime()).TotalMinutes

        # TSDuck, before the reboot.
        if (-not $preRebootVerified -and $elapsed -ge ($RebootAtMinutes - 10)) {
            $preRebootVerified = Invoke-EgressVerify -OutName 'egress-verify-pre-reboot.json'
        }

        # THE REBOOT. §12: "24h unattended soak w/ kill+restart+reboot".
        if (-not $rebootIssued -and $elapsed -ge $RebootAtMinutes) {
            $rebootIssuedUtc = (Get-Date).ToUniversalTime().ToString('o')
            Write-HostLog "issuing the planned reboot at elapsed=$([math]::Round($elapsed,2))m"
            # Restart-VM without -Force asks the guest OS to restart cleanly
            # through the integration services. That is what a patch cycle
            # does; -Force would be a power-cut test, which is a DIFFERENT
            # §12 line ("unclean-restart relay reap") and deserves its own
            # named run rather than being smuggled in here.
            Restart-VM -Name $VmName -Confirm:$false -ErrorAction SilentlyContinue
            $rebootIssued = $true
            @(
                "reboot_issued_utc=$rebootIssuedUtc"
                "reboot_at_minutes_planned=$RebootAtMinutes"
                "reboot_at_minutes_actual=$([math]::Round($elapsed,3))"
                "method=Restart-VM (graceful guest restart via integration services)"
                "operator_interaction=none"
                "soak_start_utc=$soakStartUtc"
            ) -join [Environment]::NewLine |
                Set-Content -LiteralPath (Join-Path $EvidenceDir 'REBOOT-RESULT.txt') -Encoding UTF8
        }

        # TSDuck, after the reboot -- once the recovery budget has had time to
        # elapse, so this samples a recovered station rather than a booting one.
        if ($rebootIssued -and -not $postRebootVerified -and $elapsed -ge ($RebootAtMinutes + $RecoveryBudgetMinutes + 5)) {
            $postRebootVerified = Invoke-EgressVerify -OutName 'egress-verify-post-reboot.json'
        }
    }

    if ((Get-Date) -ge $nextPull) {
        Copy-EvidenceFromGuest -Label 'periodic' | Out-Null
        $nextPull = (Get-Date).AddMinutes($EvidencePullMinutes)
        # Finished? DONE.json on the host means the agent wrote it and the
        # pull carried it across -- the same "DONE.json is the last thing to
        # arrive" contract Gate A uses.
        if (Test-Path -LiteralPath (Join-Path $EvidenceDir 'DONE.json')) {
            Write-HostLog "DONE.json received; the soak has completed"
            break
        }
    }
}

# Final pull, always, whatever ended the loop.
Copy-EvidenceFromGuest -Label 'final' | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $EvidenceDir 'DONE.json'))) {
    Write-HostLog "host deadline reached with no DONE.json"
    "host_deadline_minutes=$HostDeadlineMinutes reached at $((Get-Date).ToUniversalTime().ToString('o')) with no DONE.json from the guest" |
        Set-Content -LiteralPath (Join-Path $EvidenceDir 'WATCHDOG-TIMEOUT.txt') -Encoding UTF8
}

# Stop the VM but do NOT delete it: the next run recreates it from the base
# VHDX anyway, and a stopped VM whose disks are still on disk is the only
# thing a post-mortem has to work with when the evidence does not explain
# what happened.
Write-HostLog "stopping the VM (kept on disk for post-mortem)"
Stop-VM -Name $VmName -Force -ErrorAction SilentlyContinue

$verdictPath = Invoke-Judge
$judgeExit = $script:JudgeExit
Write-HostLog "evidence: $EvidenceDir"
Write-HostLog "verdict:  $verdictPath"

if ($judgeExit -eq 0) { exit 0 }
if ($judgeExit -eq 1) { exit 1 }
exit 2

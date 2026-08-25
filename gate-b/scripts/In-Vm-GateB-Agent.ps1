# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# The Gate B in-VM agent -- installs the candidate, puts three PEG channels on
# air, and then samples the station every five minutes for 24 hours, ACROSS a
# reboot it is not told about in advance.
#
# ---------------------------------------------------------------------------
# THE ONE THING THIS SCRIPT EXISTS TO DO THAT GATE A CANNOT
# ---------------------------------------------------------------------------
# 3.0 MASTER spec §12 requires the release soak to include a reboot, and the
# station-acceptance list requires the box to "survive an unattended reboot".
# Windows Sandbox is destroyed rather than restarted, so Gate A's driver is a
# single long-lived process and can assume it will still be running at the end.
# This agent cannot assume that. It is KILLED by the reboot, mid-soak, with no
# notice, and something has to bring it back with no human present.
#
# So the agent is written as a RESUMABLE state machine, not a script with a
# loop in it:
#
#   * All continuity lives in C:\CivicCastGateB\state.json -- the run id, the
#     soak's true start time, the next beat sequence number, the phase, and
#     the station credential the post-reboot launch needs. Every beat commits
#     it. A process that dies between two beats loses at most the beat it was
#     writing.
#   * Resumption is a scheduled task registered AT STARTUP as SYSTEM
#     (Register-GateBStartupTask.ps1) -- not at logon. At logon would require
#     someone to log in, which is the precise opposite of "unattended".
#   * Beats are APPENDED to beats.jsonl, never rewritten. The host pulls that
#     file whole; a partially-written final line is the host's problem to
#     tolerate (the judge skips blank lines and fails closed on malformed
#     ones), not a reason for the guest to hold a file handle open across a
#     reboot.
#
# ---------------------------------------------------------------------------
# WHY THE POST-REBOOT LAUNCH LOGS IN INSTEAD OF BOOTSTRAPPING
# ---------------------------------------------------------------------------
# The station's staff API is reached with a bearer token obtained from
# POST /api/setup/first-admin, presenting the installer's setup nonce from
# HKLM. That endpoint is FIRST-admin: it works once. After the reboot the
# station already has an admin, so the agent must use POST /api/setup/login
# with the credential it generated before the reboot -- which is why
# state.json carries it.
#
# That credential is a generated, random, throwaway secret for a station that
# exists inside a disposable VM for one day. It is written ONLY to
# C:\CivicCastGateB\state.json inside the guest. Run-GateB.ps1's evidence pull
# explicitly excludes state.json, so it never reaches the host evidence
# directory, the CI artifact, or the verdict. Nothing here reads or writes a
# credential belonging to a human.
#
# Windows PowerShell 5.1 only -- this runs on a stock Windows image where
# pwsh does not exist.

[CmdletBinding()]
param(
    # 'bootstrap'    -- first launch, driven by the host over PowerShell Direct
    # 'startup-task' -- a resume after the reboot, by the at-startup task
    # 'manual'       -- an operator ran it by hand; recorded so the evidence
    #                   never silently claims an attended run was unattended
    [ValidateSet('bootstrap', 'startup-task', 'manual')]
    [string]$LaunchedBy = 'manual',

    [string]$AgentRoot = 'C:\CivicCastGateB',
    [string]$KitVolumeLabel = 'CCKIT',
    [string]$InstallTargetDir = 'C:\CivicCast\install',
    [string]$BaseUrl = 'http://127.0.0.1:8000',

    # Plan. Only consulted on the FIRST launch; afterwards the values recorded
    # in state.json win, so a resume cannot silently re-plan the run it is in
    # the middle of.
    [int]$SoakMinutes = 1440,
    [int]$BeatIntervalMinutes = 5,
    [int]$InstallTimeoutMinutes = 120,
    [int]$StationUpDeadlineMinutes = 30
)

$ErrorActionPreference = 'Continue'

$OutDir = Join-Path $AgentRoot 'out'
$StatePath = Join-Path $AgentRoot 'state.json'
$BeatsPath = Join-Path $OutDir 'beats.jsonl'
$AgentLog = Join-Path $OutDir 'agent.log'

foreach ($dir in @($AgentRoot, $OutDir)) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

function Write-AgentLog {
    param([string]$Message)
    $line = "{0} [{1}] {2}" -f (Get-Date).ToUniversalTime().ToString('o'), $LaunchedBy, $Message
    Write-Host $line
    try { $line | Add-Content -LiteralPath $AgentLog -Encoding UTF8 } catch { }
}

# The shared harness module. It is staged beside this script by Run-GateB.ps1
# so the install/activation contract is one implementation, not two.
$modulePath = Join-Path $PSScriptRoot 'CivicCastStationHarness.psm1'
if (-not (Test-Path -LiteralPath $modulePath)) {
    Write-AgentLog "FATAL: shared harness module not found at $modulePath"
    exit 2
}
Import-Module $modulePath -Force -ErrorAction Stop

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

function Read-AgentState {
    if (-not (Test-Path -LiteralPath $StatePath)) { return $null }
    try {
        return Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-AgentLog "state.json is unreadable ($_) -- refusing to guess; a resume with no state is not a resume"
        return $null
    }
}

function Write-AgentState {
    param([Parameter(Mandatory = $true)] $State)
    # Write-then-rename: a reboot landing in the middle of a state write must
    # not be able to leave a truncated state.json behind, because that is the
    # one file that makes the resume possible at all.
    $temp = "$StatePath.tmp"
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $StatePath -Force
}

function Get-SystemBootUtc {
    # The boot epoch identifier for the whole run. Two beats sharing this
    # value were served by the same boot of the OS; a change is a reboot, and
    # the judge locates the planned reboot by exactly this transition. Uses
    # LastBootUpTime rather than an uptime counter because a counter cannot
    # distinguish "rebooted" from "the agent restarted".
    try {
        return (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime().ToString('o')
    } catch {
        return $null
    }
}

function Test-Unattended {
    # Measured, not asserted. An interactive desktop session runs explorer.exe;
    # a machine nobody has logged into does not. Combined with how this launch
    # was started, that is a real observation the evidence can be wrong about
    # -- which is the point. A run where somebody logged in to poke the station
    # will say so in its own beats.
    if ($LaunchedBy -eq 'manual') { return $false }
    $explorer = @(Get-Process -Name 'explorer' -ErrorAction SilentlyContinue)
    return ($explorer.Count -eq 0)
}

# ---------------------------------------------------------------------------
# Station authentication
# ---------------------------------------------------------------------------

function New-StationPassword {
    $chars = -join (((48..57) + (65..90) + (97..122)) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
    return ($chars + 'Aa1!')
}

function Get-StaffToken {
    <#
        First launch: read the installer's setup nonce from HKLM and POST
        /api/setup/first-admin. Every later launch: POST /api/setup/login with
        the credential we generated then. Returns $null on failure -- the
        caller decides what that means, because "no token" mid-soak and "no
        token" at install time are different findings.
    #>
    param([Parameter(Mandatory = $true)] $State)

    $log = Join-Path $OutDir 'station-auth.log'
    if ($State.admin_username -and $State.admin_password) {
        $body = [ordered]@{ admin_username = $State.admin_username; admin_password = $State.admin_password }
        $response = Invoke-CivicCastApi -Method 'Post' -Url "$BaseUrl/api/setup/login" -LogFile $log -BodyObj $body
        if ($response.status -eq 200 -and $response.body_json) {
            return $response.body_json.operator_console_token
        }
        Write-AgentLog "setup/login failed (status $($response.status)) -- cannot re-authenticate after the reboot"
        return $null
    }

    $nonce = $null
    try {
        $nonce = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\CivicCast\Native' -Name 'SetupNonce' -ErrorAction Stop).SetupNonce
    } catch {
        Write-AgentLog "setup nonce not readable at HKLM:\SOFTWARE\CivicCast\Native\SetupNonce : $_"
    }
    if (-not $nonce) { return $null }

    $password = New-StationPassword
    $body = [ordered]@{
        station_name             = 'Gate B Reboot Soak Station'
        admin_display_name       = 'Gate B Soak Admin'
        admin_username           = 'gatebsoak'
        admin_password           = $password
        recovery_kit_destination = 'gate-b automated 24h reboot soak -- disposable VM, not physically stored'
    }
    $response = Invoke-CivicCastApi -Method 'Post' -Url "$BaseUrl/api/setup/first-admin" -LogFile $log -BodyObj $body -SetupNonce $nonce
    if ($response.status -ne 200 -or -not $response.body_json) {
        Write-AgentLog "first-admin failed (status $($response.status))"
        return $null
    }
    $token = $response.body_json.operator_console_token
    if (-not $token) { return $null }
    # Persist the credential so the POST-REBOOT launch can log in. state.json
    # stays inside the guest; Run-GateB.ps1 never pulls it.
    $State | Add-Member -NotePropertyName 'admin_username' -NotePropertyValue 'gatebsoak' -Force
    $State | Add-Member -NotePropertyName 'admin_password' -NotePropertyValue $password -Force
    Write-AgentState -State $State
    return $token
}

# ---------------------------------------------------------------------------
# The three PEG channels
# ---------------------------------------------------------------------------

# The channel triad and their UDP ports are NOT invented here -- they are the
# ones sandbox-lab/soak-4h/channels.yaml declares and
# sandbox-lab/soak-4h/scripts/verify-egress.ps1 listens on. Gate B reuses that
# verifier unmodified, so it must aim at the same ports it does.
$PegChannels = @(
    @{ channel_id = 'public';     port = 9001; program_number = 1 }
    @{ channel_id = 'education';  port = 9002; program_number = 2 }
    @{ channel_id = 'government'; port = 9003; program_number = 3 }
)

function Start-PegChannels {
    <#
        Configure and start all three channels through the PRODUCT egress
        engine (the staff egress API), never through synthetic ffmpeg
        encoders. Gate A's judge already treats an ffmpeg-fallback egress
        proof as a FAIL because GStreamer is the shipped default engine
        (S15); a 24h soak of a fallback path would prove even less.

        Returns the number of channels that reported themselves started.
    #>
    param([Parameter(Mandatory = $true)] [string]$Token)

    $log = Join-Path $OutDir 'channel-start.log'
    $started = 0
    foreach ($channel in $PegChannels) {
        $id = $channel.channel_id
        $configUrl = "$BaseUrl/api/staff/egress/channels/$id/config"
        $commandsUrl = "$BaseUrl/api/staff/egress/channels/$id/commands"
        $config = [ordered]@{
            channel_id = $id
            enabled    = $true
            sinks      = @(
                [ordered]@{
                    kind = 'udp-ts'
                    name = "$id-headend"
                    uri  = "udp://127.0.0.1:$($channel.port)"
                }
            )
        }
        $put = Invoke-CivicCastApi -Method 'Put' -Url $configUrl -LogFile $log -BodyObj $config -BearerToken $Token
        if ($put.status -ge 400 -or $null -eq $put.status) {
            Write-AgentLog "channel $id config PUT failed (status $($put.status))"
            continue
        }
        $start = Invoke-CivicCastApi -Method 'Post' -Url $commandsUrl -LogFile $log -BodyObj (@{ action = 'start' }) -BearerToken $Token
        if ($start.status -ge 400 -or $null -eq $start.status) {
            Write-AgentLog "channel $id start command failed (status $($start.status))"
            continue
        }
        $started++
    }
    Write-AgentLog "PEG channels started: $started of $($PegChannels.Count)"
    return $started
}

function Get-ChannelSample {
    <#
        One beat's view of the three channels, read from the staff egress
        channel list. 'on_air' is derived from the channel's own state row --
        the row, not the name: a channel appearing in the listing is not a
        channel that is broadcasting, and the judge's §12 "runs the three PEG
        channels concurrently" check is about broadcasting.
    #>
    param([string]$Token)

    $samples = @()
    $response = Invoke-CivicCastApi -Method 'Get' -Url "$BaseUrl/api/staff/egress/channels" -BearerToken $Token -TimeoutSec 20
    $byId = @{}
    if ($response.status -eq 200 -and $response.body_json) {
        foreach ($entry in @($response.body_json)) {
            if ($entry.channel_id) { $byId[[string]$entry.channel_id] = $entry }
        }
    }
    foreach ($channel in $PegChannels) {
        $id = $channel.channel_id
        $onAir = $false
        $stateText = $null
        $engine = $null
        if ($byId.ContainsKey($id)) {
            $entry = $byId[$id]
            try {
                if ($entry.state) {
                    $stateText = [string]$entry.state.status
                    if (-not $stateText) { $stateText = [string]$entry.state.state }
                    $engine = [string]$entry.state.engine
                    # A channel is on air when its state row says it is
                    # running/started AND the config is enabled. Both, because
                    # a disabled channel with a stale running row is neither.
                    $onAir = ($entry.enabled -eq $true) -and
                             ($stateText -match '^(?i)(running|started|on_air|on-air|playing|active)$')
                }
            } catch {
                $stateText = "state-unreadable: $_"
            }
        }
        $samples += [ordered]@{
            channel_id = $id
            udp_port   = $channel.port
            on_air     = $onAir
            state      = $stateText
            engine     = $engine
        }
    }
    return , @($samples)
}

# ---------------------------------------------------------------------------
# Supervisor process sampling -- the primary unplanned-restart instrument
# ---------------------------------------------------------------------------

function Get-SupervisorSample {
    <#
        The supervisor service and every process it is the parent of, by PID
        and creation time.

        This is the PRIMARY instrument for gate_b_verdict's
        no_unplanned_restarts check, and it is deliberately a direct
        observation rather than a log read: the supervisor's own restart
        WARNING is latched per child (it logs once per distinct failure
        detail, not once per attempt), so counting restarts from the log is
        not possible even in principle. A pid that changed between two beats
        within one boot epoch is a restart, full stop.

        Children are found by ParentProcessId rather than by image name --
        the "NEVER kill/match by image name" rule applies just as much to
        measurement as it does to termination, because python.exe on this box
        is not necessarily THIS station's python.exe.
    #>
    $sample = [ordered]@{
        service_state = $null
        service_pid   = -1
        children      = [ordered]@{}
    }
    try {
        $service = Get-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
        $sample.service_state = "$($service.Status)"
    } catch {
        $sample.service_state = 'not-installed'
        return $sample
    }
    try {
        $serviceProcess = Get-CimInstance -ClassName Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction Stop |
            Select-Object -First 1
        if ($serviceProcess -and $serviceProcess.ProcessId -gt 0) {
            $sample.service_pid = [int]$serviceProcess.ProcessId
        }
    } catch {
        # service_pid stays -1, which the judge rejects as a non-int? No: -1
        # IS an int and is a legitimate observation meaning "the service
        # reported no process". It will therefore be compared like any other
        # pid, and a -1 -> real pid transition inside one boot epoch is
        # correctly read as a restart.
        $sample.service_pid = -1
    }
    if ($sample.service_pid -le 0) { return $sample }
    try {
        $children = @(Get-CimInstance -ClassName Win32_Process `
            -Filter "ParentProcessId=$($sample.service_pid)" -ErrorAction Stop)
        # THE KEY MATTERS. The judge detects a restart by finding the SAME key
        # carrying a DIFFERENT pid in a later beat, so the key must be stable
        # across beats and must NOT contain the pid -- keying on
        # "name#<pid>" would make a restart look like one key disappearing and
        # an unrelated new one appearing, i.e. exactly invisible.
        #
        # So: key on the image name, disambiguated by creation order when a
        # station runs more than one child of the same image (it does -- the
        # children are python.exe processes). Collapsing those into one entry
        # by name alone would hide a restart of all but the first.
        $byName = @{}
        foreach ($child in ($children | Sort-Object -Property CreationDate)) {
            $name = [string]$child.Name
            if (-not $byName.ContainsKey($name)) { $byName[$name] = 0 }
            $byName[$name] = [int]$byName[$name] + 1
            $key = $name
            if ($byName[$name] -gt 1) { $key = "$name#$($byName[$name])" }
            $entry = [ordered]@{
                pid       = [int]$child.ProcessId
                name      = $name
                start_utc = $null
            }
            try {
                $entry.start_utc = $child.CreationDate.ToUniversalTime().ToString('o')
            } catch {
                $entry.start_utc = $null
            }
            $sample.children[$key] = $entry
        }
        # Re-key the first of a duplicated name to "<name>#1" so the naming
        # scheme is uniform: a run where a second python.exe appears later
        # must not silently change what "python.exe" means between beats.
        foreach ($name in @($byName.Keys)) {
            if ($byName[$name] -gt 1 -and $sample.children.Contains($name)) {
                $sample.children["$name#1"] = $sample.children[$name]
                $sample.children.Remove($name)
            }
        }
    } catch {
        Write-AgentLog "child process enumeration failed: $_"
    }
    return $sample
}

# ---------------------------------------------------------------------------
# Beats
# ---------------------------------------------------------------------------

function Write-Beat {
    param(
        [Parameter(Mandatory = $true)] $State,
        [string]$Token
    )

    $now = (Get-Date).ToUniversalTime()
    $soakStart = [datetime]::Parse($State.soak_start_utc).ToUniversalTime()
    $elapsed = [math]::Round(($now - $soakStart).TotalMinutes, 3)

    $health = [ordered]@{ http_status = $null; ok = $false; status = $null; schema = $null; mode = $null }
    try {
        $response = Invoke-WebRequest -Uri "$BaseUrl/api/health" -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
        $health.http_status = [int]$response.StatusCode
        $health.ok = ($health.http_status -eq 200)
        try {
            $body = [string]$response.Content | ConvertFrom-Json
            $health.status = [string]$body.status
            $health.schema = [string]$body.schema
            $health.mode = [string]$body.mode
        } catch {
            $health.status = 'unparseable-body'
        }
    } catch {
        $health.http_status = $null
        $health.ok = $false
        $health.status = "unreachable: $($_.Exception.Message)"
    }

    $beat = [ordered]@{
        schema          = 'civiccast-gate-b-beat-v1'
        run_id          = $State.run_id
        beat_seq        = [int]$State.next_beat_seq
        utc             = $now.ToString('o')
        elapsed_minutes = $elapsed
        system_boot_utc = Get-SystemBootUtc
        launched_by     = $LaunchedBy
        unattended      = (Test-Unattended)
        health          = $health
        channels        = (Get-ChannelSample -Token $Token)
        supervisor      = (Get-SupervisorSample)
    }

    # Append, never rewrite. One line, written as one string, so a torn write
    # is a torn LINE that the judge rejects loudly rather than a silently
    # merged pair of beats.
    ($beat | ConvertTo-Json -Depth 8 -Compress) | Add-Content -LiteralPath $BeatsPath -Encoding UTF8

    $State.next_beat_seq = [int]$State.next_beat_seq + 1
    Write-AgentState -State $State
    return $beat
}

# ---------------------------------------------------------------------------
# Phase 1: install + activate + go on air (first launch only)
# ---------------------------------------------------------------------------

function Invoke-InstallPhase {
    param([Parameter(Mandatory = $true)] $State)

    Write-AgentLog "install phase starting"
    Write-HarnessMarker -OutDir $OutDir -Name '_BEFORE_INSTALL.marker' -Content ((Get-Date).ToUniversalTime().ToString('o')) | Out-Null

    $kitVolume = Get-Volume -FileSystemLabel $KitVolumeLabel -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $kitVolume) {
        Write-AgentLog "FATAL: no volume labelled $KitVolumeLabel -- the kit disk is not attached"
        return $null
    }
    $payloadDir = "$($kitVolume.DriveLetter):\"
    Write-AgentLog "kit payload at $payloadDir"

    $install = Invoke-CivicCastSilentInstall -PayloadDir $payloadDir `
        -InstallTargetDir $InstallTargetDir -TimeoutMinutes $InstallTimeoutMinutes
    Write-HarnessMarker -OutDir $OutDir -Name '_AFTER_INSTALL.marker' -Content ((Get-Date).ToUniversalTime().ToString('o')) | Out-Null
    Write-AgentLog "installer exit code: $($install.installer_exit_code)"

    $activation = Write-CivicCastActivationResult -OutDir $OutDir -InstallDir $InstallTargetDir `
        -PayloadDir $payloadDir -InstallerExitCode $install.installer_exit_code

    $summary = [ordered]@{
        schema                          = 'civiccast-gate-b-install-summary-v1'
        run_id                          = $State.run_id
        run_start_utc                   = $State.run_start_utc
        payload_dir                     = $payloadDir
        install_target_dir              = $InstallTargetDir
        installer_source                = $install.installer_source
        installer_sha256                = $install.installer_sha256
        silent_flag_used                = $install.silent_flag_used
        installer_exit_code             = $install.installer_exit_code
        installer_launch_error          = $install.installer_launch_error
        station_set_json_found          = $activation.station_set_json_found
        activation_self_test_json_found = $activation.activation_self_test_json_found
        errors                          = $install.errors
    }

    $stationUpLog = Join-Path $OutDir 'STATION-UP-WAIT.txt'
    $stationUp = Wait-CivicCastStationHealth -BaseUrl $BaseUrl `
        -DeadlineMinutes $StationUpDeadlineMinutes -LogFile $stationUpLog
    $summary['station_up'] = $stationUp.ok
    $summary['station_first_healthy_utc'] = $stationUp.first_healthy_utc
    $summary['station_up_polls'] = $stationUp.polls
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutDir 'summary.json') -Encoding UTF8

    if (-not $stationUp.ok) {
        Write-AgentLog "FATAL: the station never answered /api/health within $StationUpDeadlineMinutes minutes"
        return $null
    }

    $token = Get-StaffToken -State $State
    if (-not $token) {
        Write-AgentLog "FATAL: could not obtain a staff bearer token; the PEG channels cannot be started"
        return $null
    }
    $started = Start-PegChannels -Token $token
    if ($started -lt $PegChannels.Count) {
        # Not fatal to the agent: the soak still runs and every beat records
        # the channels that are NOT on air. The judge's `channels` check turns
        # that into the FAIL. An agent that exited here would produce no
        # evidence of WHY the channels never came up.
        Write-AgentLog "WARNING: only $started of $($PegChannels.Count) PEG channels started; the soak will record this in every beat"
    }
    return $token
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-AgentLog "agent starting (LaunchedBy=$LaunchedBy, AgentRoot=$AgentRoot)"

$state = Read-AgentState
if (-not $state) {
    if ($LaunchedBy -eq 'startup-task') {
        # A resume with no state is not a resume. Exiting loudly is right: the
        # host's evidence pull will find no new beats and the gap check will
        # fail, which is a truthful outcome. Inventing a fresh run here would
        # silently restart the soak's clock and report 24 hours that never
        # happened.
        Write-AgentLog "FATAL: launched as the startup task but no readable state.json exists -- refusing to start a NEW run under a resume's identity"
        exit 2
    }
    $now = (Get-Date).ToUniversalTime()
    $state = [pscustomobject]@{
        run_id                = [guid]::NewGuid().ToString('N')
        run_start_utc         = $now.ToString('o')
        soak_start_utc        = $null
        soak_minutes          = $SoakMinutes
        beat_interval_minutes = $BeatIntervalMinutes
        next_beat_seq         = 1
        phase                 = 'install'
        agent_launch_count    = 0
    }
    Write-AgentState -State $state
    Write-AgentLog "new run $($state.run_id) (soak_minutes=$SoakMinutes, beat_interval_minutes=$BeatIntervalMinutes)"
}

$state.agent_launch_count = [int]$state.agent_launch_count + 1
Write-AgentState -State $state

$token = $null
if ($state.phase -eq 'install') {
    $token = Invoke-InstallPhase -State $state
    if (-not $token) {
        Write-HarnessMarker -OutDir $OutDir -Name 'AGENT-INSTALL-FAILED.txt' `
            -Content "install phase did not reach a broadcasting station; see agent.log and summary.json" | Out-Null
        # DONE.json is still written -- with harness_completed FALSE. The
        # judge's completion check fails on that, and the install/activation
        # checks report the real cause. Writing nothing would instead present
        # as "the harness vanished", which is a different and untrue story.
        [ordered]@{
            done_utc          = (Get-Date).ToUniversalTime().ToString('o')
            harness_completed = $false
            watchdog_timeout  = $false
            stall_timeout     = $false
            reason            = 'install-phase-failed'
            run_id            = $state.run_id
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir 'DONE.json') -Encoding UTF8
        exit 1
    }
    # The soak clock starts when the station is actually broadcasting, not
    # when the installer was launched: §12's 24 hours are 24 hours of a
    # running station, and counting the install into them would shorten the
    # thing being proven by however long the install took.
    $state.soak_start_utc = (Get-Date).ToUniversalTime().ToString('o')
    $state.phase = 'soak'
    Write-AgentState -State $state

    $taskScript = Join-Path $PSScriptRoot 'Register-GateBStartupTask.ps1'
    if (Test-Path -LiteralPath $taskScript) {
        & $taskScript -AgentScript $PSCommandPath -AgentRoot $AgentRoot
        Write-AgentLog "at-startup resume task registered (exit $LASTEXITCODE)"
    } else {
        Write-AgentLog "FATAL-LATER: $taskScript not found -- this run CANNOT survive the reboot unattended"
    }
} else {
    Write-AgentLog "resuming run $($state.run_id) at phase '$($state.phase)', next beat $($state.next_beat_seq)"
    $token = Get-StaffToken -State $state
    if (-not $token) {
        Write-AgentLog "WARNING: no staff token after resume; channel samples in the following beats will show on_air=false"
    }
}

# --- the beat loop ---------------------------------------------------------
$soakStart = [datetime]::Parse($state.soak_start_utc).ToUniversalTime()
$soakEnd = $soakStart.AddMinutes([double]$state.soak_minutes)
$intervalSeconds = [int]([double]$state.beat_interval_minutes * 60)

Write-AgentLog "beat loop: start=$($soakStart.ToString('o')) end=$($soakEnd.ToString('o')) interval=${intervalSeconds}s"

while ((Get-Date).ToUniversalTime() -lt $soakEnd) {
    $beat = Write-Beat -State $state -Token $token
    Write-AgentLog ("beat {0} elapsed={1}m health={2} on_air={3}" -f `
        $beat.beat_seq, $beat.elapsed_minutes, $beat.health.http_status,
        (@($beat.channels | Where-Object { $_.on_air }).Count))

    # If the token stopped working (the station restarted its auth state, or
    # the token expired across a long soak), get a fresh one rather than
    # reporting every remaining channel as off-air. A sampling failure must
    # not be allowed to masquerade as a product failure.
    if ($token -and (@($beat.channels | Where-Object { $_.on_air }).Count) -eq 0 -and $beat.health.ok) {
        Write-AgentLog "station is healthy but no channel reads as on air -- re-authenticating in case the token lapsed"
        $refreshed = Get-StaffToken -State $state
        if ($refreshed) { $token = $refreshed }
    }

    $remaining = ($soakEnd - (Get-Date).ToUniversalTime()).TotalSeconds
    if ($remaining -le 0) { break }
    Start-Sleep -Seconds ([int][math]::Min($intervalSeconds, $remaining))
}

# One final beat at the end so the last sample sits at the soak boundary
# rather than one interval short of it.
$final = Write-Beat -State $state -Token $token
Write-AgentLog "final beat $($final.beat_seq) at elapsed=$($final.elapsed_minutes)m"

$state.phase = 'complete'
Write-AgentState -State $state

# Unregister the resume task. Leaving it armed would restart a completed soak
# on the VM's next boot, which is how a harness quietly starts consuming a
# runner box forever.
try {
    Unregister-ScheduledTask -TaskName 'CivicCastGateBAgent' -Confirm:$false -ErrorAction Stop
    Write-AgentLog "at-startup resume task unregistered"
} catch {
    Write-AgentLog "could not unregister the resume task: $_"
}

[ordered]@{
    done_utc          = (Get-Date).ToUniversalTime().ToString('o')
    harness_completed = $true
    watchdog_timeout  = $false
    stall_timeout     = $false
    run_id            = $state.run_id
    beats_written     = [int]$state.next_beat_seq - 1
    agent_launches    = [int]$state.agent_launch_count
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir 'DONE.json') -Encoding UTF8

Write-AgentLog "DONE.json written; agent exiting cleanly"
exit 0

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Register the scheduled task that resumes the Gate B agent after the reboot.
#
# This one file is what makes the difference between "the VM rebooted" and
# "the station survived an unattended reboot" (3.0 MASTER spec §12, station
# acceptance). Without it the reboot kills the agent and nothing brings it
# back; with it, the soak resumes with no human present and the beat log shows
# an uninterrupted 24 hours around a boot transition.
#
# THREE DELIBERATE CHOICES, EACH OF WHICH COULD PLAUSIBLY HAVE GONE THE OTHER
# WAY AND WOULD HAVE BROKEN THE GATE'S MEANING:
#
#   AtStartup, not AtLogon. Gate A's own runner uses an interactive-logon task
#   (sandbox-lab/runner/Install-GateARunner.ps1) because Windows Sandbox
#   cannot be launched from Session 0. The opposite constraint applies here:
#   a task that waits for a logon is a task that waits for a person, and §12
#   asks specifically for survival with nobody there. AtStartup fires before
#   any logon and requires none.
#
#   SYSTEM, not the operator account. The agent reads HKLM, drives a Windows
#   service and reads Win32_Process for the supervisor's children; SYSTEM has
#   all of that without a stored password. Running as a named user would mean
#   either storing that user's password in the task or granting the task
#   "run whether user is logged on or not" -- which needs the password too.
#   Nothing here handles a human's credential.
#
#   A startup DELAY. The agent's first act on resume is to re-authenticate
#   against the station, and at T+0 of a boot the supervisor has not started
#   its children yet. Firing instantly would produce a burst of failed
#   samples that are artefacts of the harness racing the boot, not findings
#   about the product. The delay is short enough to sit inside the reboot gap
#   budget the judge enforces and long enough that the first post-reboot beat
#   measures a station, not a starting one.
#
# Windows PowerShell 5.1 only. Exit 0 registered, 2 could not register.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AgentScript,

    [string]$AgentRoot = 'C:\CivicCastGateB',
    [string]$TaskName = 'CivicCastGateBAgent',

    # See the header. PT2M is comfortably inside the default 20-minute reboot
    # gap budget while giving the supervisor room to bring its children up.
    [string]$StartupDelay = 'PT2M'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $AgentScript)) {
    Write-Error "Register-GateBStartupTask: agent script not found at $AgentScript"
    exit 2
}

try {
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -LaunchedBy startup-task -AgentRoot "{1}"' -f `
        (Resolve-Path -LiteralPath $AgentScript).Path, $AgentRoot

    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = $StartupDelay
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

    # ExecutionTimeLimit 0 = none. A soak that can run for the rest of a day
    # must not be killed at the Task Scheduler's default 72-hour limit, and
    # more importantly must not be killed at all by the thing whose only job
    # is to keep it alive. StartWhenAvailable is deliberately OFF: it would
    # fire a "missed" startup trigger later, which for this task means
    # resuming a soak that has already finished.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -DontStopOnIdleEnd `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 `
        -RestartInterval ([TimeSpan]::FromMinutes(5)) `
        -MultipleInstances IgnoreNew

    # Replace rather than update: a task left over from a previous run points
    # at a previous run's paths, and "update" on a task whose action changed
    # is exactly the shape that leaves a stale argument behind.
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings `
        -Description 'CivicCast Gate B: resume the 24h reboot-soak agent unattended after a reboot.' `
        -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Register-GateBStartupTask: could not register '$TaskName': $_"
    exit 2
}

# Verify by READING BACK the registered task rather than trusting that
# Register-ScheduledTask returned without throwing -- the whole gate's
# unattendedness rests on this task existing with these properties, and "the
# call succeeded" is a weaker claim than "the row says so".
try {
    $registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $registeredTrigger = @($registered.Triggers)[0]
    $triggerType = $registeredTrigger.CimClass.CimClassName
    $userId = $registered.Principal.UserId
    Write-Host "registered task '$TaskName': trigger=$triggerType delay=$($registeredTrigger.Delay) principal=$userId runlevel=$($registered.Principal.RunLevel)"
    if ($triggerType -ne 'MSFT_TaskBootTrigger') {
        Write-Error "the registered trigger is '$triggerType', not a boot trigger -- this run would NOT survive the reboot unattended"
        exit 2
    }
} catch {
    Write-Error "Register-GateBStartupTask: registered '$TaskName' but could not read it back: $_"
    exit 2
}

exit 0

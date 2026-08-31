# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# CivicCastStationHarness -- the pieces Gate A and Gate B genuinely share.
#
# WHY THIS MODULE EXISTS. Gate A's driver (sandbox-lab/scripts/In-Sandbox-
# Report.ps1) performs the silent install and the K1 activation check as INLINE
# statements in one 2500-line try block, closing over script-scope $summary /
# $OutDir / $PayloadDir. Gate B needs exactly that install + activation
# behaviour inside a Hyper-V VM instead of a Sandbox VM. Copy-pasting those
# blocks would create two install contracts that drift apart silently, and the
# first symptom of the drift would be one gate passing a candidate the other
# would have failed.
#
# So the shared behaviour lives here, parameterized (nothing closes over a
# caller's scope), and BOTH gates' evidence is graded by the same field names:
# summary.json's installer_exit_code / station_set_json_found /
# activation_self_test_json_found, and ACTIVATION-RESULT.txt's
# installer_exit_code= / station_set_json_found_after_install= lines are read
# identically by scripts/gate_a_verdict.py and scripts/gate_b_verdict.py.
#
# HONEST SCOPE NOTE -- read this before assuming Gate A calls into here.
# Gate B consumes this module. In-Sandbox-Report.ps1 does NOT yet: migrating
# the live Gate A driver onto it would mean editing the one harness whose
# mapped-folder/shipper/watchdog architecture was earned over seven failed
# runs, with no way to exercise a Windows Sandbox run from a PR. That
# migration is deliberately deferred and named in docs/ops/gate-b.md rather
# than done half-way here. What prevents the drift in the meantime is not
# hope: tests/gate_b/test_gate_b_harness_contract.py reads the literals out of
# BOTH this module and In-Sandbox-Report.ps1 and fails the build when they
# stop agreeing -- the silent-install flag, the four station-set.json lookup
# shapes, and the ACTIVATION-RESULT.txt field names.
#
# PowerShell 5.1 compatible by requirement: the in-VM agent runs under
# Windows PowerShell 5.1 (the in-box shell on a stock Windows image, before
# anything is installed), so nothing here may use PowerShell 7 syntax --
# no ternaries, no ?? operators, no -Parallel.

# NO Set-StrictMode here, deliberately.
#
# Strict mode turns a read of a non-existent property into a terminating
# error. That is usually a good trade, and it is the wrong one for this file:
# every function here promises never to throw past its own boundary, because
# each is called from a harness whose job is to keep sampling a station for 24
# hours and to record failures as evidence rather than die of them. The
# concrete case is Invoke-CivicCastApi's catch block reading
# $_.Exception.Response -- present on a WebException, absent on plenty of
# other exception types -- where strict mode would convert "the station
# returned an error we could not read the body of" into an unhandled throw
# out of the error handler itself. Gate A's driver takes the same posture
# ($ErrorActionPreference = 'Continue') for the same reason.

# ---------------------------------------------------------------------------
# Contract constants. These are the literals the cross-gate contract test
# binds; change one here and the test will require the matching change in
# In-Sandbox-Report.ps1 (or an explicit, argued update to the test).
# ---------------------------------------------------------------------------

# Tauri/NSIS convention: uppercase /S is silent mode. /D= sets the install
# directory and, per an NSIS quirk, MUST be the last argument and unquoted.
$script:CivicCastSilentFlag = '/S'
$script:CivicCastInstallDirFlag = '/D='

# The two files the K1 activation hook is expected to leave behind.
$script:CivicCastStationSetFileName = 'station-set.json'
$script:CivicCastActivationSelfTestFileName = 'activation-self-test.json'


function Get-CivicCastHarnessContract {
    <#
    .SYNOPSIS
        The literals this module promises, as data.
    .DESCRIPTION
        Exposed so a test (or an operator debugging a mismatch) can read the
        contract without parsing the module source. Returns an ordered
        hashtable; every value is one of the $script: constants above.
    #>
    [CmdletBinding()]
    param()

    return [ordered]@{
        silent_flag                     = $script:CivicCastSilentFlag
        install_dir_flag                = $script:CivicCastInstallDirFlag
        station_set_file_name           = $script:CivicCastStationSetFileName
        activation_self_test_file_name  = $script:CivicCastActivationSelfTestFileName
    }
}


function Invoke-BoundedProcess {
    <#
    .SYNOPSIS
        Run an external process with a hard timeout; kill it rather than wait.
    .DESCRIPTION
        Lifted from Gate A's In-Sandbox-Report.ps1, where it exists because a
        synchronous, uncancellable file/process operation against a share the
        guest does not control can wedge the issuing thread permanently. Every
        external call a harness makes on its critical path should go through
        something with this shape: a timeout that kills the child instead of
        joining it forever.

        Never throws past its own boundary. Returns a hashtable with
        started/completed/exit_code/error so the caller decides what a
        timeout means.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [int]$TimeoutSeconds = 60
    )

    $result = [ordered]@{
        file_path  = $FilePath
        started    = $false
        completed  = $false
        timed_out  = $false
        exit_code  = $null
        error      = $null
    }
    try {
        if ($ArgumentList -and $ArgumentList.Count -gt 0) {
            $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -NoNewWindow -ErrorAction Stop
        } else {
            $proc = Start-Process -FilePath $FilePath -PassThru -NoNewWindow -ErrorAction Stop
        }
        $result.started = $true
    } catch {
        $result.error = "launch failed: $_"
        return $result
    }
    try {
        Wait-Process -Id $proc.Id -Timeout $TimeoutSeconds -ErrorAction Stop
        $result.completed = $true
    } catch {
        $result.timed_out = $true
        $result.error = "timed out after ${TimeoutSeconds}s; child killed"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $proc.Id -Timeout 5 -ErrorAction SilentlyContinue
        return $result
    }
    try {
        $proc.Refresh()
        $result.exit_code = $proc.ExitCode
    } catch {
        $result.error = "exit code unreadable: $_"
    }
    return $result
}


function Write-HarnessMarker {
    <#
    .SYNOPSIS
        Write a small marker file into an evidence directory.
    .DESCRIPTION
        Markers are how both harnesses make a moment observable to a poller
        that cannot be raced: Test-Path on a file that is written once and
        never removed cannot be missed by a coarse polling interval the way a
        transient field value can (the exact failure that made Gate A's
        staleness watchdog miss run6).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string]$OutDir,
        [Parameter(Mandatory = $true)] [string]$Name,
        [string]$Content = ''
    )

    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    }
    $path = Join-Path $OutDir $Name
    try {
        Set-Content -LiteralPath $path -Value $Content -Encoding UTF8 -ErrorAction Stop
    } catch {
        # A marker that cannot be written must never take the run down with
        # it -- the marker is diagnostics, the run is the product.
        Write-Warning "Write-HarnessMarker: could not write $path : $_"
    }
    return $path
}


function Test-CivicCastKnownPaths {
    <#
    .SYNOPSIS
        Targeted, NON-RECURSIVE lookup of an installed file at its four known shapes.
    .DESCRIPTION
        Checks exactly:
            <InstallDir>\<FileName>
            <InstallDir>\app\<FileName>
            <InstallDir>\app\*\<FileName>        (shallow, one level only)
            %ProgramData%\CivicCast\<FileName>

        The non-recursive property is the point, not an optimisation. Gate A
        originally scanned the install tree with Get-ChildItem -Recurse; on a
        ~12 GB install across a VSMB share that is minutes of I/O on the
        harness's own thread, and it was one of the operations that could
        wedge it. Four Test-Path calls cannot.

        Returns an ARRAY of full paths that exist (possibly empty), matching
        Gate A's summary.json shape, where station_set_json_found is the list
        of hits and the judge reads its truthiness/count.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$InstallDir,
        [Parameter(Mandatory = $true)] [string]$FileName
    )

    $hits = @()
    if ($InstallDir) {
        $direct = Join-Path $InstallDir $FileName
        if (Test-Path -LiteralPath $direct) { $hits += $direct }

        $appDir = Join-Path $InstallDir 'app'
        $appDirect = Join-Path $appDir $FileName
        if (Test-Path -LiteralPath $appDirect) { $hits += $appDirect }

        if (Test-Path -LiteralPath $appDir) {
            $children = @(Get-ChildItem -LiteralPath $appDir -Directory -ErrorAction SilentlyContinue)
            foreach ($child in $children) {
                $shallow = Join-Path $child.FullName $FileName
                if (Test-Path -LiteralPath $shallow) { $hits += $shallow }
            }
        }
    }
    if ($env:ProgramData) {
        $programData = Join-Path (Join-Path $env:ProgramData 'CivicCast') $FileName
        if (Test-Path -LiteralPath $programData) { $hits += $programData }
    }
    return , @($hits)
}


function Invoke-CivicCastSilentInstall {
    <#
    .SYNOPSIS
        Run the candidate kit's signed installer silently and capture its exit code.
    .DESCRIPTION
        The installer only READS <PayloadDir>\packs and <PayloadDir>\station and
        writes solely to the /D= target, so PayloadDir may be read-only media --
        which is what lets Gate B attach the ~21 GB kit as a read-only VHDX
        instead of copying it into the VM's own disk.

        The exit code is a real, meaningful signal, not just success/failure:
        nsis-hooks-bootstrap.nsh's CIVICCAST_FAIL macro (SetErrorLevel + Abort)
        maps postinstall steps onto distinct codes -- 110 pack delivery,
        111/112/121/122 D2 verify, 116-119 D4 provision/service/firewall,
        120 upgrade quiesce failure, 123 D4 activation (K1). Callers
        should record it verbatim rather than collapsing it to a boolean.

        Returns a hashtable with installer_source, installer_sha256,
        silent_flag_used, installer_exit_code, installer_launch_error.
        Never throws on a failed install -- a failed install is a finding, and
        a finding must reach the evidence file, not the console of a process
        that is about to die.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string]$PayloadDir,
        [Parameter(Mandatory = $true)] [string]$InstallTargetDir,
        [int]$TimeoutMinutes = 120
    )

    $result = [ordered]@{
        installer_source        = $null
        installer_sha256        = $null
        silent_flag_used        = $null
        installer_exit_code     = $null
        installer_launch_error  = $null
        install_target_dir      = $InstallTargetDir
        errors                  = @()
    }

    $exe = Get-ChildItem -LiteralPath $PayloadDir -Filter '*setup.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $exe) {
        $result.installer_launch_error = "No *setup.exe found in payload at $PayloadDir"
        $result.errors += $result.installer_launch_error
        return $result
    }
    $result.installer_source = $exe.FullName
    try {
        $result.installer_sha256 = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLower()
    } catch {
        $result.errors += "hash of installer failed: $_"
    }

    # /D must be LAST and unquoted (NSIS quirk). Build the whole argument
    # string rather than an array so the unquoted trailing /D= survives
    # PowerShell's own argument quoting.
    $argString = "$($script:CivicCastSilentFlag) $($script:CivicCastInstallDirFlag)$InstallTargetDir"
    $result.silent_flag_used = $argString

    try {
        $proc = Start-Process -FilePath $exe.FullName -ArgumentList $argString -PassThru -WindowStyle Hidden -ErrorAction Stop
    } catch {
        $result.installer_launch_error = "installer launch failed: $_"
        $result.errors += $result.installer_launch_error
        return $result
    }
    try {
        Wait-Process -Id $proc.Id -Timeout ($TimeoutMinutes * 60) -ErrorAction Stop
    } catch {
        $result.installer_launch_error = "installer did not finish within $TimeoutMinutes minutes; killed"
        $result.errors += $result.installer_launch_error
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $proc.Id -Timeout 10 -ErrorAction SilentlyContinue
        return $result
    }
    try {
        $proc.Refresh()
        $result.installer_exit_code = $proc.ExitCode
    } catch {
        $result.errors += "installer exit code unreadable: $_"
    }
    return $result
}


function Write-CivicCastActivationResult {
    <#
    .SYNOPSIS
        Probe for the K1 activation artefacts and write ACTIVATION-RESULT.txt.
    .DESCRIPTION
        Writes the exact file shape both judges read:

            installer_exit_code=<int>
            install_dir=<path>
            station_set_json_found_after_install=<0|1>

        plus, only when the first probe found nothing and a re-run was
        attempted, rerun_exit_code= and station_set_json_found_after_rerun=.

        The re-run path exists because activation is a postinstall hook that
        can fail for environmental reasons (cache root, disk) while the
        install itself succeeded; re-running the activation CLI directly
        against the now fully-provisioned install, with stdout/stderr
        captured, turns "activation didn't happen" from a dead end into a
        diagnosable event. It does NOT make a failed activation pass: the
        judge reads station_set_json_found_after_install, which the re-run
        never rewrites.

        Returns a hashtable with station_set_json_found and
        activation_self_test_json_found (both arrays, Gate A's shape) for the
        caller to merge into summary.json.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string]$OutDir,
        [Parameter(Mandatory = $true)] [AllowEmptyString()] [string]$InstallDir,
        [Parameter(Mandatory = $true)] [string]$PayloadDir,
        [Parameter(Mandatory = $true)] [AllowNull()] $InstallerExitCode,
        [string]$CacheRoot = $null,
        [switch]$SkipActivationRerun
    )

    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    }

    $stationSet = Test-CivicCastKnownPaths -InstallDir $InstallDir -FileName $script:CivicCastStationSetFileName
    $selfTest = Test-CivicCastKnownPaths -InstallDir $InstallDir -FileName $script:CivicCastActivationSelfTestFileName

    $resultPath = Join-Path $OutDir 'ACTIVATION-RESULT.txt'
    $exitText = '<null>'
    if ($null -ne $InstallerExitCode) { $exitText = "$InstallerExitCode" }
    "installer_exit_code=$exitText" | Set-Content -LiteralPath $resultPath -Encoding UTF8
    "install_dir=$InstallDir" | Add-Content -LiteralPath $resultPath -Encoding UTF8
    $stationHit = @($stationSet).Count
    "station_set_json_found_after_install=$stationHit" | Add-Content -LiteralPath $resultPath -Encoding UTF8

    if ($stationHit -eq 0 -and $InstallDir -and -not $SkipActivationRerun) {
        $bundle = Join-Path (Join-Path $PayloadDir 'station') 'station-index.json'
        $exe = Join-Path $InstallDir 'CivicCast Native.exe'
        if (-not $CacheRoot) { $CacheRoot = Join-Path (Split-Path $InstallDir -Parent) 'cache' }
        if ((Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath $bundle)) {
            New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
            $outLog = Join-Path $OutDir 'activation-rerun.stdout.log'
            $errLog = Join-Path $OutDir 'activation-rerun.stderr.log'
            "(started $((Get-Date).ToUniversalTime().ToString('o')))" | Set-Content -LiteralPath $errLog -Encoding UTF8
            $argStr = '--civiccast-activate-station --install-root "' + $InstallDir + '"' +
                      ' --civiccast-import-station "' + $bundle + '"' +
                      ' --cache-root "' + $CacheRoot + '"'
            try {
                $proc = Start-Process -FilePath $exe -ArgumentList $argStr -Wait -PassThru `
                    -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -ErrorAction Stop
                "rerun_exit_code=$($proc.ExitCode)" | Add-Content -LiteralPath $resultPath -Encoding UTF8
            } catch {
                "rerun_exit_code=<launch-failed: $_>" | Add-Content -LiteralPath $resultPath -Encoding UTF8
            }
            $stationSet = Test-CivicCastKnownPaths -InstallDir $InstallDir -FileName $script:CivicCastStationSetFileName
            $selfTest = Test-CivicCastKnownPaths -InstallDir $InstallDir -FileName $script:CivicCastActivationSelfTestFileName
            "station_set_json_found_after_rerun=$(@($stationSet).Count)" | Add-Content -LiteralPath $resultPath -Encoding UTF8
        } else {
            "rerun_skipped=missing_exe_or_bundle exe=$(Test-Path -LiteralPath $exe) bundle=$(Test-Path -LiteralPath $bundle)" |
                Add-Content -LiteralPath $resultPath -Encoding UTF8
        }
    }

    return [ordered]@{
        station_set_json_found          = @($stationSet)
        activation_self_test_json_found = @($selfTest)
        activation_result_path          = $resultPath
    }
}


function Invoke-CivicCastApi {
    <#
    .SYNOPSIS
        Bounded HTTP JSON call against the station; never throws past its boundary.
    .DESCRIPTION
        Captures status/ok/body_raw/body_json/error into a hashtable rather
        than raising, so a harness sampling a station every five minutes for a
        day cannot be killed by one bad response.

        The returned shape and the header names are deliberately IDENTICAL to
        Gate A's own Invoke-CivicCastApi (In-Sandbox-Report.ps1) -- in
        particular the setup-nonce header 'X-CivicCast-Setup-Nonce', which is
        how the installer's HKLM nonce is presented to
        POST /api/setup/first-admin. Two harnesses that authenticate against
        the same station differently would eventually disagree about whether
        the station is reachable.

        Error bodies matter here: a 4xx from the station carries the reason in
        its body, and Invoke-WebRequest throws it away unless the response
        stream is read explicitly, which is what the catch block does.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string]$Method,
        [Parameter(Mandatory = $true)] [string]$Url,
        [string]$LogFile = $null,
        $BodyObj = $null,
        [string]$BearerToken = $null,
        [string]$SetupNonce = $null,
        [int]$TimeoutSec = 30
    )

    $result = [ordered]@{
        method = $Method; url = $Url; status = $null; ok = $false
        body_raw = $null; body_json = $null; error = $null
    }
    try {
        $headers = @{}
        if ($BearerToken) { $headers['Authorization'] = "Bearer $BearerToken" }
        if ($SetupNonce) { $headers['X-CivicCast-Setup-Nonce'] = $SetupNonce }
        $params = @{
            Uri = $Url; Method = $Method; Headers = $headers; UseBasicParsing = $true
            TimeoutSec = $TimeoutSec; ErrorAction = 'Stop'
        }
        if ($null -ne $BodyObj) {
            $params['Body'] = ($BodyObj | ConvertTo-Json -Depth 10)
            $params['ContentType'] = 'application/json'
        }
        $response = Invoke-WebRequest @params
        $result.status = [int]$response.StatusCode
        $result.body_raw = [string]$response.Content
        $result.ok = $true
    } catch {
        # Belt and braces around the response read. Not every exception that
        # reaches here is a WebException, so .Response may not exist at all,
        # and a body that will not read must never take down the error handler
        # that exists to record why the call failed.
        try {
            $exception = $_.Exception
            if ($exception -and $exception.Response) {
                $result.status = [int]$exception.Response.StatusCode
                $stream = $exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $result.body_raw = $reader.ReadToEnd()
            }
        } catch {
            # A response object that will not yield its status or body leaves
            # them null. Never fabricate either one.
            $result.body_raw = $null
        }
        $result.error = "$_"
    }
    if ($result.body_raw) {
        try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch { $result.body_json = $null }
    }
    if ($LogFile) {
        try {
            "$Method $Url -> status:$($result.status) ok:$($result.ok) err:$($result.error)" |
                Add-Content -LiteralPath $LogFile -Encoding UTF8
            if ((-not $result.ok) -or ($result.status -ge 400)) {
                "  BODY: $($result.body_raw)" | Add-Content -LiteralPath $LogFile -Encoding UTF8
            }
        } catch {
            Write-Warning "Invoke-CivicCastApi: could not append to $LogFile"
        }
    }
    return $result
}


function Wait-CivicCastStationHealth {
    <#
    .SYNOPSIS
        Poll /api/health on a single bounded deadline until the station answers 200.
    .DESCRIPTION
        ONE endpoint, ONE deadline. Gate A learned this the hard way: probing
        several surfaces on independent unbounded loops meant a station that
        never came up produced a hang rather than a verdict. /api/health is the
        station's documented liveness path and always answers 200 while the
        process is alive (civiccast/app.py), so it is the only surface whose
        silence means "not up yet" rather than "not ready yet".

        Every poll is logged with its timestamp and outcome, so a failure has a
        trail rather than a single "timed out" line.

        Returns a hashtable: ok, status, polls, first_healthy_utc, error.
    #>
    [CmdletBinding()]
    param(
        [string]$BaseUrl = 'http://127.0.0.1:8000',
        [int]$DeadlineMinutes = 20,
        [int]$PollSeconds = 6,
        [string]$LogFile = $null
    )

    $result = [ordered]@{
        url = "$BaseUrl/api/health"; ok = $false; status = $null; bytes = 0
        polls = 0; first_healthy_utc = $null; error = $null
    }
    $deadline = (Get-Date).AddMinutes($DeadlineMinutes)
    while ((Get-Date) -lt $deadline) {
        $result.polls++
        $stamp = (Get-Date).ToUniversalTime().ToString('o')
        try {
            $response = Invoke-WebRequest -Uri $result.url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            $result.status = [int]$response.StatusCode
            $body = [string]$response.Content
            $result.bytes = $body.Length
            if ($result.status -eq 200 -and $result.bytes -gt 0) {
                $result.ok = $true
                $result.first_healthy_utc = $stamp
                if ($LogFile) {
                    "poll #$($result.polls) $stamp -> status:$($result.status) STATION HEALTHY" |
                        Add-Content -LiteralPath $LogFile -Encoding UTF8
                }
                return $result
            }
            if ($LogFile) {
                "poll #$($result.polls) $stamp -> status:$($result.status) ok:false bytes:$($result.bytes)" |
                    Add-Content -LiteralPath $LogFile -Encoding UTF8
            }
        } catch {
            $result.error = "$($_.Exception.Message)"
            if ($LogFile) {
                "poll #$($result.polls) $stamp -> ERROR: $($result.error)" |
                    Add-Content -LiteralPath $LogFile -Encoding UTF8
            }
        }
        Start-Sleep -Seconds $PollSeconds
    }
    return $result
}


Export-ModuleMember -Function @(
    'Get-CivicCastHarnessContract',
    'Invoke-BoundedProcess',
    'Write-HarnessMarker',
    'Test-CivicCastKnownPaths',
    'Invoke-CivicCastSilentInstall',
    'Write-CivicCastActivationResult',
    'Invoke-CivicCastApi',
    'Wait-CivicCastStationHealth'
)

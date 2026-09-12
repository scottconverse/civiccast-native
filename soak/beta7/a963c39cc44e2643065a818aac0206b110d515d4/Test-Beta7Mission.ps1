[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$common = Join-Path $PSScriptRoot 'Beta7Tester.Common.ps1'
$runner = Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoak.ps1'
. $common
. $runner -SelfTest -BaseUrl 'http://127.0.0.1:1' -OutputRoot (Join-Path $PSScriptRoot 'selftest-output') -SourceSha ('0' * 40) -ExpectedElementsPerPhase @{ON=@{public=@(77);education=@(77);government=@(77)};OFF=@{public=@(77);education=@(77);government=@(77)}}
$sha = '0123456789abcdef0123456789abcdef01234567'
$hash = ('a' * 64)
$base = Get-Content (Join-Path $PSScriptRoot 'run-identity.json') -Raw | ConvertFrom-Json
$base.candidate_source_sha = $sha; $base.build_source_sha = $sha; $base.gate_a_source_sha = $sha
$base.expected_manifest_sha256 = $hash; $base.expected_installer_sha256 = $hash
$base.build_run_id = '12345'; $base.gate_a_run_id = '67890'; $base.gate_a_verdict = 'PASS'
$base.install_root = 'C:\CivicCastHostStore\install'
$base.kit_base_url = "http://192.168.0.135:8766/$sha/"
$base.expected_elements_per_phase = [pscustomobject]@{ON=[pscustomobject]@{public=@(77);education=@(77);government=@(77)};OFF=[pscustomobject]@{public=@(77);education=@(77);government=@(77)}}
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('civiccast-beta7-selftest-' + [guid]::NewGuid().ToString('N') + '.json')
$oldComputer = $env:COMPUTERNAME
try {
    $env:COMPUTERNAME = [string]$base.expected_hostname
    $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
    $accepted = Get-Beta5Identity $tmp
    if ([string]$accepted.candidate_source_sha -ne $sha) { throw 'Populated candidate SHA was not accepted.' }
    foreach ($rejectedKitUrl in @('http://192.168.0.135:8766/',('http://192.168.0.135:8766/' + ('f' * 40) + '/'))) {
        $base.kit_base_url = $rejectedKitUrl
        $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
        try { Get-Beta5Identity $tmp | Out-Null; throw "Unbound kit URL was accepted: $rejectedKitUrl" } catch { if ($_.Exception.Message -notmatch 'exact candidate') { throw } }
    }
    $base.kit_base_url = "http://192.168.0.135:8766/$sha/"
    $base.expected_elements_per_phase = [pscustomobject]@{ON=[pscustomobject]@{public='EXPECTED_ELEMENTS_PUBLIC';education=@(77);government=@(77)};OFF=[pscustomobject]@{public=@(77);education=@(77);government=@(77)}}; $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
    try { Get-Beta5Identity $tmp | Out-Null; throw 'Topology placeholder was accepted.' } catch { if ($_.Exception.Message -notmatch 'topology expectation') { throw } }
    $base.expected_elements_per_phase = [pscustomobject]@{ON=[pscustomobject]@{public=@(77);education=@(77);government=@(77)};OFF=[pscustomobject]@{public=@(77);education=@(77);government=@(77)}}
    $base.gate_a_verdict = 'PENDING'; $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
    try { Get-Beta5Identity $tmp | Out-Null; throw 'PENDING Gate A identity was accepted.' } catch { if ($_.Exception.Message -notmatch 'Gate A verdict') { throw } }
    $base.gate_a_verdict = 'PASS'; $base.build_source_sha = ('f' * 40); $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
    try { Get-Beta5Identity $tmp | Out-Null; throw 'Mismatched build SHA was accepted.' } catch { if ($_.Exception.Message -notmatch 'source SHAs') { throw } }
    foreach ($rejectedVersion in @('1.0.0-beta.5','1.0.0-beta.6')) {
        $base.build_source_sha = $sha; $base.expected_version = $rejectedVersion
        $base | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding utf8
        try { Get-Beta5Identity $tmp | Out-Null; throw "$rejectedVersion identity was accepted." } catch { if ($_.Exception.Message -notmatch 'beta.7 contract') { throw } }
    }
    $clean = @{text='worker WORKER_RESULT error=None clean=true';path='worker.log'}
    $stall = @{text='watchdog: no output for 10s';path='worker.log'}
    $grade = Get-Beta7FailureGrades @($clean,$stall)
    if ($grade.f1_pass -or $grade.f3_pass) { throw 'F-1/F-3 failure fixtures were not rejected.' }
    $txnGood = @{text='CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=1)`nCTRL reload: new leg preroll verified (reload_id=1) held_streams=2`nCTRL reload: firing (reload_id=1)`nCTRL reload committed (elements=77)';path='public/gst-worker.stdout.log'}
    $txnCross = @{text='CTRL reload: firing (reload_id=1)`nCTRL reload committed (elements=77)';path='education/gst-worker.stdout.log'}
    $goodGrade = Get-Beta7FailureGrades @($txnGood) @{public=@(77,78)}
    if (-not $goodGrade.f1_pass) { throw 'Valid transaction preroll fixture was rejected.' }
    $crossGrade = Get-Beta7FailureGrades @($txnGood,$txnCross) @{public=@(77,78);education=@(77,78)}
    if ($crossGrade.f1_pass) { throw 'Cross-channel transaction fixture was accepted.' }
    $undersized = @{text='CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=2)`nCTRL reload: new leg preroll verified (reload_id=2) held_streams=2`nCTRL reload: firing (reload_id=2)`nCTRL reload committed (elements=56)';path='public/gst-worker.stdout.log'}
    if ((Get-Beta7FailureGrades @($txnGood,$undersized) @{public=@(77,78)}).f1_pass) { throw 'Undersized elements=56 regression was accepted.' }
    $topologyLogs=@(@{path='public/gst-worker.stdout.log';text=$txnGood.text},@{path='education/gst-worker.stdout.log';text=$txnGood.text},@{path='government/gst-worker.stdout.log';text=$txnGood.text})
    $states=@(@{channel_id='public';state='ON_AIR';pid=1},@{channel_id='education';state='ON_AIR';pid=2},@{channel_id='government';state='ON_AIR';pid=3})
    $transport=@(@{label='public';verdict='PASS'},@{label='education';verdict='PASS'},@{label='government';verdict='PASS'})
    $topology = Get-Beta7WorkerTopologyGrade $topologyLogs @(@{id='public'},@{id='education'},@{id='government'}) $states $transport @{public=@(77,78);education=@(77,78);government=@(77,78)}
    if (-not $topology.pass) { throw 'Healthy topology fixture was rejected.' }
    $missingTopology = Get-Beta7WorkerTopologyGrade $topologyLogs[0] @(@{id='public'},@{id='education'},@{id='government'}) $states $transport @{public=@(77,78);education=@(77,78);government=@(77,78)}
    if ($missingTopology.pass) { throw 'Missing channel topology fixture was accepted.' }
    $startScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakJob.ps1') -Raw
    $dotSourceIndex = $startScript.IndexOf(". (Join-Path `$installedBin 'Beta7Tester.Common.ps1')")
    $identityIndex = $startScript.IndexOf('Get-Beta5Identity $identityPath')
    if ($dotSourceIndex -lt 0 -or $identityIndex -lt 0 -or $dotSourceIndex -gt $identityIndex) { throw 'Start-Beta7SoakJob does not load the verified identity helper before use.' }
    Write-Output 'BETA7_MISSION_SELFTEST_PASS'
} finally {
    $env:COMPUTERNAME = $oldComputer
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

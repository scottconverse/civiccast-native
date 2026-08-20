# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# T-2/G-15: headless-bootstrap.ps1 had zero execution tests -- only
# substring/order assertions on its text (test_windows_wsl_bootstrap_script.py).
# This suite dot-sources the real script to get its real functions into scope
# and exercises them directly with synthetic inputs, instead of grepping for
# characteristic strings. Dot-sourcing is safe: the script's tail (the actual
# mutex/WSL/service bootstrap run) is guarded behind
# `if ($MyInvocation.InvocationName -ne '.')`, so importing it here only
# defines functions/variables -- it does not touch WSL, the network, or the
# real installer-state.json (see headless-bootstrap.ps1's guard comment).
#
# Run: pwsh -c 'Invoke-Pester tests/policy/HeadlessBootstrap.Tests.ps1'

Describe "headless-bootstrap.ps1" {

    BeforeAll {
        # Pester v5/v6: code at file top level (outside any block) only runs
        # during discovery, not the run phase -- $script:ScriptPath must be
        # (re)computed here so it exists when It/BeforeAll blocks execute.
        $script:ScriptPath = Join-Path $PSScriptRoot "../../civiccast/apps/installer/src-tauri/resources/headless-bootstrap.ps1"
        # Dot-source with a plain, non-verbatim InstallDir for the tests that
        # don't care about the prefix-strip behavior itself.
        . $script:ScriptPath -InstallDir "TestDrive:\CivicCastInstall"
    }

    Context "extended-length \$InstallDir prefix strip" {
        It "strips the \\?\ prefix from a plain drive path" {
            . $script:ScriptPath -InstallDir '\\?\C:\Users\tester\AppData\Local\CivicCast Installer'
            $InstallDir | Should -Be 'C:\Users\tester\AppData\Local\CivicCast Installer'
        }

        It "strips the \\?\UNC\ prefix to a plain UNC path" {
            . $script:ScriptPath -InstallDir '\\?\UNC\server\share\dir'
            $InstallDir | Should -Be '\\server\share\dir'
        }

        It "leaves a plain path untouched" {
            . $script:ScriptPath -InstallDir 'C:\plain\path'
            $InstallDir | Should -Be 'C:\plain\path'
        }
    }

    Context "Redact-LogMessage" {
        It "redacts a setup nonce" {
            Redact-LogMessage "SETUP_NONCE=abc123secret" | Should -Not -Match "abc123secret"
        }

        It "redacts a bearer token" {
            Redact-LogMessage "Authorization: Bearer sk-live-should-not-appear" |
                Should -Not -Match "sk-live-should-not-appear"
        }

        It "redacts a nonce query parameter" {
            Redact-LogMessage "http://127.0.0.1:8000/operator/?nonce=topsecretvalue" |
                Should -Not -Match "topsecretvalue"
        }

        It "leaves an ordinary log line untouched" {
            Redact-LogMessage "CivicCast headless bootstrap starting. InstallDir=C:\Program Files\CivicCast" |
                Should -Match "CivicCast headless bootstrap starting"
        }
    }

    Context "Test-ServiceAlreadyHealthy" {
        BeforeEach {
            Mock Get-BundledRuntimeBuildId { "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
        }

        It "returns true only when /health reports the expected version and build" {
            Mock Invoke-WebRequest {
                [pscustomobject]@{
                    StatusCode = 200
                    Content    = '{"status":"healthy","version":"' + $CivicCastVersion + '","runtime_build_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
                }
            }
            Test-ServiceAlreadyHealthy | Should -BeTrue
        }

        It "returns false for stale bytes with the same semantic version" {
            Mock Invoke-WebRequest {
                [pscustomobject]@{
                    StatusCode = 200
                    Content    = '{"status":"healthy","version":"' + $CivicCastVersion + '","runtime_build_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}'
                }
            }
            Test-ServiceAlreadyHealthy | Should -BeFalse
        }

        It "returns false when /health reports a different version" {
            Mock Invoke-WebRequest {
                [pscustomobject]@{
                    StatusCode = 200
                    Content    = '{"status":"healthy","version":"0.0.1-stale"}'
                }
            }
            Test-ServiceAlreadyHealthy | Should -BeFalse
        }

        It "returns true for a degraded-but-correct build (readiness is not liveness)" {
            # GauntletGate W-1: /health's `status` became a READINESS verdict --
            # "degraded" whenever the database schema is not current. A station
            # is degraded for the whole window between "the service is running"
            # and "the operator has run Prepare storage", which is exactly when
            # this function is asked whether the expected build is answering.
            # Gating reuse on readiness would make a fresh install throw
            # "setup finished without returning a bootstrap instance proof"
            # (the Test-ServiceAlreadyHealthy fallback in the main try block).
            Mock Invoke-WebRequest {
                [pscustomobject]@{
                    StatusCode = 200
                    Content    = '{"status":"degraded","schema":"not-configured","version":"' + $CivicCastVersion + '","runtime_build_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
                }
            }
            Test-ServiceAlreadyHealthy | Should -BeTrue
        }

        It "returns false when /health is unreachable" {
            Mock Invoke-WebRequest { throw "connection refused" }
            Test-ServiceAlreadyHealthy | Should -BeFalse
        }

        It "returns false on a non-200 status" {
            Mock Invoke-WebRequest { [pscustomobject]@{ StatusCode = 503; Content = "{}" } }
            Test-ServiceAlreadyHealthy | Should -BeFalse
        }
    }

    Context "single-instance mutex no-op (G-4/PE-ENG-2)" {
        It "exits 2 with the BOOTSTRAP_NOOP_MUTEX_HELD marker when a peer instance holds the mutex" {
            # Hold the same named mutex the script itself acquires, to
            # simulate a peer instance already running -- then actually run
            # the real script as a child process and observe its real exit
            # code and stdout, instead of asserting on source text.
            $mutex = New-Object System.Threading.Mutex($false, "Local\CivicCastHeadlessBootstrap")
            $acquired = $mutex.WaitOne(0)
            try {
                $acquired | Should -BeTrue -Because "the test must hold the mutex itself to simulate a peer instance"

                $installDir = Join-Path $TestDrive "install"
                New-Item -ItemType Directory -Force -Path $installDir | Out-Null
                $stdoutPath = Join-Path $TestDrive "noop-stdout.txt"
                $stderrPath = Join-Path $TestDrive "noop-stderr.txt"

                $proc = Start-Process -FilePath "powershell.exe" -ArgumentList @(
                    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script:ScriptPath,
                    "-InstallDir", $installDir
                ) -NoNewWindow -PassThru -Wait `
                    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

                $proc.ExitCode | Should -Be 2
                (Get-Content -Raw -Path $stdoutPath) | Should -Match "BOOTSTRAP_NOOP_MUTEX_HELD"
            } finally {
                if ($acquired) { $mutex.ReleaseMutex() }
                $mutex.Dispose()
            }
        }
    }

    Context "offline first-run (T-4/G-20)" {
        # Ensure-Ubuntu2404 itself calls `exit` on this path (same as a real
        # run would, so it can halt the whole bootstrap) -- calling it
        # in-process here would kill the Pester runner, not just this test.
        # Test the pure classifier it delegates to instead, the same pattern
        # as main.rs's output_needs_reboot/output_wsl_not_ready tests.
        It "recognizes common wsl.exe connectivity-failure phrasings" {
            Test-WslInstallOutputIndicatesNetworkFailure "curl: (6) Could not resolve host: raw.githubusercontent.com" |
                Should -BeTrue
            Test-WslInstallOutputIndicatesNetworkFailure "Error: Network is unreachable" | Should -BeTrue
            Test-WslInstallOutputIndicatesNetworkFailure "Connection timed out after 30000ms" | Should -BeTrue
        }

        It "does not misclassify a reboot-required or generic failure as a network failure" {
            Test-WslInstallOutputIndicatesNetworkFailure "A restart is required to finish installation." |
                Should -BeFalse
            Test-WslInstallOutputIndicatesNetworkFailure "Ubuntu-24.04 install failed: unknown error 0x80070005" |
                Should -BeFalse
        }
    }
}

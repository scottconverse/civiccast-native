# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "tester-handoff" / "v1.3.0"


def test_macos_proof_resolves_repo_root_from_handoff_script() -> None:
    script = (HANDOFF / "start-macos-proof.sh").read_text(encoding="utf-8")

    assert '$(dirname "${BASH_SOURCE[0]}")/../..' in script
    assert '$(dirname "${BASH_SOURCE[0]}")/../../..' not in script
    assert "git rev-parse --is-inside-work-tree" in script


def test_clean_machine_prompts_start_by_removing_prior_tester_state() -> None:
    mac_prompt = (HANDOFF / "PROMPT-MACOS-CODEX.md").read_text(encoding="utf-8")
    windows_prompt = (HANDOFF / "PROMPT-WINDOWS-CODEX.md").read_text(encoding="utf-8")
    windows_runner = (HANDOFF / "Run-WindowsTesterDirective.ps1").read_text(encoding="utf-8")

    assert 'rm -rf "$ROOT"' not in mac_prompt
    assert "Do not delete $ROOT before clone/update" in mac_prompt
    assert "technical source-build proof" in mac_prompt
    assert "not the full public/non-technical tester journey" in mac_prompt
    assert "Compartmentalization rule" in mac_prompt
    assert "do not run or adapt Windows-only" in mac_prompt
    assert "The Mac proof is source-build only" in mac_prompt
    assert 'git -C "$REPO" clean -fdX' in mac_prompt
    assert mac_prompt.index("git clone -c filter.lfs.process=") < (
        mac_prompt.index("Cleaning prior macOS source-build proof")
    )
    assert "C:\\CivicCastProof" in windows_prompt
    assert "full Windows public/non-technical tester proof path" in windows_prompt
    assert "collect-and-continue proof" in windows_prompt
    assert "expected filename/path mismatch" in windows_prompt
    assert "Run-WindowsTesterDirective.ps1" in windows_prompt
    assert "windows-runner-2026-05-27-11" in windows_prompt
    assert "-Mode Bootstrap" in windows_prompt
    assert "-Mode RecordResult" in windows_prompt
    assert "Do not paste old partial snippets" in windows_prompt
    assert "trap {" in windows_runner
    assert "Write-WindowsProofResult" in windows_runner
    assert "Start-Transcript" in windows_runner
    assert 'Join-Path $env:LOCALAPPDATA "CivicCast Installer"' in windows_runner
    assert "Stop-CivicCastTesterProcesses" in windows_runner
    assert "Invoke-ElevatedCivicCastCleanup" in windows_runner
    assert 'Start-Process -FilePath "powershell.exe"' in windows_runner
    assert "-Verb RunAs -Wait -PassThru" in windows_runner
    assert "Get-CivicCastTesterProcesses" in windows_runner
    assert "$remainingProcesses = @(Stop-CivicCastTesterProcesses)" in windows_runner
    assert '$DirectiveRunnerVersion = "windows-runner-2026-05-27-11"' in windows_runner
    assert "Install-GitPortable" in windows_runner
    assert "Install-GitHubCliPortable" in windows_runner
    assert "Install-GitLfsPortable" not in windows_runner
    assert "Sync-CivicCastArtifactsWithoutLfs" in windows_runner
    assert "Install-NodePortable" in windows_runner
    assert "Test-NpmAvailable" in windows_runner
    assert 'Join-Path $nodeRoot "npm.cmd"' in windows_runner
    assert "npm is still unavailable after winget/portable Node.js fallback" in windows_runner
    assert "Ensure-NodeAndPlaywright" in windows_runner
    assert "https://nodejs.org/download/release/v$version" in windows_runner
    assert "PLAYWRIGHT_BROWSERS_PATH" in windows_runner
    assert "[Environment]::SetEnvironmentVariable" in windows_runner
    assert "Use-CivicCastPlaywright.ps1" in windows_runner
    assert "playwright@1.52.0" in windows_runner
    assert "install chromium" in windows_runner
    assert "winget is unavailable; using portable/direct fallback" in windows_runner
    assert "winget is unavailable. Install App Installer" not in windows_runner
    assert "Runner version: $DirectiveRunnerVersion" in windows_runner
    assert "Invoke-TaskKillCivicCastProcesses" in windows_runner
    assert "Invoke-TaskKillByCivicCastImageName" in windows_runner
    assert "taskkill.exe" in windows_runner
    assert "/IM" in windows_runner
    assert "civiccast-installer.exe" in windows_runner
    assert '*CivicCast*"' not in windows_runner
    assert "RedirectStandardError" in windows_runner
    assert "continuing to elevated cleanup" in windows_runner
    assert "Approve this UAC prompt" in windows_runner
    assert (
        'throw "Previous CivicCast installer process is still running after stop attempt'
        not in windows_runner
    )
    assert "civiccast*.exe" in windows_runner
    assert "C:\\Users\\civic\\AppData\\Local\\CivicCast Installer" in windows_runner
    assert "C:\\Users\\civic\\.local\\share\\civiccast" in windows_runner
    assert "Move-CivicCastTesterPathAside" in windows_runner
    assert "Test-CivicCastSkippableLockedInstallerPath" in windows_runner
    assert "proof data/state roots were cleaned separately" in windows_runner
    assert "continuing to final move-aside fallback" in windows_runner
    assert "checking process state before deciding whether to stop" in windows_runner
    assert "Get-CivicCastCleanupRoots" in windows_runner
    assert "Get-ChildItem -LiteralPath $usersRoot -Directory" in windows_runner
    assert 'Join-Path $profile "AppData\\Local\\CivicCast"' in windows_runner
    assert "Get-CivicCastUninstallRegistryKeys" in windows_runner
    assert "Invoke-CivicCastNsisUninstall" in windows_runner
    assert "uninstall.exe" in windows_runner
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in windows_runner
    assert "Clear-CivicCastTesterWslState" in windows_runner
    assert "Clear-CivicCastTesterWslAppState" in windows_runner
    assert "/root/.local/state/civiccast" in windows_runner
    assert "/root/.local/share/civiccast" in windows_runner
    assert "/mnt/c/Users/*" in windows_runner
    assert "/etc/passwd" in windows_runner
    assert "*/storage/station-state.json" in windows_runner
    assert "*/storage/data/civiccast.sqlite3" in windows_runner
    assert "*/storage/data/civiccast.sqlite3-*" in windows_runner
    assert "*/storage/civiccast.sqlite3-*" in windows_runner
    assert '-ipath "*civiccast*"' in windows_runner
    assert "exit 48" in windows_runner
    assert 'pkill -f "/.local/share/civiccast/"' in windows_runner
    assert '127.0.0.1", 8000' in windows_runner
    assert "exit 45" in windows_runner
    assert "$HOME/.local/share/civiccast" in windows_runner
    assert "exit 46" in windows_runner
    assert "exit 47" in windows_runner
    assert '$ubuntuDistros = @($distros | Where-Object { $_ -match "Ubuntu" })' in windows_runner
    assert "foreach ($distro in $ubuntuDistros)" in windows_runner
    assert "wsl.exe --terminate $distro" in windows_runner
    assert "wsl.exe -d $distro -u root" in windows_runner
    assert "wsl.exe -d $distro --exec" in windows_runner
    assert "wsl.exe --shutdown" in windows_runner
    assert "exit 44" in windows_runner
    assert "Invoke-DocumentedWslBootstrap" in windows_runner
    assert "wsl.exe --install --no-distribution --web-download" in windows_runner
    assert "wsl.exe --install --inbox --no-distribution" in windows_runner
    assert "wsl.exe --install -d Ubuntu-24.04 --no-launch --web-download" in windows_runner
    assert "wsl.exe --install -d Ubuntu-24.04 --no-launch" in windows_runner
    assert "Is-CatastrophicDownloadFailure" in windows_runner
    assert "function Write-CivicCastWslReadyState" in windows_runner
    assert windows_runner.index("if (Test-CivicCastUbuntuReady)") < windows_runner.index(
        "WSL2 Ubuntu 24.04 with Python 3.12 is already ready."
    )
    ready_branch = windows_runner[
        windows_runner.index("if (Test-CivicCastUbuntuReady)") : windows_runner.index(
            'Write-Host "WSL2 Ubuntu 24.04 with Python 3.12 is already ready."'
        )
    ]
    assert "Write-CivicCastWslReadyState" in ready_branch
    assert '"CivicCast"' in windows_runner
    assert '"Ubuntu-24.04", "CivicCast"' not in windows_runner
    assert '($testerDistros -contains $distro) -or ($distro -match "Ubuntu")' in windows_runner
    assert "Removing prior clean-proof WSL distro" in windows_runner
    assert "Failed to unregister prior clean-proof WSL distro" in windows_runner
    assert 'git -C $Repo config user.name "CivicCast Tester"' in windows_runner
    assert "Remove-CivicCastTesterPath" in windows_runner
    assert "Existing WSL state was found before this clean proof" not in windows_runner
    assert '$ErrorActionPreference = "Continue"' in windows_runner
    assert "$wslExitCode -ne 0" in windows_runner
    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ProofStarter" in (
        windows_runner
    )
    assert windows_prompt.index("git clone -c filter.lfs.process=") < (
        windows_prompt.index("powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner")
    )
    assert "Move it aside or delete it, then rerun" not in windows_prompt
    assert "$Repo.failed-" in windows_prompt
    assert '"C:\\CivicCastTester",' not in windows_prompt
    assert "WSL2/Ubuntu prerequisite" in windows_prompt
    assert "Do not stop after bootstrap" in windows_prompt
    assert "proof-directive.md" in windows_prompt
    assert "documented Windows WSL2/Ubuntu prerequisite" in windows_prompt
    assert "REBOOT REQUIRED" in windows_prompt
    assert "wsl.exe` commands only for" in windows_prompt
    assert "version listed in this prompt" in windows_prompt
    assert "record the mismatch as a finding and continue" in windows_prompt
    assert "installs Node.js and Playwright Chromium" in windows_prompt
    assert "Do not manually click installer screens" in windows_prompt
    assert "C:\\CivicCastTester\\Use-CivicCastPlaywright.ps1" in windows_prompt
    assert "Stay Alive For The Next Fix" in windows_prompt
    assert "Start-Sleep -Seconds 600" in windows_prompt
    assert "LatestActionableCommit" in windows_prompt
    assert "Do not rerun only because another tester result commit appeared" in windows_prompt
    assert "dedicated clean proof machine" in windows_prompt
    assert "stale first-admin state survived" in windows_prompt
    assert "operator_console_url" in windows_prompt
    assert "FIRST_ADMIN_ALREADY_COMPLETE_AFTER_CLEANUP" in windows_prompt
    assert "civiccast.sqlite3*" in windows_prompt


def test_latest_directive_routes_prompts_and_results_through_branch() -> None:
    directive = (HANDOFF / "LATEST-TEST-DIRECTIVE.md").read_text(encoding="utf-8")

    assert "PROMPT-WINDOWS-CODEX.md" in directive
    assert "PROMPT-MACOS-CODEX.md" in directive
    assert (
        "Determine the host platform before applying any platform-specific instruction" in directive
    )
    assert "A macOS tester must run only the macOS prompt" in directive
    assert "must ignore every" in directive
    assert "Windows is the full public/non-technical" in directive
    assert "macOS is a technical source-build proof only" in directive
    assert "tester-handoff/v1.3.0/test-results/<platform>" in directive
    assert "commit and push only that result file" in directive
    assert "check the repo for latest test directive" in directive
    assert "codex-skill/civiccast-tester/SKILL.md" in directive
    assert "stop stale `civiccast*.exe`" in directive
    assert "request UAC approval" in directive
    assert "Run-WindowsTesterDirective.ps1" in directive
    assert "windows-runner-2026-05-27-11" in directive
    assert "approve uac prompts" in directive.lower()
    assert "collect-and-continue" in directive
    assert "expected filename/path mismatches" in directive
    assert "do not stop after bootstrap" in directive.lower()
    assert "documented WSL2/Ubuntu prerequisite bootstrap" in directive
    assert "REBOOT REQUIRED" in directive
    assert "failure traps/transcripts" in directive
    assert "installs Node.js and Playwright Chromium" in directive
    assert "Do not manually click installer" in directive
    assert "C:\\CivicCastTester\\Use-CivicCastPlaywright.ps1" in directive
    assert "Tester Watch Loop After Posting A Result" in directive
    assert "After pushing a result, do not stop and wait for Scott" in directive
    assert "newest non-result commit" in directive
    assert "dedicated clean proof machine" in directive
    assert "Ubuntu*` WSL proof state" in directive
    assert "operator_console_url" in directive
    assert "FIRST_ADMIN_ALREADY_COMPLETE_AFTER_CLEANUP" in directive


def test_platform_prompts_push_only_result_files() -> None:
    mac_prompt = (HANDOFF / "PROMPT-MACOS-CODEX.md").read_text(encoding="utf-8")
    windows_runner = (HANDOFF / "Run-WindowsTesterDirective.ps1").read_text(encoding="utf-8")

    assert "test-results/macos" in mac_prompt
    assert 'write_macos_result "PASS"' in mac_prompt
    assert "PASS or FAIL" not in mac_prompt
    assert "replace this line" not in mac_prompt
    assert "- OS: $os_version" in mac_prompt
    assert "- Architecture: $arch" in mac_prompt
    assert 'git -C "$REPO" config user.name "CivicCast Tester"' in mac_prompt
    assert "test-results\\windows" in windows_runner
    assert "- OS: $($Os.Caption) $($Os.Version) build $($Os.BuildNumber)" in windows_runner
    assert "- Architecture: $env:PROCESSOR_ARCHITECTURE" in windows_runner
    assert "trap 'on_macos_error" in mac_prompt
    assert "write_macos_result" in mac_prompt
    assert "TRANSCRIPT_PATH" in mac_prompt
    assert 'commit -s -m "test: add macos proof result' in mac_prompt
    assert 'commit -s -m "test: add windows proof result' in windows_runner
    assert "push origin tester/v1.3.0-pullable-proof-kit" in mac_prompt
    assert "push origin tester/v1.3.0-pullable-proof-kit" in windows_runner
    assert "LAST_TESTED_ACTIONABLE_COMMIT" in mac_prompt
    assert "sleep 600" in mac_prompt
    assert "Do not rerun only because another tester result" in mac_prompt


def test_platform_prompts_install_tester_machine_skill() -> None:
    mac_prompt = (HANDOFF / "PROMPT-MACOS-CODEX.md").read_text(encoding="utf-8")
    windows_prompt = (HANDOFF / "PROMPT-WINDOWS-CODEX.md").read_text(encoding="utf-8")
    skill = (HANDOFF / "codex-skill" / "civiccast-tester" / "SKILL.md").read_text(encoding="utf-8")

    assert "check the repo for latest test directive" in skill
    assert "tester/v1.3.0-pullable-proof-kit" in skill
    assert "LATEST-TEST-DIRECTIVE.md" in skill
    assert "failure traps/transcripts" in skill
    assert "Run-WindowsTesterDirective.ps1" in skill
    assert "windows-runner-2026-05-27-11" in skill
    assert "Approve" in skill
    assert "collect-and-continue" in skill
    assert "expected filename/path mismatches" in skill
    assert "do not stop after bootstrap" in skill.lower()
    assert "REBOOT REQUIRED" in skill
    assert "installs Node.js and Playwright Chromium" in skill
    assert "Do not manually click installer" in skill
    assert "C:\\CivicCastTester\\Use-CivicCastPlaywright.ps1" in skill
    assert "After pushing a result file, do not stop and wait for Scott" in skill
    assert "Every 10 minutes" in skill
    assert "Watch Loop" in skill
    assert "dedicated clean proof machine" in skill
    assert "first-admin state survived" in skill
    assert "operator_console_url" in skill
    assert "FIRST_ADMIN_ALREADY_COMPLETE_AFTER_CLEANUP" in skill
    assert "First identify the host OS and compartmentalize the instructions" in skill
    assert "run only `PROMPT-MACOS-CODEX.md`" in skill
    assert "ignore all Windows runner" in skill
    assert "skills\\civiccast-tester" in windows_prompt
    assert "skills/civiccast-tester" in mac_prompt
    assert "TESTER-MACHINE-OPERATING-NOTE.md" in (
        HANDOFF / "Run-WindowsTesterDirective.ps1"
    ).read_text(encoding="utf-8")
    assert "TESTER-MACHINE-OPERATING-NOTE.md" in mac_prompt
    windows_runner = (HANDOFF / "Run-WindowsTesterDirective.ps1").read_text(encoding="utf-8")
    skill_install_index = windows_runner.index("Installed CivicCast tester Codex skill")
    artifact_sync_index = windows_runner.index(
        "Sync-CivicCastArtifactsWithoutLfs", skill_install_index
    )
    assert skill_install_index < artifact_sync_index
    assert mac_prompt.index("Installed CivicCast tester Codex skill") < (
        mac_prompt.index("Skipping Git LFS artifact pull; macOS proof is source-build only.")
    )
    assert "LFS_DISABLED_ARTIFACT_MISSING" in windows_runner
    assert "C:\\CivicCastTester\\artifact-cache\\v1.3.0" in skill


def test_fresh_machine_helpers_match_canonical_result_paths() -> None:
    windows_helper = (HANDOFF / "Bootstrap-CivicCastWindowsFreshMachine.ps1").read_text(
        encoding="utf-8"
    )
    mac_helper = (HANDOFF / "bootstrap-civiccast-macos-fresh-machine.sh").read_text(
        encoding="utf-8"
    )
    readme = (HANDOFF / "README.md").read_text(encoding="utf-8")

    assert "Run-WindowsTesterDirective.ps1" in windows_helper
    assert "Start-CivicCastWindowsProof.ps1" not in windows_helper
    assert "Move it aside or delete it, then rerun" not in windows_helper
    assert "$Repo.failed-" in windows_helper
    assert 'git -C $Repo config user.name "CivicCast Tester"' in windows_helper
    assert "Run-WindowsTesterDirective.ps1" in readme
    assert "canonical Windows Codex runner" in readme
    assert "portable Git/GitHub CLI downloads" in readme

    assert "write_macos_result" in mac_helper
    assert 'write_macos_result "PASS"' in mac_helper
    assert 'git -C "$REPO" config user.name "CivicCast Tester"' in mac_helper
    assert "Transcript: $TRANSCRIPT_PATH" in mac_helper
    assert "- OS: $os_version" in mac_helper


def test_tester_handoff_does_not_pull_lfs_artifacts() -> None:
    active_files = [
        HANDOFF / "Run-WindowsTesterDirective.ps1",
        HANDOFF / "PROMPT-WINDOWS-CODEX.md",
        HANDOFF / "LATEST-TEST-DIRECTIVE.md",
        HANDOFF / "PROMPT-MACOS-CODEX.md",
        HANDOFF / "Bootstrap-CivicCastWindowsFreshMachine.ps1",
        HANDOFF / "bootstrap-civiccast-macos-fresh-machine.sh",
        HANDOFF / "start-macos-proof.sh",
        HANDOFF / "codex-skill" / "civiccast-tester" / "SKILL.md",
    ]

    for path in active_files:
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "git lfs pull" not in lower
        assert "git -c $repo lfs" not in lower
        assert 'git -c "$repo" lfs' not in lower
        assert "git-lfs-windows" not in lower

    windows_runner = (HANDOFF / "Run-WindowsTesterDirective.ps1").read_text(encoding="utf-8")
    directive = (HANDOFF / "LATEST-TEST-DIRECTIVE.md").read_text(encoding="utf-8")
    skill = (HANDOFF / "codex-skill" / "civiccast-tester" / "SKILL.md").read_text(encoding="utf-8")

    assert "Sync-CivicCastArtifactsWithoutLfs" in windows_runner
    assert "LFS_DISABLED_ARTIFACT_MISSING" in windows_runner
    assert "LFS_DISABLED_ARTIFACT_MISSING" in directive
    assert "LFS_DISABLED_ARTIFACT_MISSING" in skill
    assert "artifact-cache\\v1.3.0" in windows_runner

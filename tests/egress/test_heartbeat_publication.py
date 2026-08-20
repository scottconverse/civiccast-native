# SPDX-License-Identifier: Apache-2.0
"""Behavioral proof for the tester heartbeat Git publication chain."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HEARTBEAT_SCRIPT = REPO_ROOT / "tester-handoff" / "v3.0" / "soak-4h" / "scripts" / "heartbeat.ps1"
TESTER_BRANCH = "tester/v3.0-finish-line-4h-soak"


def test_heartbeat_resolves_portable_bash_command() -> None:
    source = HEARTBEAT_SCRIPT.read_text(encoding="utf-8")

    assert "Get-Command bash -ErrorAction SilentlyContinue" in source
    assert "Get-Command bash.exe -ErrorAction SilentlyContinue" not in source


def _powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell.exe")
    if executable is None:
        if os.name != "nt":
            pytest.skip("heartbeat publication is exercised on Windows PowerShell runners")
        pytest.fail("PowerShell is required for heartbeat publication coverage")
    return executable


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )


def _install_runtime_fixture(repo: Path) -> None:
    probes = repo / "tester-handoff" / "v3.0" / "soak-4h" / "synthetic-probes"
    scripts = repo / "tester-handoff" / "v3.0" / "soak-4h" / "scripts"
    probes.mkdir(parents=True)
    scripts.mkdir(parents=True)
    for name in ("paywall.sh", "recording.sh", "agenda.sh"):
        (probes / name).write_text(f"#!/bin/sh\necho {name}-ran\nexit 0\n", encoding="utf-8")
    (scripts / "verify-egress.ps1").write_text(
        "param([int]$HeartbeatIndex, [string]$Stamp)\nWrite-Output 'egress-ran'\nexit 0\n",
        encoding="utf-8",
    )


def _tester_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "tester"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", str(repo))
    _git(repo, "checkout", "-b", TESTER_BRANCH)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _install_runtime_fixture(repo)
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=tester@example.invalid",
        "-c",
        "user.name=Heartbeat Test",
        "commit",
        "-m",
        "seed",
    )
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", TESTER_BRANCH)
    return repo, remote


def _run_heartbeat(
    repo: Path, run_root: Path, *, path_prefix: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "NONCE": "heartbeat-contract-nonce",
            "TARGET_COMMIT": "a" * 40,
            "RUN_ROOT": str(run_root),
            "DIRECTIVE_REPO": str(repo),
            "BASE_URL": "http://127.0.0.1:9",
            "TOKEN": "unused-test-token",
        }
    )
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    executable = _powershell()
    command = [executable]
    if Path(executable).name.lower() == "powershell.exe":
        command.extend(["-ExecutionPolicy", "Bypass"])
    command.extend(["-NoProfile", "-File", str(HEARTBEAT_SCRIPT), "-HeartbeatIndex", "1"])
    return subprocess.run(command, env=env, capture_output=True, text=True, check=False)


def _write_git_shim(shim_dir: Path, *, real_git: str, windows_body: str, posix_body: str) -> None:
    (shim_dir / "git.cmd").write_text(
        f'@echo off\n{windows_body}\n"{real_git}" %*\nexit /b %errorlevel%\n',
        encoding="utf-8",
    )
    posix_shim = shim_dir / "git"
    posix_shim.write_text(
        f'#!/bin/sh\n{posix_body}\nexec {shlex.quote(real_git)} "$@"\n',
        encoding="utf-8",
    )
    posix_shim.chmod(0o755)


def test_heartbeat_commits_and_pushes_exact_written_json(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    run_root = tmp_path / "run"

    completed = _run_heartbeat(repo, run_root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "heartbeat 1 written and pushed:" in completed.stdout
    repo_files = list((repo / "tester-handoff" / "v3.0" / "heartbeats").glob("*.json"))
    local_files = list((run_root / "heartbeats").glob("*.json"))
    assert len(repo_files) == len(local_files) == 1
    assert repo_files[0].read_bytes() == local_files[0].read_bytes()
    assert _git(repo, "status", "--porcelain").stdout == ""
    relative = repo_files[0].relative_to(repo).as_posix()
    assert f"origin/{TESTER_BRANCH}:{relative}" in completed.stdout
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() in completed.stdout
    remote_json = _git(tmp_path, "--git-dir", str(remote), "show", f"{TESTER_BRANCH}:{relative}")
    expected_filtered_blob = _git(
        repo, "hash-object", "--path", relative, str(repo_files[0])
    ).stdout.strip()
    remote_blob = _git(
        tmp_path, "--git-dir", str(remote), "rev-parse", f"{TESTER_BRANCH}:{relative}"
    ).stdout.strip()
    assert remote_blob == expected_filtered_blob
    published = json.loads(remote_json.stdout)
    assert set(published["probes"]) == {"paywall.sh", "recording.sh", "agenda.sh"}
    assert all(result["exit_code"] == 0 for result in published["probes"].values())
    assert published["egress_state"]["status"] == "pass"
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_heartbeat_fails_closed_when_push_fails(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    _git(repo, "remote", "set-url", "--push", "origin", str(tmp_path / "missing-remote.git"))

    completed = _run_heartbeat(repo, tmp_path / "run")

    assert completed.returncode != 0
    assert "git push failed" in completed.stdout + completed.stderr
    assert "written and pushed" not in completed.stdout
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert _git(repo, "status", "--porcelain").stdout == ""

    _git(repo, "remote", "set-url", "--push", "origin", str(remote))
    recovered = _run_heartbeat(repo, tmp_path / "recovered-run")

    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert "written and pushed" in recovered.stdout


def test_heartbeat_pushes_current_commit_even_from_differently_named_branch(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    _git(repo, "checkout", "-b", "local-heartbeat-run")

    completed = _run_heartbeat(repo, tmp_path / "run")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    remote_files = _git(
        tmp_path,
        "--git-dir",
        str(remote),
        "ls-tree",
        "-r",
        "--name-only",
        TESTER_BRANCH,
    ).stdout.splitlines()
    assert (
        len([path for path in remote_files if path.startswith("tester-handoff/v3.0/heartbeats/")])
        == 1
    )
    assert (
        _git(repo, "rev-parse", "HEAD").stdout
        == _git(tmp_path, "--git-dir", str(remote), "rev-parse", TESTER_BRANCH).stdout
    )


def test_heartbeat_refuses_to_commit_unrelated_staged_content(tmp_path: Path) -> None:
    repo, _remote = _tester_repo(tmp_path)
    (repo / "unrelated.txt").write_text("must not ride with heartbeat\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")

    completed = _run_heartbeat(repo, tmp_path / "run")

    assert completed.returncode != 0
    assert "heartbeat must be the only staged path" in completed.stdout + completed.stderr
    assert "written and pushed" not in completed.stdout
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert _git(repo, "status", "--porcelain").stdout == "A  unrelated.txt\n"


def test_heartbeat_disables_local_hooks_for_evidence_commit(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    run_root = tmp_path / "run"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\nprintf 'hook mutation\\n' > hook-added.txt\ngit add hook-added.txt\n",
        encoding="utf-8",
    )
    post_hook = repo / ".git" / "hooks" / "post-commit"
    post_hook.write_text(
        f"#!/bin/sh\ngit push origin HEAD:refs/heads/{TESTER_BRANCH}\n",
        encoding="utf-8",
    )
    contaminated_hooks = run_root / ".heartbeat-hooks-disabled"
    contaminated_hooks.mkdir(parents=True)
    (contaminated_hooks / "pre-commit").write_text(
        hook.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (contaminated_hooks / "post-commit").write_text(
        post_hook.read_text(encoding="utf-8"), encoding="utf-8"
    )

    completed = _run_heartbeat(repo, run_root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "written and pushed" in completed.stdout
    assert (
        _git(
            tmp_path, "--git-dir", str(remote), "rev-list", "--count", TESTER_BRANCH
        ).stdout.strip()
        == "2"
    )
    remote_paths = _git(
        tmp_path, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", TESTER_BRANCH
    ).stdout.splitlines()
    assert "hook-added.txt" not in remote_paths


def test_heartbeat_refuses_to_publish_unrelated_ahead_commit(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    (repo / "ahead.txt").write_text("not heartbeat evidence\n", encoding="utf-8")
    _git(repo, "add", "ahead.txt")
    _git(
        repo,
        "-c",
        "user.email=tester@example.invalid",
        "-c",
        "user.name=Heartbeat Test",
        "commit",
        "-m",
        "unrelated ahead commit",
    )
    local_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_sha = _git(tmp_path, "--git-dir", str(remote), "rev-parse", TESTER_BRANCH).stdout.strip()

    completed = _run_heartbeat(repo, tmp_path / "run")

    assert completed.returncode != 0
    assert "local HEAD must match" in completed.stdout + completed.stderr
    assert local_sha in completed.stdout + completed.stderr
    assert remote_sha in completed.stdout + completed.stderr
    assert "written and pushed" not in completed.stdout
    assert (
        _git(
            tmp_path, "--git-dir", str(remote), "rev-list", "--count", TESTER_BRANCH
        ).stdout.strip()
        == "1"
    )


def test_heartbeat_tolerates_ls_remote_warning_before_exact_ref(tmp_path: Path) -> None:
    repo, _remote = _tester_repo(tmp_path)
    shim_dir = tmp_path / "git-shim"
    shim_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    _write_git_shim(
        shim_dir,
        real_git=real_git,
        windows_body='if "%1"=="ls-remote" echo warning: simulated advisory 1>&2',
        posix_body='if [ "${1:-}" = "ls-remote" ]; then echo "warning: simulated advisory" >&2; fi',
    )

    completed = _run_heartbeat(repo, tmp_path / "run", path_prefix=shim_dir)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "written and pushed" in completed.stdout


def test_heartbeat_pushes_verified_commit_when_local_head_moves(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    shim_dir = tmp_path / "git-race-shim"
    shim_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    _write_git_shim(
        shim_dir,
        real_git=real_git,
        windows_body=(
            'if "%1"=="push" (\n'
            "  echo race mutation>race.txt\n"
            f'  "{real_git}" add race.txt\n'
            f'  "{real_git}" -c user.email=race@example.invalid -c user.name=Race commit -m "race mutation"\n'
            ")"
        ),
        posix_body=(
            'if [ "${1:-}" = "push" ]; then\n'
            "  echo race mutation >race.txt\n"
            f"  {shlex.quote(real_git)} add race.txt\n"
            f"  {shlex.quote(real_git)} -c user.email=race@example.invalid "
            '-c user.name=Race commit -m "race mutation"\n'
            "fi"
        ),
    )

    completed = _run_heartbeat(repo, tmp_path / "run", path_prefix=shim_dir)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    remote_paths = _git(
        tmp_path, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", TESTER_BRANCH
    ).stdout.splitlines()
    assert "race.txt" not in remote_paths
    assert (
        len([path for path in remote_paths if path.startswith("tester-handoff/v3.0/heartbeats/")])
        == 1
    )


def test_failed_push_preserves_concurrently_moved_local_head(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    shim_dir = tmp_path / "git-failed-race-shim"
    shim_dir.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    _write_git_shim(
        shim_dir,
        real_git=real_git,
        windows_body=(
            'if "%1"=="push" (\n'
            "  echo race mutation>race.txt\n"
            f'  "{real_git}" add race.txt\n'
            f'  "{real_git}" -c user.email=race@example.invalid -c user.name=Race commit -m "race mutation"\n'
            "  echo simulated push failure 1>&2\n"
            "  exit /b 1\n"
            ")"
        ),
        posix_body=(
            'if [ "${1:-}" = "push" ]; then\n'
            "  echo race mutation >race.txt\n"
            f"  {shlex.quote(real_git)} add race.txt\n"
            f"  {shlex.quote(real_git)} -c user.email=race@example.invalid "
            '-c user.name=Race commit -m "race mutation"\n'
            '  echo "simulated push failure" >&2\n'
            "  exit 1\n"
            "fi"
        ),
    )

    completed = _run_heartbeat(repo, tmp_path / "run", path_prefix=shim_dir)

    assert completed.returncode != 0
    assert "local HEAD changed during failed heartbeat push" in completed.stdout + completed.stderr
    assert _git(repo, "show", "HEAD:race.txt").stdout.strip() == "race mutation"
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "3"
    assert (
        _git(
            tmp_path, "--git-dir", str(remote), "rev-list", "--count", TESTER_BRANCH
        ).stdout.strip()
        == "1"
    )


def test_heartbeat_records_probe_and_egress_failures_before_publication(tmp_path: Path) -> None:
    repo, remote = _tester_repo(tmp_path)
    probes = repo / "tester-handoff" / "v3.0" / "soak-4h" / "synthetic-probes"
    (probes / "recording.sh").write_text("#!/bin/sh\necho failed-probe\nexit 7\n", encoding="utf-8")
    verifier = repo / "tester-handoff" / "v3.0" / "soak-4h" / "scripts" / "verify-egress.ps1"
    verifier.write_text(
        "param([int]$HeartbeatIndex, [string]$Stamp)\nWrite-Output 'failed-egress'\nexit 3\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=tester@example.invalid",
        "-c",
        "user.name=Heartbeat Test",
        "commit",
        "-m",
        "configure failing runtime probes",
    )
    _git(repo, "push", "origin", TESTER_BRANCH)

    completed = _run_heartbeat(repo, tmp_path / "run")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    heartbeat_paths = _git(
        tmp_path,
        "--git-dir",
        str(remote),
        "ls-tree",
        "-r",
        "--name-only",
        TESTER_BRANCH,
    ).stdout.splitlines()
    heartbeat_path = next(
        path for path in heartbeat_paths if path.startswith("tester-handoff/v3.0/heartbeats/")
    )
    published = json.loads(
        _git(tmp_path, "--git-dir", str(remote), "show", f"{TESTER_BRANCH}:{heartbeat_path}").stdout
    )
    assert published["probes"]["recording.sh"]["exit_code"] == 7
    assert published["egress_state"]["status"] == "fail"
    assert published["egress_state"]["exit_code"] == 3

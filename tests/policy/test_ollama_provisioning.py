# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""rc17 D2 — installer-owned Ollama provisioning, minimal, inside the walls.

R1 detect-healthy, R2 absent-install, R3 resumability, and R4 non-blocking are
exercised at script-logic level (real Git Bash execution against a faked
`ollama` on PATH and a shimmed venv python, matching the established pattern
in ``test_windows_wsl_bootstrap_script.py`` for the console-script/launcher
controls). Real package installs, the real ollama.com download, and real WSL
execution are the VM gauntlet's job, not this suite's.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADLESS_BOOTSTRAP = (
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "resources" / "headless-bootstrap.ps1"
)


def _source() -> str:
    return HEADLESS_BOOTSTRAP.read_text(encoding="utf-8")


def _ollama_script() -> str:
    """The embedded ``$ollamaScript`` bash body, verbatim from production source."""
    source = _source()
    marker = "    $ollamaScript = @'\n"
    start = source.index(marker) + len(marker)
    return source[start : source.index("\n'@", start)]


def _bash() -> str:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    resolved = str(git_bash) if git_bash.exists() else shutil.which("bash")
    assert resolved is not None, (
        "Bash is required to exercise the embedded Ollama provisioning script"
    )
    return resolved


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        return f"/{resolved.drive[0].lower()}/{resolved.as_posix()[3:]}"
    return resolved.as_posix()


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _real_selected_tags() -> list[str]:
    """The REAL selection surface, imported in-process (where pytest's own
    interpreter is guaranteed to import civiccast on every runner). Keeps
    the fixture honest to production without a hardcoded tag list."""
    from civiccast.installer.model_download import (
        TRANSLATION_MODEL,
        summary_provisioning_tags,
    )

    return [*summary_provisioning_tags(), TRANSLATION_MODEL]


def _stub_venv(root: Path) -> Path:
    """A fake ``<venv>/bin/python`` that SERVES the model list itself.

    Two prior shim designs (exec the pytest interpreter; exec it with
    ``-I`` stripped + PYTHONPATH injected) both inherited fragile
    assumptions about the RUNNER's interpreter and failed on the Linux
    cleanroom. The contract under test is only "the venv python prints the
    selected tags" -- so the fake prints the real tags directly, computed
    in-process by ``_real_selected_tags()`` from the same production
    module the real venv python would import. No interpreter inheritance,
    identical behavior on every OS, still no hardcoded tag list."""
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True)
    tag_lines = "\n".join(f'printf "%s\\n" "{t}"' for t in _real_selected_tags())
    _write_executable(
        venv / "bin" / "python",
        "#!/usr/bin/env bash\n" + tag_lines + "\n",
    )
    return venv


def _stub_broken_venv(root: Path) -> Path:
    """A fake ``<venv>/bin/python`` whose model-selection call FAILS --
    the cleanroom-discovered scenario where the selection step errors and
    the phase must report honestly instead of silently completing."""
    venv = root / "venv"
    (venv / "bin").mkdir(parents=True)
    _write_executable(
        venv / "bin" / "python",
        '#!/usr/bin/env bash\necho "simulated venv python failure" >&2\nexit 1\n',
    )
    return venv


def _fake_ollama(
    bin_dir: Path,
    *,
    models: list[str],
    pull_log: Path,
    fail: set[str] = frozenset(),
    version: str = "0.24.0",
) -> None:
    """A stand-in ``ollama`` reporting ``models`` as already installed and
    recording every ``pull`` invocation (so a test can assert calls were
    skipped, not just that the outcome looks right)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    list_rows = "\n".join(f'  echo -e "{m}\\tabc123\\t1 GB\\tnow"' for m in models)
    fail_condition = " || ".join(f'"$2" = "{m}"' for m in fail)
    fail_check = f"[[ {fail_condition} ]]" if fail_condition else "false"
    script = f"""#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  --version)
    echo "ollama version is {version}"
    ;;
  list)
    echo -e "NAME\\tID\\tSIZE\\tMODIFIED"
{list_rows}
    ;;
  pull)
    echo "$2" >> "{_bash_path(pull_log)}"
    if {fail_check}; then
      echo "simulated pull failure for $2" >&2
      exit 1
    fi
    ;;
  *)
    echo "unhandled fake ollama subcommand: $*" >&2
    exit 1
    ;;
esac
"""
    _write_executable(bin_dir / "ollama", script)


def _fake_unresponsive_ollama(bin_dir: Path) -> None:
    """A stand-in ``ollama`` whose binary exists but whose daemon never
    answers -- ``--version`` works, ``list`` always fails."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  --version) echo "ollama version is 0.19.0" ;;
  list) echo "Error: could not connect to ollama app" >&2; exit 1 ;;
  *) echo "unhandled fake ollama subcommand: $*" >&2; exit 1 ;;
esac
"""
    _write_executable(bin_dir / "ollama", script)


def _run_ollama_script(
    *, venv: Path, path_dirs: list[Path], cwd: Path
) -> subprocess.CompletedProcess[str]:
    script = _ollama_script().replace(
        'venv="/opt/civiccast/current/venv"',
        f'venv="{_bash_path(venv)}"',
    )
    assert f'venv="{_bash_path(venv)}"' in script, (
        "venv substitution did not match production source"
    )
    posix_dirs = [_bash_path(d) for d in path_dirs]
    # A genuinely isolated PATH: the fakes plus ONLY Git Bash's own coreutils
    # (awk/grep/sha256sum/mktemp/...). The real Windows PATH is deliberately
    # NOT inherited -- a real system `python3`/`dpkg`/`curl` leaking in here
    # previously let a test reach the real ollama.com download over the
    # network. If the script needs a tool this PATH doesn't have, it must
    # fail fast (command not found), never silently succeed against the real
    # machine.
    # Platform arm (cleanroom fix): on Windows the coreutils come from Git
    # Bash's own dirs; on POSIX (the Linux cleanroom gate) an ALLOWLISTED
    # symlink farm provides the same basic tools -- deliberately excluding
    # curl/wget/python3 so the fail-fast isolation property holds on every
    # OS (a real network tool leaking in is exactly the incident this
    # harness exists to prevent).
    if os.name == "nt":
        core_dirs = [
            Path(d)
            for d in (r"C:\Program Files\Git\usr\bin", r"C:\Program Files\Git\bin")
            if Path(d).exists()
        ]
    else:
        allow = [
            "sh",
            "bash",
            "env",
            "awk",
            "gawk",
            "grep",
            "sed",
            "cat",
            "cut",
            "tr",
            "head",
            "tail",
            "sort",
            "uniq",
            "wc",
            "mktemp",
            "mkdir",
            "rm",
            "mv",
            "cp",
            "ln",
            "chmod",
            "touch",
            "dirname",
            "basename",
            "readlink",
            "sha256sum",
            "tar",
            "gzip",
            "date",
            "sleep",
            "true",
            "false",
            "test",
        ]
        corebin = cwd / ".corebin"
        corebin.mkdir(exist_ok=True)
        for tool in allow:
            real = shutil.which(tool)
            if real and not (corebin / tool).exists():
                (corebin / tool).symlink_to(real)
        core_dirs = [corebin]
    env = {
        "PATH": ":".join([*posix_dirs, *(_bash_path(d) for d in core_dirs)]),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
    }
    return subprocess.run(
        [_bash(), "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# R1 -- detect-healthy: a healthy existing install (matching pinned version +
# every hardware-selected model already present) skips BOTH install and pulls.
# ---------------------------------------------------------------------------


def test_healthy_existing_install_with_models_present_skips_install_and_pulls(
    tmp_path: Path,
) -> None:
    venv = _stub_venv(tmp_path)
    fakes = tmp_path / "fakes"
    pull_log = tmp_path / "pulls.log"
    _fake_ollama(
        fakes,
        models=["gemma4:12b", "gemma4:e4b", "translategemma:4b"],
        pull_log=pull_log,
    )

    completed = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" in completed.stdout
    assert "reusing it without changes" in completed.stdout
    assert "installing the pinned local AI engine" not in completed.stdout
    assert not pull_log.exists(), (
        f"no model should have been pulled: {pull_log.read_text() if pull_log.exists() else ''}"
    )


def test_healthy_existing_install_missing_one_model_pulls_only_that_model(tmp_path: Path) -> None:
    venv = _stub_venv(tmp_path)
    fakes = tmp_path / "fakes"
    pull_log = tmp_path / "pulls.log"
    _fake_ollama(
        fakes,
        models=["gemma4:12b", "translategemma:4b"],
        pull_log=pull_log,
    )

    completed = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" in completed.stdout
    pulled = pull_log.read_text(encoding="utf-8").splitlines()
    assert pulled == ["gemma4:e4b"], pulled


# ---------------------------------------------------------------------------
# The wall: a present-but-unhealthy existing install is refused, not forced.
# ---------------------------------------------------------------------------


def test_unhealthy_existing_install_is_refused_not_overwritten(tmp_path: Path) -> None:
    venv = _stub_venv(tmp_path)
    fakes = tmp_path / "fakes"
    _fake_unresponsive_ollama(fakes)

    completed = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)

    assert completed.returncode != 0
    assert "not responding to 'ollama list'" in completed.stderr
    assert "Leaving it untouched" in completed.stderr
    assert "installing the pinned local AI engine" not in completed.stdout
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" not in completed.stdout


# ---------------------------------------------------------------------------
# R2 -- absent: the install branch fires (real download/systemd mechanics are
# VM-gauntlet scope; asserted structurally below).
# ---------------------------------------------------------------------------


def test_absent_ollama_reaches_the_pinned_install_branch(tmp_path: Path) -> None:
    venv = _stub_venv(tmp_path)
    empty_path_dir = tmp_path / "empty"
    empty_path_dir.mkdir()

    completed = _run_ollama_script(venv=venv, path_dirs=[empty_path_dir], cwd=tmp_path)

    # No real apt-get/dpkg/curl/systemctl on this narrow PATH: the install
    # branch is reached (proving the absent-triggers-install decision) and
    # then fails loudly on the first missing real tool, rather than silently
    # falling through to "reuse" or "refuse".
    assert (
        "did not find an existing Ollama install; installing the pinned local AI engine"
        in completed.stdout
    )
    assert completed.returncode != 0
    assert "reusing it without changes" not in completed.stdout
    assert "not responding to 'ollama list'" not in completed.stderr


# ---------------------------------------------------------------------------
# R3 -- resumability: a failed pull leaves ollama untouched; a re-run resumes
# only the still-missing model, without reinstalling.
# ---------------------------------------------------------------------------


def test_failed_pull_resumes_on_rerun_without_reinstalling_ollama(tmp_path: Path) -> None:
    venv = _stub_venv(tmp_path)
    fakes = tmp_path / "fakes"
    pull_log = tmp_path / "pulls.log"
    # First run: gemma4:e4b already present, gemma4:12b and translategemma:4b
    # missing, and the fake ollama simulates translategemma:4b failing.
    _fake_ollama(
        fakes,
        models=["gemma4:e4b"],
        pull_log=pull_log,
        fail={"translategemma:4b"},
    )

    first = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)

    assert first.returncode != 0
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" not in first.stdout
    assert "could not download every local AI model" in first.stderr
    first_pulls = pull_log.read_text(encoding="utf-8").splitlines()
    assert set(first_pulls) == {"gemma4:12b", "translategemma:4b"}
    assert "installing the pinned local AI engine" not in first.stdout, (
        "a partial model failure must never trigger an ollama reinstall"
    )

    # Second run ("re-run"): the fake now reports the successfully-pulled
    # gemma4:12b as present too (as the real daemon would), and no longer
    # fails translategemma:4b. Resume must retry ONLY the model still missing.
    pull_log.write_text("", encoding="utf-8")
    _fake_ollama(
        fakes,
        models=["gemma4:e4b", "gemma4:12b"],
        pull_log=pull_log,
    )

    second = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)

    assert second.returncode == 0, second.stderr
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" in second.stdout
    second_pulls = pull_log.read_text(encoding="utf-8").splitlines()
    assert second_pulls == ["translategemma:4b"], second_pulls
    assert "installing the pinned local AI engine" not in second.stdout


# ---------------------------------------------------------------------------
# Structural controls: version pin, sha-verified download, hardware-selection
# reuse (wall 3: no invented catalog), and non-blocking wiring (wall 4/R4).
# ---------------------------------------------------------------------------


def test_ollama_version_is_pinned_exactly_and_not_a_reusable_variable() -> None:
    script = _ollama_script()
    assert script.count('ollama_version="0.24.0"') == 1, (
        "the version must be assigned exactly once, not threaded through as a reusable variable"
    )
    assert "0.32.1" not in script
    assert "OLLAMA_VERSION" not in _source(), (
        "no top-level PS version variable inviting a future bump"
    )


def test_absent_install_uses_sha_verified_pinned_download() -> None:
    script = _ollama_script()
    install_start = script.index("install_pinned_ollama() {")
    install_end = script.index("\n}\n", install_start)
    body = script[install_start:install_end]

    assert (
        "https://github.com/ollama/ollama/releases/download/v${ollama_version}/${archive}" in body
    )
    download = body.index("urlretrieve")
    verify = body.index('actual_sha256="$(sha256sum "${archive_path}"')
    compare = body.index('if [ "${actual_sha256}" != "${sha256}" ]')
    extract = body.index("tar --zstd -xf")
    assert download < verify < compare < extract
    # Real, curl-verified sha256 values for the pinned v0.24.0 linux release
    # assets (github.com/ollama/ollama/releases/download/v0.24.0/sha256sum.txt).
    assert "15c5f8d66ba06e0d3b4719df8868612dbd66e14e82760929bb3552e1657cdcdb" in body
    assert "6e9a3ce5f64e93312902e39c420ec336255f078a368ca25e99b339d08a6dfa4b" in body


def test_absent_install_lands_at_standard_path_not_a_civiccast_owned_tree() -> None:
    """Wall 4: no installer-owned parallel Ollama tree, no dedicated
    release/cutover machinery -- the pinned install (when one is even needed)
    lands where a later run's OWN detect step (``command -v ollama``) will
    find it as an ordinary system install, not a second CivicCast-only copy.
    """
    script = _ollama_script()
    install_start = script.index("install_pinned_ollama() {")
    install_end = script.index("\n}\n", install_start)
    body = script[install_start:install_end]

    assert "/opt/civiccast/ollama" not in body
    assert "-C /usr/local" in body
    # No CivicCast-owned versioned-release/cutover tree for Ollama (PR #296's
    # rejected shape: ollama_install_root/releases/<version> + a "current"
    # symlink swap CivicCast alone manages). The GitHub download URL itself
    # legitimately contains "releases/" (github.com/.../releases/download/...)
    # so check for the OWNED-TREE pattern specifically, not that substring.
    assert "ollama_release_path" not in body
    assert "ollama_current" not in body
    assert "ollama_install_root" not in body
    assert ".next" not in body


def test_model_selection_reuses_existing_hardware_selection_no_invented_catalog() -> None:
    script = _ollama_script()
    assert (
        "from civiccast.installer.model_download import summary_provisioning_tags, TRANSLATION_MODEL"
        in script
    )
    # Wall 3: don't hand-roll the tag list this file already owns.
    assert "gemma4:12b" not in script
    assert "gemma4:e4b" not in script
    assert "translategemma:4b" not in script


def test_model_phase_runs_only_after_ready_and_never_blocks_it() -> None:
    source = _source()

    already_healthy_start = source.index("if (Test-ServiceAlreadyHealthy) {")
    already_healthy_end = source.index("\n    }\n", already_healthy_start)
    already_healthy_body = source[already_healthy_start:already_healthy_end]
    already_healthy_call = already_healthy_body.index("Invoke-OllamaModelPhase")
    already_healthy_log = already_healthy_body.index("leaving it untouched")
    assert already_healthy_log < already_healthy_call, (
        "the model phase must never gate or precede the already-healthy no-op"
    )

    main_ready = source.index('Write-State "runtime" "ready" "CivicCast prepared storage')
    main_start_host = source.index("Start-RuntimeHost", main_ready)
    main_model_call = source.index("Invoke-OllamaModelPhase -OperatorUrl $operatorUrl", main_ready)
    assert main_ready < main_start_host < main_model_call, (
        "local AI model setup must run strictly after the dashboard is ready and started"
    )


def test_model_phase_failure_is_non_fatal_and_never_reverts_ready() -> None:
    source = _source()
    phase_start = source.index("function Invoke-OllamaModelPhase")
    phase_end = source.index("\n}\n", phase_start)
    body = source[phase_start:phase_end]

    assert "try {" in body
    assert "} catch {" in body
    catch_body = body[body.index("} catch {") :]
    assert 'Write-State "runtime" "ready"' in catch_body, (
        "a model failure must re-affirm ready (with an honest note), never flip to error"
    )
    assert 'Write-State "runtime" "error"' not in body


def test_model_phase_error_message_reaches_the_existing_progress_hook() -> None:
    """Wall 5: progress/failure surfaced through Write-State/Write-Log only
    -- no new installer lane id, no Rust/React changes required."""
    source = _source()
    assert "function Provision-OllamaRuntime" in source
    assert "function Invoke-OllamaModelPhase" in source

    # No new lane id introduced anywhere in the PS1 (only the pre-existing
    # "runtime" lane is used for the model phase's own state writes).
    ollama_functions_start = source.index("function Provision-OllamaRuntime")
    ollama_functions_end = source.index("\n}\n", source.index("function Invoke-OllamaModelPhase"))
    ollama_region = source[ollama_functions_start:ollama_functions_end]
    assert '"models"' not in ollama_region
    assert 'Write-State "runtime"' in ollama_region


@pytest.mark.skipif(
    shutil.which("bash") is None and not Path(r"C:\Program Files\Git\bin\bash.exe").exists(),
    reason="bash -n needs Git Bash",
)
def test_ollama_script_embedded_bash_parses() -> None:
    completed = subprocess.run(
        [_bash(), "-n"],
        input=_ollama_script(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_healthy_existing_install_is_reused_regardless_of_its_version(
    tmp_path: Path,
) -> None:
    """FALSIFICATION (reviewer-added, wall 2): reuse is decided by HEALTH,
    never by version. A healthy existing install reporting a NEWER version
    (0.31.9) with all selected models present must be reused exactly like a
    0.24.0 one: no install attempted, zero pulls. The 0.24.0 pin governs
    only the absent-install branch. Guards against a future "helpful"
    version check reintroducing the force-install behavior the charter
    banned."""
    venv = _stub_venv(tmp_path)
    fakes = tmp_path / "fakes"
    pull_log = tmp_path / "pulls.log"
    _fake_ollama(
        fakes,
        models=["gemma4:12b", "gemma4:e4b", "translategemma:4b"],
        pull_log=pull_log,
        version="0.31.9",
    )
    completed = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" in completed.stdout
    assert "reusing it without changes" in completed.stdout
    assert not pull_log.exists() or pull_log.read_text(encoding="utf-8").strip() == ""


def test_selection_failure_reports_honestly_never_silently_completes(
    tmp_path: Path,
) -> None:
    """FALSIFICATION (cleanroom-discovered fail-open): when the venv python
    cannot serve the model list, the phase used to fall through with an
    EMPTY selection -- pulling nothing and still printing
    OLLAMA_MODEL_PROVISIONING_COMPLETE. A selection failure must surface an
    honest, actionable error and a non-complete outcome, while the overall
    script still exits 0 (the model phase never blocks the installer --
    charter wall)."""
    venv = _stub_broken_venv(tmp_path)
    fakes = tmp_path / "fakes"
    pull_log = tmp_path / "pulls.log"
    _fake_ollama(fakes, models=["gemma4:12b"], pull_log=pull_log)
    completed = _run_ollama_script(venv=venv, path_dirs=[fakes], cwd=tmp_path)
    assert completed.returncode != 0, "selection failure must not report success"
    assert "OLLAMA_MODEL_PROVISIONING_COMPLETE" not in completed.stdout
    combined = completed.stdout + completed.stderr
    assert "could not determine" in combined.lower() or "retry" in combined.lower(), combined

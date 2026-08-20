# SPDX-License-Identifier: Apache-2.0
"""The ffmpeg-wrapper gate (ADR 0007) must catch real subprocess invocations of
the ffmpeg binary and only those -- not docstrings, wrapper calls, PATH probes,
or reviewed (# noqa: S603) exceptions.

These tests are what keep the gate non-vacuous: a green gate that detects
nothing is worthless, so each real-violation shape is proven to flag.
"""

from __future__ import annotations

from pathlib import Path

from scripts.policy.check_ffmpeg_wrapper import _violations


def _flags(tmp_path: Path, code: str) -> bool:
    sample = tmp_path / "sample.py"
    sample.write_text(code, encoding="utf-8")
    return bool(_violations(sample))


def test_flags_a_direct_ffmpeg_string_invocation(tmp_path: Path) -> None:
    assert _flags(tmp_path, 'import subprocess\nsubprocess.run(["ffmpeg", "-i", "in.mp4"])\n')


def test_flags_the_ffmpeg_executable_constant(tmp_path: Path) -> None:
    code = 'import subprocess\n_FFMPEG_EXECUTABLE = "ffmpeg"\nsubprocess.run([_FFMPEG_EXECUTABLE, "-i"])\n'
    assert _flags(tmp_path, code)


def test_flags_an_ffmpeg_command_built_into_a_variable(tmp_path: Path) -> None:
    # cmd = [_FFMPEG_EXECUTABLE, ...]; subprocess.run(cmd)
    code = 'import subprocess\ncmd = [_FFMPEG_EXECUTABLE, "-i", "x"]\nsubprocess.run(cmd)\n'
    assert _flags(tmp_path, code)


def test_flags_popen_too(tmp_path: Path) -> None:
    assert _flags(tmp_path, 'import subprocess\nsubprocess.Popen(["ffmpeg", "-i"])\n')


def test_honours_a_reviewed_noqa_exception(tmp_path: Path) -> None:
    # The NDI/SDI relays' bring-your-own-binary path is marked this way.
    assert not _flags(
        tmp_path, 'import subprocess\nsubprocess.run(["ffmpeg", "-i"])  # noqa: S603\n'
    )


def test_ignores_docstrings_wrapper_calls_and_path_probes(tmp_path: Path) -> None:
    code = (
        "import shutil\n"
        "import subprocess\n"
        "def _thumb():\n"
        '    """Renders a frame with ffmpeg via subprocess conventions."""\n'
        '    if shutil.which("ffmpeg") is None:\n'
        '        raise RuntimeError("ffmpeg not found on PATH")\n'
        '    return run_ffmpeg(["-i", "x"])\n'
    )
    assert not _flags(tmp_path, code)


def test_ignores_ffprobe_which_is_not_ffmpeg(tmp_path: Path) -> None:
    assert not _flags(tmp_path, 'import subprocess\nsubprocess.run(["ffprobe", "-show_streams"])\n')


# --- bypass vectors an adversarial pass proved slipped through the first cut ---


def test_flags_an_aliased_subprocess_module(tmp_path: Path) -> None:
    assert _flags(tmp_path, 'import subprocess as sp\nsp.run(["ffmpeg", "-i", "x"])\n')


def test_flags_a_directly_imported_run(tmp_path: Path) -> None:
    assert _flags(tmp_path, 'from subprocess import run\nrun(["ffmpeg", "-i", "x"])\n')


def test_flags_a_shell_string_command(tmp_path: Path) -> None:
    # shell=True with a string command is if anything a WORSE ADR-0007 violation.
    assert _flags(
        tmp_path, 'import subprocess\nsubprocess.run("ffmpeg -i in.mp4 out.mp4", shell=True)\n'
    )


def test_flags_os_system_and_os_popen(tmp_path: Path) -> None:
    assert _flags(tmp_path, 'import os\nos.system("ffmpeg -i in.mp4 out.mp4")\n')
    assert _flags(tmp_path, 'import os\nos.popen("ffmpeg -version")\n')


def test_a_filename_containing_ffmpeg_is_not_a_binary_reference(tmp_path: Path) -> None:
    # Only the FIRST token of a command string is the binary; a data filename is not.
    assert not _flags(
        tmp_path, 'import subprocess\nsubprocess.run(["cp", "ffmpeg_out.mp4", "d"])\n'
    )

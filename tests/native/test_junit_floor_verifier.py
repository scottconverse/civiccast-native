# SPDX-License-Identifier: Apache-2.0
"""Sensitivity contracts for the native JUnit execution floor verifier."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_native_junit_floor import passed_native_cases

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_native_junit_floor.py"


def _write_junit(path: Path, body: str) -> None:
    path.write_text(f"<testsuite>{body}</testsuite>", encoding="utf-8")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_passed_native_cases_rejects_missing_native_nodes(tmp_path: Path) -> None:
    junit_path = tmp_path / "missing-native.xml"
    _write_junit(junit_path, '<testcase classname="tests.other" name="test_other" />')

    with pytest.raises(ValueError, match=r"no tests\.native cases"):
        passed_native_cases(junit_path)


def test_passed_native_cases_rejects_skipped_native_nodes(tmp_path: Path) -> None:
    junit_path = tmp_path / "skipped-native.xml"
    _write_junit(
        junit_path,
        '<testcase classname="tests.native.test_runtime" name="test_runtime"><skipped /></testcase>',
    )

    with pytest.raises(ValueError, match="skipped, failed, or errored"):
        passed_native_cases(junit_path)


def test_passed_native_cases_counts_parameters_and_rejects_duplicate_identities(
    tmp_path: Path,
) -> None:
    junit_path = tmp_path / "parametrized-native.xml"
    _write_junit(
        junit_path,
        (
            '<testcase classname="tests.native.test_runtime" name="test_runtime[cpu]" />'
            '<testcase classname="tests.native.test_runtime" name="test_runtime[cuda]" />'
        ),
    )
    duplicate_path = tmp_path / "duplicate-native.xml"
    _write_junit(
        duplicate_path,
        (
            '<testcase classname="tests.native.test_runtime" name="test_runtime[cpu]" />'
            '<testcase classname="tests.native.test_runtime" name="test_runtime[cpu]" />'
        ),
    )
    many_incomplete_path = tmp_path / "many-incomplete-native.xml"
    _write_junit(
        many_incomplete_path,
        "".join(
            (
                '<testcase classname="tests.native.test_runtime" '
                f'name="test_runtime[{index}]"><skipped /></testcase>'
            )
            for index in range(25)
        ),
    )

    assert passed_native_cases(junit_path) == 2
    with pytest.raises(ValueError, match="duplicate"):
        passed_native_cases(duplicate_path)
    with pytest.raises(ValueError) as incomplete:
        passed_native_cases(many_incomplete_path)
    message = str(incomplete.value)
    assert "test_runtime[19]" in message
    assert "test_runtime[20]" not in message
    assert "and 5 more" in message


def test_cli_requires_every_argument() -> None:
    result = _run_cli()

    assert result.returncode == 2
    assert "--junit" in result.stderr
    assert "--floor" in result.stderr
    assert "--label" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("--floor", "1", "--label", "native"),
        ("--junit", "missing.xml", "--label", "native"),
        ("--junit", "missing.xml", "--floor", "1"),
    ],
)
def test_cli_rejects_each_individually_missing_required_argument(args: tuple[str, ...]) -> None:
    result = _run_cli(*args)

    assert result.returncode == 2
    assert "required" in result.stderr


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "no tests.native cases"),
        (
            '<testcase classname="tests.native.test_runtime" name="skipped"><skipped /></testcase>',
            "skipped, failed, or errored",
        ),
        (
            '<testcase classname="tests.native.test_runtime" name="failure"><failure /></testcase>',
            "skipped, failed, or errored",
        ),
        (
            '<testcase classname="tests.native.test_runtime" name="error"><error /></testcase>',
            "skipped, failed, or errored",
        ),
    ],
)
def test_cli_rejects_incomplete_or_non_native_junit(
    tmp_path: Path,
    body: str,
    message: str,
) -> None:
    junit_path = tmp_path / "invalid.xml"
    _write_junit(junit_path, body)

    result = _run_cli("--junit", str(junit_path), "--floor", "1", "--label", "native")

    assert result.returncode == 1
    assert message in result.stdout


def test_cli_rejects_missing_and_malformed_junit(tmp_path: Path) -> None:
    missing = _run_cli(
        "--junit", str(tmp_path / "missing.xml"), "--floor", "1", "--label", "native"
    )
    malformed_path = tmp_path / "malformed.xml"
    malformed_path.write_text("<testsuite>", encoding="utf-8")
    malformed = _run_cli("--junit", str(malformed_path), "--floor", "1", "--label", "native")

    assert missing.returncode == 1
    assert "JUnit file is missing" in missing.stdout
    assert malformed.returncode == 1
    assert "execution is unproven" in malformed.stdout


def test_cli_rejects_below_floor_and_returns_zero_only_on_pass(tmp_path: Path) -> None:
    junit_path = tmp_path / "passed.xml"
    _write_junit(
        junit_path,
        '<testcase classname="tests.native.test_runtime" name="test_runtime" />',
    )

    below_floor = _run_cli("--junit", str(junit_path), "--floor", "2", "--label", "native")
    exact_floor = _run_cli("--junit", str(junit_path), "--floor", "1", "--label", "native")
    zero_floor = _run_cli("--junit", str(junit_path), "--floor", "0", "--label", "native")
    negative_floor = _run_cli("--junit", str(junit_path), "--floor", "-1", "--label", "native")

    assert below_floor.returncode == 1
    assert "pass count 1 < floor 2" in below_floor.stdout
    assert exact_floor.returncode == 0
    for invalid in (zero_floor, negative_floor):
        assert invalid.returncode == 2
        assert "--floor must be positive" in invalid.stderr

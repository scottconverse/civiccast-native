# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Security receipts and dated exceptions must fail closed."""

from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def checker(tmp_path: Path):
    path = Path(__file__).resolve().parents[2] / "scripts/check_pip_audit_allowlist.py"
    spec = importlib.util.spec_from_file_location("audit_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ALLOWLIST_PATH = tmp_path / "allowed.json"
    module.ALLOWLIST_PATH.write_text('{"allowed": []}', encoding="utf-8")
    return module


def run_report(checker, tmp_path: Path, data: object) -> int:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    expected = tmp_path / "inventory.json"
    expected.write_text('[{"name":"pkg","version":"1"}]', encoding="utf-8")
    findings = (
        isinstance(data, dict)
        and isinstance(data.get("dependencies"), list)
        and any(isinstance(row, dict) and row.get("vulns") for row in data["dependencies"])
    )
    return checker.main(
        [
            "checker",
            str(path),
            "--inventory",
            str(expected),
            "--scanner-exit-code",
            "1" if findings else "0",
        ]
    )


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        None,
        {"dependencies": []},
        {"dependencies": {}},
        {"dependencies": [None]},
        {"dependencies": [{"name": "pkg", "version": "1"}]},
        {"dependencies": [{"name": "pkg", "version": "1", "vulns": None}]},
        {"dependencies": [{"name": "", "version": "1", "vulns": []}]},
        {"dependencies": [{"name": "pkg", "version": "", "vulns": []}]},
        {"dependencies": [{"name": "pkg", "version": "1", "vulns": [{}]}]},
        {
            "dependencies": [
                {"name": "pkg", "version": "1", "vulns": [], "skip_reason": "unavailable"}
            ]
        },
    ],
)
def test_malformed_or_incomplete_audit_fails(checker, tmp_path, data):
    assert run_report(checker, tmp_path, data) == 2


def test_clean_nonempty_audit_passes(checker, tmp_path):
    assert (
        run_report(
            checker, tmp_path, {"dependencies": [{"name": "pkg", "version": "1", "vulns": []}]}
        )
        == 0
    )


def exception_entry():
    return {
        "package": "pkg",
        "id": "TEST-1",
        "reviewed": date.today().isoformat(),
        "review_by": (date.today() + timedelta(days=7)).isoformat(),
        "reason": "Verified unreachable caller path; upstream fix not available.",
    }


@pytest.mark.parametrize(
    "change", ["expired", "future", "missing_deadline", "missing_reason", "bad_date"]
)
def test_invalid_exception_fails(checker, tmp_path, change):
    entry = exception_entry()
    if change == "expired":
        entry["reviewed"] = (date.today() - timedelta(days=10)).isoformat()
        entry["review_by"] = (date.today() - timedelta(days=1)).isoformat()
    elif change == "future":
        entry["reviewed"] = (date.today() + timedelta(days=1)).isoformat()
    elif change == "missing_deadline":
        del entry["review_by"]
    elif change == "missing_reason":
        entry["reason"] = ""
    else:
        entry["reviewed"] = "not-a-date"
    checker.ALLOWLIST_PATH.write_text(json.dumps({"allowed": [entry]}), encoding="utf-8")
    assert (
        run_report(
            checker,
            tmp_path,
            {"dependencies": [{"name": "pkg", "version": "1", "vulns": [{"id": "TEST-1"}]}]},
        )
        == 2
    )


def test_current_exception_only_matches_exact_pair(checker, tmp_path):
    checker.ALLOWLIST_PATH.write_text(
        json.dumps({"allowed": [exception_entry()]}), encoding="utf-8"
    )
    report = {"dependencies": [{"name": "pkg", "version": "1", "vulns": [{"id": "TEST-1"}]}]}
    assert run_report(checker, tmp_path, report) == 0
    report["dependencies"][0]["vulns"][0]["id"] = "TEST-2"
    assert run_report(checker, tmp_path, report) == 1


def test_invalid_json_fails(checker, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    expected = tmp_path / "inventory.json"
    expected.write_text('[{"name":"pkg","version":"1"}]', encoding="utf-8")
    assert (
        checker.main(
            ["checker", str(path), "--inventory", str(expected), "--scanner-exit-code", "0"]
        )
        == 2
    )


def test_structurally_valid_partial_receipt_without_independent_inventory_fails(checker, tmp_path):
    # Exact shape of the independently captured one-of-194 false PASS.
    path = tmp_path / "partial.json"
    path.write_text(
        '{"dependencies":[{"name":"aiofiles","version":"25.1.0","vulns":[]}]}', encoding="utf-8"
    )
    assert checker.main(["checker", str(path)]) == 2


def run_bound(checker, tmp_path, dependencies, inventory, scanner_exit=0):
    report = tmp_path / "bound-report.json"
    expected = tmp_path / "independent-pip-list.json"
    report.write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")
    expected.write_text(json.dumps(inventory), encoding="utf-8")
    return checker.main(
        [
            "checker",
            str(report),
            "--inventory",
            str(expected),
            "--scanner-exit-code",
            str(scanner_exit),
        ]
    )


@pytest.mark.parametrize("change", ["omit", "substitute", "duplicate", "wrong-version"])
def test_bound_inventory_rejects_graph_changes(checker, tmp_path, change):
    inventory = [{"name": "pkg", "version": "1"}, {"name": "other", "version": "2"}]
    dependencies = [dict(row, vulns=[]) for row in inventory]
    if change == "omit":
        dependencies.pop()
    if change == "substitute":
        dependencies[1]["name"] = "replacement"
    if change == "duplicate":
        dependencies.append(dict(dependencies[0]))
    if change == "wrong-version":
        dependencies[1]["version"] = "3"
    assert run_bound(checker, tmp_path, dependencies, inventory) == 2


def test_complete_independently_bound_inventory_passes(checker, tmp_path):
    assert (
        run_bound(
            checker,
            tmp_path,
            [{"name": "Some_Pkg", "version": "1.0", "vulns": []}],
            [{"name": "some-pkg", "version": "1.0"}],
        )
        == 0
    )


@pytest.mark.parametrize("exit_code", [1, 2, 127])
def test_scanner_error_cannot_be_clean_receipt(checker, tmp_path, exit_code):
    assert (
        run_bound(
            checker,
            tmp_path,
            [{"name": "pkg", "version": "1", "vulns": []}],
            [{"name": "pkg", "version": "1"}],
            exit_code,
        )
        == 2
    )


@pytest.mark.parametrize(
    "inventory",
    [
        [],
        {},
        [{"name": "pkg", "version": "1"}, {"name": "PKG", "version": "1"}],
        [{"name": "pkg", "version": "not-version"}],
    ],
)
def test_invalid_independent_inventory_fails(checker, tmp_path, inventory):
    assert (
        run_bound(checker, tmp_path, [{"name": "pkg", "version": "1", "vulns": []}], inventory) == 2
    )


@pytest.mark.parametrize(
    "pin",
    [
        "pkg==1; sys_platform == 'win32'",
        "pkg>=1",
        "pkg==1.*",
        "-r other.txt",
        "pkg @ https://example.invalid/pkg.whl",
        "pkg[extra]==1",
    ],
)
def test_native_inventory_refuses_universal_or_unresolved_input(checker, tmp_path, pin):
    report = tmp_path / "report.json"
    report.write_text('{"dependencies":[{"name":"pkg","version":"1","vulns":[]}]}')
    requirements = tmp_path / "native.txt"
    requirements.write_text(pin)
    assert (
        checker.main(
            [
                "checker",
                str(report),
                "--requirements",
                str(requirements),
                "--scanner-exit-code",
                "0",
            ]
        )
        == 2
    )


def test_native_exact_pin_graph_is_independent_of_installed_environment(checker, tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"dependencies":[{"name":"native-only","version":"18.0.0","vulns":[]}]}')
    requirements = tmp_path / "native.txt"
    requirements.write_text("native-only==18.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n")
    assert (
        checker.main(
            [
                "checker",
                str(report),
                "--requirements",
                str(requirements),
                "--scanner-exit-code",
                "0",
            ]
        )
        == 0
    )


def test_dated_findings_accept_exit_one_only(checker, tmp_path):
    checker.ALLOWLIST_PATH.write_text(json.dumps({"allowed": [exception_entry()]}))
    dependencies = [{"name": "pkg", "version": "1", "vulns": [{"id": "TEST-1"}]}]
    inventory = [{"name": "pkg", "version": "1"}]
    assert run_bound(checker, tmp_path, dependencies, inventory, 1) == 0
    assert run_bound(checker, tmp_path, dependencies, inventory, 0) == 2

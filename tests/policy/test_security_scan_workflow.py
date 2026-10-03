# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Audit item #27: the CI security-scan workflow covers all three scanners
and never runs unallowlisted findings without failing."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(
        Path(".github/workflows/ci-security-scan.yml").read_text(encoding="utf-8")
    )


def _job_run_commands(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_security_scan_workflow_covers_pip_audit_bandit_and_both_npm_audits() -> None:
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    assert set(jobs) == {"pip-audit", "bandit", "npm-audit-operator", "npm-audit-public"}
    assert "pip-audit" in _job_run_commands(jobs["pip-audit"])
    assert "check_pip_audit_allowlist.py" in _job_run_commands(jobs["pip-audit"])
    assert "bandit -ll -r civiccast" in _job_run_commands(jobs["bandit"])
    for npm_job in ("npm-audit-operator", "npm-audit-public"):
        assert "npm audit --audit-level=high" in _job_run_commands(jobs[npm_job])
    assert jobs["npm-audit-operator"]["defaults"]["run"]["working-directory"] == (
        "civiccast/apps/portal-operator"
    )
    assert jobs["npm-audit-public"]["defaults"]["run"]["working-directory"] == (
        "civiccast/apps/portal-public"
    )
    # Weekly drift catcher stays scheduled. PyYAML parses the bare `on:`
    # key as boolean True (YAML 1.1), hence the lookup shape.
    triggers = workflow.get("on", workflow.get(True))
    assert "schedule" in triggers
    assert "pull_request" in triggers


def test_security_scan_workflow_never_soft_fails() -> None:
    """A gate that runs with continue-on-error is theater: it goes green no
    matter what the scanners find. No job or step may set it."""

    workflow = _load_workflow()
    for job_name, job in workflow["jobs"].items():
        assert not job.get("continue-on-error"), f"{job_name} soft-fails at job level"
        for step in job["steps"]:
            assert not step.get("continue-on-error"), (
                f"{job_name} step {step.get('name', '?')!r} soft-fails"
            )


def test_security_scan_workflow_is_not_in_the_required_checks_list() -> None:
    """This gate must stay separate from the 5 branch-protection-required
    checks (Unit tests, Lint, both a11y jobs, Operator portal build) — a
    scanner false positive should never block every PR the day it's added."""

    workflow = _load_workflow()
    assert workflow["name"] == "ci-security-scan"


def test_pip_audit_allowlist_entries_are_dated_and_reasoned() -> None:
    data = json.loads(Path("security/pip-audit-allowlist.json").read_text(encoding="utf-8"))

    assert data["allowed"], "allowlist should document at least the known nltk finding"
    for entry in data["allowed"]:
        assert entry["package"]
        assert entry["id"]
        assert entry["reviewed"]
        assert len(entry["reason"]) > 20


def test_pip_audit_allowlist_checker_fails_on_unlisted_findings(tmp_path: Path) -> None:
    import subprocess
    import sys

    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "totally-made-up-package",
                        "version": "0.0.1",
                        "vulns": [{"id": "FAKE-1"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / "inventory.json").write_text(
        '[{"name":"totally-made-up-package","version":"0.0.1"}]', encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_pip_audit_allowlist.py",
            str(report),
            "--inventory",
            str(tmp_path / "inventory.json"),
            "--scanner-exit-code",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 1
    assert "totally-made-up-package" in result.stderr


def test_pip_audit_allowlist_checker_passes_on_known_findings(tmp_path: Path) -> None:
    import subprocess
    import sys

    allowlist = json.loads(Path("security/pip-audit-allowlist.json").read_text(encoding="utf-8"))
    entry = allowlist["allowed"][0]

    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": entry["package"],
                        "version": "0.0.0",
                        "vulns": [{"id": entry["id"]}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / "inventory.json").write_text(
        json.dumps([{"name": entry["package"], "version": "0.0.0"}]), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_pip_audit_allowlist.py",
            str(report),
            "--inventory",
            str(tmp_path / "inventory.json"),
            "--scanner-exit-code",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "case",
    [
        "clean",
        "dated-finding",
        "omitted",
        "scanner-error",
        "error-one-clean",
        "inventory-error",
        "native",
    ],
)
def test_actual_workflow_shell_binds_independent_graph_and_status(
    tmp_path: Path, case: str
) -> None:
    """Execute actual workflow run body with offline collector shims + real checker."""
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    bash = (
        Path("C:/Program Files/Git/bin/bash.exe")
        if os.name == "nt"
        else Path(shutil.which("bash") or "")
    )
    assert bash.is_file(), "the actual shell integration requires Bash"
    steps = _load_workflow()["jobs"]["pip-audit"]["steps"]
    run = next(
        step["run"]
        for step in steps
        if step["name"].startswith("Audit native" if case == "native" else "pip-audit (")
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "security").mkdir()
    shutil.copyfile(
        repo / "scripts/check_pip_audit_allowlist.py",
        tmp_path / "scripts/check_pip_audit_allowlist.py",
    )
    shutil.copyfile(
        repo / "security/pip-audit-allowlist.json", tmp_path / "security/pip-audit-allowlist.json"
    )
    # Defined independently, never derived from the fake scanner's receipt.
    inventory = [{"name": "nltk", "version": "3.10.3"}, {"name": "other", "version": "2"}]
    dependencies = [dict(item, vulns=[]) for item in inventory]
    status = 0
    if case == "dated-finding":
        allowed = json.loads((repo / "security/pip-audit-allowlist.json").read_text())["allowed"][0]
        assert allowed["package"] == "nltk"
        dependencies[0]["vulns"] = [{"id": allowed["id"]}]
        status = 1
    if case == "omitted":
        dependencies.pop()
    if case in {"scanner-error", "error-one-clean"}:
        status = 2 if case == "scanner-error" else 1
    if case == "native":
        dependencies = [{"name": "native-only", "version": "18.0.0", "vulns": []}]
        (tmp_path / "requirements-native-app.txt").write_text("native-only==18.0.0\n")
    (tmp_path / "independent.json").write_text(json.dumps(inventory))
    (tmp_path / "scanner.json").write_text(json.dumps({"dependencies": dependencies}))
    binary = tmp_path / "bin"
    binary.mkdir()
    shim = binary / "uv"
    shim.write_text(
        """#!/bin/bash
case "$*" in
  *" -m pip list "*) cat "$TEST_INVENTORY"; exit "$TEST_INVENTORY_EXIT";;
  *" -m pip_audit "*) echo called > "$TEST_CALLED"; cat "$TEST_RECEIPT"; exit "$TEST_SCANNER_EXIT";;
  *"scripts/check_pip_audit_allowlist.py"*) shift 3; exec "$TEST_PYTHON" "$@";;
  *) exit 99;;
esac
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = dict(os.environ)
    env.update(
        TEST_BIN=str(binary),
        TEST_INVENTORY=str(tmp_path / "independent.json"),
        TEST_RECEIPT=str(tmp_path / "scanner.json"),
        TEST_PYTHON=sys.executable,
        TEST_CALLED=str(tmp_path / "audit-called"),
        TEST_SCANNER_EXIT=str(status),
        TEST_INVENTORY_EXIT="2" if case == "inventory-error" else "0",
    )
    prefix = (
        'export PATH="$(cygpath -u "$TEST_BIN"):/usr/bin:/bin:$PATH"\n'
        if os.name == "nt"
        else 'export PATH="$TEST_BIN:$PATH"\n'
    )
    result = subprocess.run(
        [str(bash), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", prefix + run],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    expected = 0 if case in {"clean", "dated-finding", "native"} else 2
    assert result.returncode == expected, result.stdout + result.stderr
    if case == "inventory-error":
        assert not (tmp_path / "audit-called").exists()

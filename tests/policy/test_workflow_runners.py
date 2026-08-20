# SPDX-License-Identifier: Apache-2.0
"""Runner policy tests.

Scott's directive (2026-06-12, repo public): GitHub-hosted runners
everywhere; self-hosted labels only for the explicit hardware/duration
allowlist (GPU proofs, the local Hyper-V cleanroom, the >6h soak).
"""

from pathlib import Path

from scripts.policy.check_workflow_runners import (
    SELF_HOSTED_ALLOWLIST,
    check_workflow_runners,
    validate_workflow,
)


def test_existing_repo_workflows_use_allowed_runner_labels() -> None:
    assert check_workflow_runners() == []


def test_hosted_runner_labels_pass(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "good.yml"
    workflow.parent.mkdir(parents=True)
    for label in ("ubuntu-latest", "windows-latest", "macos-latest", "ubuntu-24.04"):
        workflow.write_text(
            f"""
name: good
jobs:
  test:
    runs-on: {label}
    steps: []
""",
            encoding="utf-8",
        )
        assert validate_workflow(workflow, workflow.read_text(encoding="utf-8")) == []


def test_self_hosted_fails_with_directive_message(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "bad.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        """
name: bad
jobs:
  test:
    runs-on: [self-hosted, linux, x64, scott-desktop]
    steps: []
""",
        encoding="utf-8",
    )

    violations = validate_workflow(workflow, workflow.read_text(encoding="utf-8"))

    assert violations
    assert "self-hosted" in violations[0]
    assert "hosted-runners directive" in violations[0]
    assert "ubuntu-latest" in violations[0]


def test_allowlisted_hardware_lanes_may_stay_self_hosted(tmp_path: Path) -> None:
    parent = tmp_path / ".github" / "workflows"
    parent.mkdir(parents=True)
    text = """
name: gpu
jobs:
  proof:
    runs-on: [self-hosted, Linux, X64, scott-desktop, rtx5070, ubuntu-2404]
    steps: []
"""
    for name in SELF_HOSTED_ALLOWLIST:
        allowed = parent / name
        assert validate_workflow(allowed, text) == [], name

    ordinary = parent / "ordinary.yml"
    violations = validate_workflow(ordinary, text)
    assert violations
    assert "self-hosted" in violations[0]


def test_every_allowlist_entry_carries_a_reason() -> None:
    # The allowlist is an exception ledger, not a loophole: each entry must
    # say WHY hosted runners cannot serve it.
    for name, reason in SELF_HOSTED_ALLOWLIST.items():
        assert name.endswith(".yml")
        assert reason.strip(), name


def test_matrix_runner_expressions_are_flagged(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "matrix.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        """
name: matrix
jobs:
  test:
    runs-on: ${{ matrix.os }}
    steps: []
""",
        encoding="utf-8",
    )

    violations = validate_workflow(workflow, workflow.read_text(encoding="utf-8"))

    assert violations
    assert "matrix runner target" in violations[0]


def test_native_beta_hosted_selector_is_allowed_only_for_installer_workflow(
    tmp_path: Path,
) -> None:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    text = """
name: installer
jobs:
  frontend:
    runs-on: ${{ inputs.native_beta_windows_only && 'windows-latest' || 'ubuntu-latest' }}
    steps: []
"""

    installer = workflow_dir / "ci-installer-compile.yml"
    assert validate_workflow(installer, text) == []

    ordinary = workflow_dir / "ordinary.yml"
    violations = validate_workflow(ordinary, text)
    assert violations
    assert "matrix runner target" in violations[0]

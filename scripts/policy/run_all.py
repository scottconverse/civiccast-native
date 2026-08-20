#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run every policy check and produce a combined PROMOTE/BLOCK report.

Wired into ``.pipelines/feature.yaml`` and ``.pipelines/bugfix.yaml`` as
the ``policy`` stage. The manager role uses this report to decide
PROMOTE / BLOCK / REPLAN.

Exit code: 0 only if every check passes. 1 if any check fails. The final
report line is one of:
  POLICY: ALL CHECKS PASSED
  POLICY: <N> CHECK(S) FAILED

To add project-specific policy checks, drop them in this directory next
to the generic ones and add them to the CHECKS list below.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = find_repo_root(__file__)

# Order matters only for human readability of the combined report.
# Add project-specific checks here (e.g., a custom check_module_boundaries.py).
CHECKS: list[tuple[str, list[str]]] = [
    ("check_manifest_schema", ["check_manifest_schema.py"]),
    ("check_scope_lock", ["check_scope_lock.py"]),
    ("check_allowed_paths", ["check_allowed_paths.py"]),
    ("check_execute_readiness", ["check_execute_readiness.py"]),
    ("check_git_identity", ["check_git_identity.py"]),
    ("check_release_identity", ["check_release_identity.py"]),
    ("check_release_candidate_boundary", ["check_release_candidate_boundary.py"]),
    (
        "check_no_contradictory_release_banners",
        ["check_no_contradictory_release_banners.py"],
    ),
    ("check_rung_file_ownership", ["check_rung_file_ownership.py"]),
    ("check_release_docs_consistency", ["check_release_docs_consistency.py"]),
    ("check_public_copy_legal", ["check_public_copy_legal.py"]),
    ("check_claims_retraction", ["check_claims_retraction.py"]),
    ("check_v14_release_evidence", ["check_v14_release_evidence.py"]),
    ("check_v15_resilience_gate", ["check_v15_resilience_gate.py"]),
    ("check_v17_adoption_gate", ["check_v17_adoption_gate.py"]),
    ("check_actions_budget", ["check_actions_budget.py"]),
    ("check_workflow_runners", ["check_workflow_runners.py"]),
    ("check_operator_copy", ["check_operator_copy.py"]),
    ("check_beta_handoff_docs", ["check_beta_handoff_docs.py"]),
    ("check_release_artifacts", ["check_release_artifacts.py"]),
    ("check_sidecar_attestation_integrity", ["check_sidecar_attestation_integrity.py"]),
    ("check_ffmpeg_wrapper", ["check_ffmpeg_wrapper.py"]),
    ("check_no_todos", ["check_no_todos.py"]),
    ("check_adr_gate", ["check_adr_gate.py"]),
]


def _run(check_name: str, script_args: list[str], extra_args: list[str]) -> tuple[bool, str]:
    cmd = [sys.executable, str(THIS_DIR / script_args[0]), *script_args[1:], *extra_args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.rstrip()


def _write_scope_receipt(run_id: str, results: list[tuple[str, bool, str]]) -> None:
    scope_checks = {
        "check_scope_lock",
        "check_rung_file_ownership",
        "check_release_docs_consistency",
    }
    status = {name: passed for name, passed, _ in results if name in scope_checks}
    if set(status) != scope_checks or not all(status.values()):
        return

    receipt = REPO_ROOT / ".agent-runs" / run_id / "scope-lock-receipt.txt"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    scope_output = next(output for name, _, output in results if name == "check_scope_lock")
    canonical = "unknown"
    if "canonical_rung:" in scope_output:
        canonical = scope_output.split("canonical_rung:", 1)[1].strip()
    receipt.write_text(
        "\n".join(
            [
                "scope_lock: PASS",
                f"canonical_rung: {canonical}",
                "edited_paths_match_rung: PASS",
                "docs_consistency: PASS",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        help="Pipeline run id, passed through to checks that consume the manifest.",
    )
    args = parser.parse_args()

    extra_for_run_consumers = ["--run", args.run] if args.run else []
    # Checks that consume the run id or need pipeline-mode enforcement.
    run_consumers = {
        "check_allowed_paths",
        "check_manifest_schema",
        "check_scope_lock",
        "check_rung_file_ownership",
        "check_release_docs_consistency",
        "check_actions_budget",
        "check_execute_readiness",
    }

    results: list[tuple[str, bool, str]] = []
    for name, script_args in CHECKS:
        extra = extra_for_run_consumers if name in run_consumers else []
        passed, output = _run(name, script_args, extra)
        results.append((name, passed, output))

    print("=" * 64)
    print("Policy checks")
    print("=" * 64)
    for name, passed, output in results:
        status = "PASS" if passed else "FAIL"
        print(f"\n[{status}] {name}")
        if output:
            for line in output.splitlines():
                print(f"  {line}")

    failed = [name for name, passed, _ in results if not passed]
    print()
    print("-" * 64)
    if failed:
        print(f"POLICY: {len(failed)} CHECK(S) FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1

    if args.run:
        _write_scope_receipt(args.run, results)

    print("POLICY: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

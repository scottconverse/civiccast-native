# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CI must prove the real-Postgres staff-auth boundary actually executes."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-test.yml"
AUTH_TESTS = REPO_ROOT / "tests" / "auth" / "test_staff_token_lifecycle.py"


def test_ci_junit_floor_covers_real_postgres_staff_auth() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert 'cls.startswith("tests.auth.test_staff_token_lifecycle")' in workflow
    assert "Real-Postgres staff-auth tests passed:" in workflow
    assert "Real-Postgres staff-auth pass count" in workflow

    block = workflow.split("- name: Assert real-Postgres staff-auth tests actually ran", 1)[1]
    selected = set(re.findall(r'name == "(test_[^"]+)"', block))
    assert selected == {
        "test_postgres_audit_order_is_deterministic_under_collisions",
        "test_real_postgres_valid_token_survives_shared_ip_failure_budget",
    }
    floor_match = re.search(r"floor = (\d+)", block)
    assert floor_match is not None
    floor = int(floor_match.group(1))
    assert floor == len(selected)

    tree = ast.parse(AUTH_TESTS.read_text(encoding="utf-8"))
    collected_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert selected <= collected_names

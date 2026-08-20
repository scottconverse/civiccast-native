# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from scripts.policy.check_v15_resilience_gate import (
    REQUIRED_PATHS,
    REQUIRED_UPDATE_FIELDS,
    evaluate_v15_resilience_gate,
)


def _write_openapi(root: Path, *, include_rollback_schema: bool = True) -> None:
    schemas = {
        "UpdateRollbackStatus": {
            "properties": {field: {"type": "string"} for field in REQUIRED_UPDATE_FIELDS}
        }
    }
    if include_rollback_schema:
        schemas["RollbackArtifactRequest"] = {"properties": {"artifact_path": {"type": "string"}}}
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "openapi.json").write_text(
        json.dumps(
            {
                "paths": {path: {} for path in REQUIRED_PATHS},
                "components": {"schemas": schemas},
            }
        ),
        encoding="utf-8",
    )


def test_v15_resilience_gate_passes_current_repo() -> None:
    root = Path(__file__).resolve().parents[2]

    assert evaluate_v15_resilience_gate(root) == []


def test_v15_resilience_gate_requires_rollback_contract(tmp_path: Path) -> None:
    _write_openapi(tmp_path, include_rollback_schema=False)

    violations = evaluate_v15_resilience_gate(tmp_path)

    assert any("RollbackArtifactRequest" in violation for violation in violations)


def test_v15_resilience_gate_scans_json_proof_secrets(tmp_path: Path) -> None:
    _write_openapi(tmp_path)
    proof_dir = tmp_path / "docs" / "releases" / "evidence"
    proof_dir.mkdir(parents=True)
    (proof_dir / "support.json").write_text(
        json.dumps({"environment": {"API_TOKEN": {"value": "ccst_leaked_secret"}}}),
        encoding="utf-8",
    )

    violations = evaluate_v15_resilience_gate(tmp_path)

    assert any("API_TOKEN" in violation for violation in violations)

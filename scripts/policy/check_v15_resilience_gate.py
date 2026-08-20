#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: v1.5 resilience surfaces and proof artifacts stay fail-closed."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)
OPENAPI_PATH = Path("docs/openapi.json")
REQUIRED_PATHS = {
    "/api/staff/installer/restore",
    "/api/staff/installer/restore/rehearsal",
    "/api/staff/installer/update-rollback",
    "/api/staff/installer/update-rollback/preflight",
    "/api/staff/installer/update-rollback/maintenance-window",
    "/api/staff/installer/update-rollback/rollback-artifact",
    "/api/staff/installer/update-rollback/rollback-rehearsal",
    "/api/staff/installer/update-rollback/failed-update-rehearsal",
    "/api/staff/installer/update-rollback/post-update-proof",
    "/api/staff/installer/provider-proof",
    "/api/staff/installer/support-bundle",
}
REQUIRED_UPDATE_FIELDS = {
    "safe_to_apply",
    "last_preflight_at",
    "checkpoint_summary",
    "rollback_artifact_sha256",
    "rollback_proof_state",
    "last_rollback_test_at",
    "rollback_proof_summary",
    "post_update_proof_state",
    "last_post_update_proof_at",
    "post_update_proof_summary",
    "maintenance_window_state",
    "maintenance_window_expires_at",
    "maintenance_window_summary",
    "failed_update_rollback_state",
    "last_failed_update_rollback_at",
    "failed_update_rollback_summary",
}
PROOF_SCAN_GLOBS = (
    "docs/releases/evidence/**/*.json",
    "tester-handoff/v1.5/**/*.json",
)
SECRET_KEY_MARKERS = ("secret", "token", "password", "private_key", "private-key", "credential")
REDACTED_VALUES = {"", "[redacted]", "redacted", "excluded", "not included", "none", "null"}
RAW_SECRET_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)?PRIVATE KEY-----|"
    r"\b(?:token|password|secret|private_key)=([^\s&\"']{8,})",
    re.IGNORECASE,
)


def evaluate_v15_resilience_gate(root: Path) -> list[str]:
    """Return v1.5 resilience-gate violations."""

    root = root.resolve()
    violations: list[str] = []
    openapi_path = root / OPENAPI_PATH
    if not openapi_path.exists():
        return [f"{OPENAPI_PATH.as_posix()}: missing generated OpenAPI contract."]

    try:
        openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{OPENAPI_PATH.as_posix()}: invalid JSON: {exc}"]

    paths = set(openapi.get("paths", {}))
    missing_paths = sorted(REQUIRED_PATHS - paths)
    for path in missing_paths:
        violations.append(f"{OPENAPI_PATH.as_posix()}: missing v1.5 resilience path {path}.")

    schemas = openapi.get("components", {}).get("schemas", {})
    update_properties = schemas.get("UpdateRollbackStatus", {}).get("properties", {})
    missing_fields = sorted(REQUIRED_UPDATE_FIELDS - set(update_properties))
    for field in missing_fields:
        violations.append(
            f"{OPENAPI_PATH.as_posix()}: UpdateRollbackStatus missing field {field!r}."
        )
    if "RollbackArtifactRequest" not in schemas:
        violations.append(f"{OPENAPI_PATH.as_posix()}: missing RollbackArtifactRequest schema.")

    violations.extend(_scan_committed_json_proof_secrets(root))
    return violations


def _scan_committed_json_proof_secrets(root: Path) -> list[str]:
    violations: list[str] = []
    for proof_path in _iter_proof_json_files(root):
        relative = proof_path.relative_to(root).as_posix()
        text = proof_path.read_text(encoding="utf-8", errors="ignore")
        if RAW_SECRET_PATTERN.search(text):
            violations.append(f"{relative}: contains a raw secret-looking token or private key.")
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            violations.append(f"{relative}: proof JSON is invalid: {exc}")
            continue
        for pointer, key, value in _iter_secret_like_values(payload):
            if _redacted(value):
                continue
            violations.append(
                f"{relative}:{pointer}: secret-like key {key!r} has an unredacted value."
            )
    return violations


def _iter_proof_json_files(root: Path) -> Iterator[Path]:
    for pattern in PROOF_SCAN_GLOBS:
        yield from (path for path in root.glob(pattern) if path.is_file())


def _iter_secret_like_values(payload: Any, pointer: str = "$") -> Iterator[tuple[str, str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            child_pointer = f"{pointer}.{key_text}"
            if any(marker in key_text.lower() for marker in SECRET_KEY_MARKERS):
                yield child_pointer, key_text, value
            yield from _iter_secret_like_values(value, child_pointer)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from _iter_secret_like_values(item, f"{pointer}[{index}]")


def _redacted(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value.strip().lower() in REDACTED_VALUES
    if isinstance(value, list):
        return all(_redacted(item) for item in value)
    if isinstance(value, dict):
        return all(_redacted(item) for item in value.values())
    return False


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else REPO_ROOT
    violations = evaluate_v15_resilience_gate(root)
    if violations:
        print("V1.5 RESILIENCE GATE: FAIL")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("V1.5 RESILIENCE GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

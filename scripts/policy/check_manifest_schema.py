#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: the run manifest must satisfy a strict schema.

Fuzzy manifests are the largest single source of agent drift. This check
enforces structural minimums on the manifest so the downstream stages
(researcher, planner, executor, verifier, critic, drift-detector,
auto-promote) have a contract worth enforcing.

Rules enforced:
  - `goal` is a non-empty quoted string of >= MIN_GOAL_CHARS characters.
  - `expected_outputs` has >= 1 entry; each entry is non-empty.
  - `definition_of_done` is a non-empty quoted string of
    >= MIN_DOD_CHARS characters.
  - `non_goals` has >= 1 entry; each entry is non-empty.
  - `rollback_plan` is a non-empty quoted string.
  - When `allowed_paths` contains a "broad" prefix (a top-level
    directory like "src/" with no further specificity),
    `forbidden_paths` must be non-empty. Belt-and-suspenders for
    runs whose scope is wide.
  - `goal` and `definition_of_done` must NOT contain forbidden status
    words (`done`, `complete`, `ready`, `shippable`, `taggable`,
    case-insensitive). These words are forbidden in manifest contracts
    because they import the project's ambient release-gate semantics
    into a run that is not itself a release gate.

If invoked without --run, prints usage and exits 0 (no-op outside a
pipeline run). When run via `auto_promote.py` or `run_all.py` with a
--run argument, all rules are enforced.

The fix from PR #7 (resolve REPO_ROOT for both source and installed
layouts) is applied here as well.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root, strip_yaml_comment
except ModuleNotFoundError:  # pragma: no cover - source-tree test import
    from scripts.policy_utils import find_repo_root, strip_yaml_comment

FORBIDDEN_STATUS_WORDS = {"done", "complete", "ready", "shippable", "taggable"}
MIN_GOAL_CHARS = 30
MIN_DOD_CHARS = 80
BROAD_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*/$")


REPO_ROOT = find_repo_root(__file__)
RUN_DIR = REPO_ROOT / ".agent-runs"


def _read_manifest(manifest_path: Path) -> dict[str, object]:
    """Parse the manifest into a flat dict.

    Stdlib-only minimal YAML parser, matching the conventions used by
    check_allowed_paths.py. Supports:
      - top-level `pipeline_run:` block
      - scalar values: `key: "string"` or `key: bareword`
      - list values: `key:` followed by `  - "item"` lines
      - inline empty lists: `key: []`
      - comments after whitespace + `#`

    Returns a dict keyed by manifest field. List values are list[str].
    Scalar values are str.
    """
    if not manifest_path.exists():
        print(
            f"check_manifest_schema: FAIL - manifest not found at {manifest_path}", file=sys.stderr
        )
        sys.exit(1)

    text = manifest_path.read_text(encoding="utf-8")
    fields: dict[str, object] = {}
    current_list_key: str | None = None

    for raw in text.splitlines():
        line = strip_yaml_comment(raw.rstrip())
        if not line:
            continue
        stripped = line.strip()

        # Reset list-accumulation when we hit a new top-level / nested key.
        if stripped.startswith("- ") and current_list_key is not None:
            value = stripped[2:].strip().strip("\"'")
            existing = fields.setdefault(current_list_key, [])
            if not isinstance(existing, list):
                fields[current_list_key] = []
                existing = fields[current_list_key]
            existing.append(value)
            continue

        # Any non-list line ends list accumulation.
        current_list_key = None

        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()

        if key in ("pipeline_run",):
            # Top-level block marker; no value.
            continue

        if value == "[]":
            fields[key] = []
            continue
        if value == "":
            current_list_key = key
            fields.setdefault(key, [])
            continue

        # Scalar
        scalar = value.strip("\"'")
        fields[key] = scalar

    return fields


def _is_broad_prefix(prefix: str) -> bool:
    """True if `prefix` is a top-level directory with no further specificity.

    Examples that match:
      - `src/`, `lib/`, `civiccast/`, `app/`

    Examples that do not match:
      - `src/auth/`, `civiccast/stream/`, `civicrecords-ai/civicrecords_ai/`

    A broad prefix authorizes large blast radius; the schema requires
    `forbidden_paths` to be populated in that case.
    """
    normalized = prefix.strip()
    if not normalized.endswith("/"):
        normalized = normalized + "/"
    return bool(BROAD_PREFIX_PATTERN.fullmatch(normalized))


def _check(fields: dict[str, object]) -> list[str]:
    """Apply schema rules. Return a list of violation strings (empty = pass)."""
    violations: list[str] = []

    goal = fields.get("goal")
    if not isinstance(goal, str) or len(goal.strip()) < MIN_GOAL_CHARS:
        violations.append(
            f"`goal` is missing, empty, or under {MIN_GOAL_CHARS} characters - fuzzy goal produces fuzzy downstream work."
        )
    else:
        for word in FORBIDDEN_STATUS_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", goal, re.IGNORECASE):
                violations.append(
                    f"`goal` contains forbidden status word `{word}` - manifests must not import release-gate semantics into a non-release run."
                )

    dod = fields.get("definition_of_done")
    if not isinstance(dod, str) or len(dod.strip()) < MIN_DOD_CHARS:
        violations.append(
            f"`definition_of_done` is missing, empty, or under {MIN_DOD_CHARS} characters - the verifier and critic need a paragraph to evaluate against."
        )
    else:
        for word in FORBIDDEN_STATUS_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", dod, re.IGNORECASE):
                violations.append(
                    f"`definition_of_done` contains forbidden status word `{word}` - see goal rule."
                )

    expected_outputs = fields.get("expected_outputs")
    if not isinstance(expected_outputs, list) or len(expected_outputs) < 1:
        violations.append(
            "`expected_outputs` is empty - the verifier has no objective check without at least one testable output."
        )
    elif any(not (isinstance(item, str) and item.strip()) for item in expected_outputs):
        violations.append("`expected_outputs` contains an empty entry.")

    non_goals = fields.get("non_goals")
    if not isinstance(non_goals, list) or len(non_goals) < 1:
        violations.append(
            "`non_goals` is empty - explicit out-of-scope items keep the executor honest. Add at least one."
        )

    rollback_plan = fields.get("rollback_plan")
    if not isinstance(rollback_plan, str) or not rollback_plan.strip():
        violations.append(
            "`rollback_plan` is empty - every run must name how a revert would happen, even if it is `git revert <merge-commit>`."
        )

    allowed_paths = fields.get("allowed_paths")
    forbidden_paths = fields.get("forbidden_paths")
    if (
        isinstance(allowed_paths, list)
        and any(isinstance(p, str) and _is_broad_prefix(p) for p in allowed_paths)
        and (not isinstance(forbidden_paths, list) or len(forbidden_paths) < 1)
    ):
        broad = [p for p in allowed_paths if isinstance(p, str) and _is_broad_prefix(p)]
        violations.append(
            "`allowed_paths` includes a broad top-level prefix "
            f"({', '.join(broad)}) but `forbidden_paths` is empty. "
            "Add explicit forbidden_paths to bound the blast radius."
        )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="agent-pipeline-codex 0.5.5")
    parser.add_argument(
        "--run",
        help="Pipeline run id (directory under .agent-runs/). Without this, the check is a no-op.",
    )
    args = parser.parse_args()

    if not args.run:
        print(
            "check_manifest_schema: no --run argument provided; skipping (no-op outside a pipeline run)."
        )
        return 0

    manifest_path = RUN_DIR / args.run / "manifest.yaml"
    fields = _read_manifest(manifest_path)
    violations = _check(fields)

    if violations:
        print("check_manifest_schema: FAIL")
        print(f"  manifest: {manifest_path}")
        print("  violations:")
        for v in violations:
            print(f"    - {v}")
        return 1

    print(
        f"check_manifest_schema: PASS - manifest at {manifest_path.relative_to(REPO_ROOT)} satisfies the v0.5 schema."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

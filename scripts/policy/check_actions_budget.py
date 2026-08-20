#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate GitHub Actions workflow-cost discipline.

By default this check inspects workflow files changed in the current working
tree. In pipeline mode (``--run``), it also compares the current HEAD against
the branch upstream or an explicit base ref so committed workflow changes
cannot silently bypass the budget gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

WORKFLOW_RE = re.compile(r"^\.github/workflows/.*\.ya?ml$")
CRON_RE = re.compile(r"cron:\s*['\"]([^'\"]+)['\"]")
UPLOAD_RE = re.compile(r"uses:\s*actions/upload-artifact@")
HEAVY_MARKERS = (
    "apt-get install",
    "docker build",
    "docker/build-push-action",
    "install browsers",
    "playwright install",
    "setup-texlive",
    "texlive",
    "ollama pull",
    "cleanroom",
    "e2e",
)
GLOBAL_COVERAGE_GATES = {"ci-test.yml", "deterministic-detectors.yml"}
RELEASE_CANDIDATE_WORKFLOWS = {"native-beta-candidate-artifacts.yml"}
STATIC_CONCURRENCY_GROUPS = {
    "ci-installer-compile.yml": "ci-installer-compile-reusable-${{ github.ref }}"
}


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return Path(proc.stdout.strip())
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "policy" and script_dir.parent.name == "scripts":
        return script_dir.parents[1]
    return script_dir.parent


REPO_ROOT = _repo_root()


def _git_status_paths() -> list[Path]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1].strip()
        raw = raw.strip('"')
        normalized = raw.replace("\\", "/")
        if WORKFLOW_RE.match(normalized):
            paths.append(REPO_ROOT / raw)
    return paths


def _git_diff_paths(base_ref: str) -> list[Path]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode != 0:
        return []

    paths: list[Path] = []
    for raw in proc.stdout.splitlines():
        normalized = raw.strip().replace("\\", "/")
        if WORKFLOW_RE.match(normalized):
            paths.append(REPO_ROOT / normalized)
    return paths


def _discover_base_ref(explicit_base: str | None) -> str | None:
    if explicit_base:
        return explicit_base

    for args in (
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        ["rev-parse", "--verify", "origin/main"],
    ):
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def _changed_workflows_for_run(base_ref: str | None) -> tuple[list[Path], str | None]:
    discovered = _discover_base_ref(base_ref)
    paths = _git_status_paths()
    if discovered:
        paths.extend(_git_diff_paths(discovered))
    return sorted(set(paths)), discovered


def _all_workflows() -> list[Path]:
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    return sorted(
        path
        for path in workflow_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )


def _has_pr_trigger(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*pull_request\s*:", text))


def _has_push_main(text: str) -> bool:
    push_match = re.search(r"(?m)^  push\s*:", text)
    if not push_match:
        return False
    next_top_level = re.search(r"(?m)^  [a-zA-Z_][a-zA-Z0-9_-]*\s*:", text[push_match.end() :])
    push_body_end = push_match.end() + next_top_level.start() if next_top_level else len(text)
    push_body = text[push_match.end() : push_body_end]
    return bool(
        re.search(r"branches:\s*\[\s*main\s*\]", push_body)
        or re.search(r"(?m)^\s*-\s*main\s*$", push_body)
    )


def _is_release_or_tag_workflow(path: Path, text: str) -> bool:
    name = path.name.lower()
    has_tag_trigger = bool(
        re.search(r"(?m)^\s*tags\s*:", text) or re.search(r"(?m)^\s*-\s*['\"]?v?\*['\"]?\s*$", text)
    )
    return (
        path.name in RELEASE_CANDIDATE_WORKFLOWS
        or "release" in name
        or "tag" in name
        or has_tag_trigger
    )


def _has_concurrency(path: Path, text: str) -> bool:
    static_group = STATIC_CONCURRENCY_GROUPS.get(path.name)
    return (
        "concurrency:" in text
        and (
            "group: ${{ github.workflow }}-${{ github.ref }}" in text
            or (static_group is not None and f"group: {static_group}" in text)
        )
        and re.search(r"cancel-in-progress:\s*true", text) is not None
    )


def _is_daily_cron(expr: str) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    return fields[2] == "*" and fields[3] == "*" and fields[4] == "*"


def _has_heavy_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in HEAVY_MARKERS)


def _has_cache(text: str) -> bool:
    lowered = text.lower()
    return (
        "actions/cache@" in lowered
        or ("astral-sh/setup-uv@" in lowered and "enable-cache: true" in lowered)
        or "rust-cache@" in lowered
        or "cache: pip" in lowered
        or "cache: npm" in lowered
        or "cache-from:" in lowered
        or "cache-to:" in lowered
        or "workflow-cost: local-docker-cache" in lowered
    )


def _has_python_pr_matrix(text: str) -> bool:
    if not _has_pr_trigger(text) or "python-version" not in text:
        return False
    matrix_block = re.search(r"matrix:\s*(?P<body>.*?)(?=^\S|\Z)", text, re.M | re.S)
    if not matrix_block:
        return False
    body = matrix_block.group("body")
    return "python-version" in body and (
        "[" in body or "3.11" in body or "3.13" in body or len(re.findall(r"3\.\d+", body)) > 1
    )


def _artifact_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if not UPLOAD_RE.search(line):
            continue
        block = [line]
        base_indent = len(line) - len(line.lstrip())
        for later in lines[index + 1 :]:
            indent = len(later) - len(later.lstrip())
            if later.lstrip().startswith("- ") and indent <= base_indent:
                break
            block.append(later)
        blocks.append("\n".join(block))
    return blocks


def validate_workflow(path: Path, text: str) -> list[str]:
    violations: list[str] = []
    release_or_tag = _is_release_or_tag_workflow(path, text)
    pr_trigger = _has_pr_trigger(text)

    if "@daily" in text:
        violations.append("daily cron is forbidden without explicit Scott approval")
    for expr in CRON_RE.findall(text):
        if _is_daily_cron(expr):
            violations.append(f"daily cron `{expr}` is forbidden; weekly is the maximum default")

    if not release_or_tag and not _has_concurrency(path, text):
        violations.append("missing required concurrency block with cancel-in-progress: true")

    if pr_trigger and _has_push_main(text):
        violations.append(
            "duplicates pull_request main and push main for the same validation workflow"
        )

    if _has_heavy_marker(text):
        if "paths:" not in text and path.name not in GLOBAL_COVERAGE_GATES:
            violations.append("heavy workflow is missing paths filters")
        if not _has_cache(text):
            violations.append(
                "heavy workflow is missing cache coverage for expensive installs/downloads"
            )

    if pr_trigger and "macos-latest" in text:
        violations.append(
            "macOS jobs are forbidden on PR-fired workflows without explicit Scott approval"
        )

    if (
        pr_trigger
        and "windows-latest" in text
        and "workflow-cost: windows-pr-justification" not in text
    ):
        violations.append(
            "Windows PR jobs require workflow-cost: windows-pr-justification evidence"
        )

    if _has_python_pr_matrix(text):
        violations.append(
            "PR CI must use one production Python version by default, currently Python 3.12"
        )

    if not release_or_tag:
        for block in _artifact_blocks(text):
            if not re.search(r"retention-days:\s*7\b", block):
                violations.append("upload-artifact step is missing retention-days: 7")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all", action="store_true", help="Check every workflow file, not only changed workflows."
    )
    parser.add_argument(
        "--run", help="Pipeline run id. Enables committed diff detection for workflow edits."
    )
    parser.add_argument("--base-ref", help="Base ref or SHA for committed workflow diff detection.")
    args = parser.parse_args()

    base_ref: str | None = None
    if args.all:
        paths = _all_workflows()
    elif args.run:
        paths, base_ref = _changed_workflows_for_run(args.base_ref)
        if not base_ref and not paths:
            print(
                "check_actions_budget: FAIL (pipeline mode cannot prove whether committed workflow files changed; "
                "pass --base-ref or configure an upstream branch)"
            )
            return 1
    else:
        paths = _git_status_paths()
    if not paths:
        suffix = f" against {base_ref}" if base_ref else ""
        print(f"check_actions_budget: PASS (no changed workflow files{suffix})")
        return 0

    failures: list[tuple[Path, list[str]]] = []
    for path in paths:
        if not path.exists():
            continue
        violations = validate_workflow(path, path.read_text(encoding="utf-8-sig"))
        if violations:
            failures.append((path, violations))

    if failures:
        print("check_actions_budget: FAIL")
        for path, violations in failures:
            rel = path.relative_to(REPO_ROOT)
            print(f"  - {rel}")
            for violation in violations:
                print(f"    - {violation}")
        return 1

    suffix = f" against {base_ref}" if base_ref else ""
    print(f"check_actions_budget: PASS ({len(paths)} workflow file(s) checked{suffix})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

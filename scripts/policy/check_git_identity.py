#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: Git author identity must not credit another GitHub account."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root


REPO_ROOT = find_repo_root(__file__)
CANONICAL_EMAIL = "1474146+scottconverse@users.noreply.github.com"
BLOCKED_EMAILS = {"scott@users.noreply.github.com"}


def _git(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def _configured_email() -> str | None:
    proc = _git(["config", "--get", "user.email"])
    email = proc.stdout.strip()
    return email or None


def _history_bad_email_matches() -> list[str]:
    refs_proc = _git(
        [
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads",
            "refs/remotes/origin",
            "refs/tags",
        ],
        check=True,
    )
    refs = [line.strip() for line in refs_proc.stdout.splitlines() if line.strip()]
    if not refs:
        return []

    log_proc = _git(
        [
            "log",
            *refs,
            "--format=%H%x09%D%x09%an <%ae>%x09%cn <%ce>%x09%s",
        ],
        check=True,
    )
    matches: list[str] = []
    for line in log_proc.stdout.splitlines():
        if any(email in line for email in BLOCKED_EMAILS):
            matches.append(line)
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-config-required",
        action="store_true",
        help="Fail unless local Git config uses CivicCast's canonical author email.",
    )
    args = parser.parse_args()

    violations: list[str] = []
    configured_email = _configured_email()
    if args.local_config_required:
        if configured_email != CANONICAL_EMAIL:
            violations.append(
                "git config user.email must be "
                f"{CANONICAL_EMAIL!r}; current value is {configured_email!r}."
            )
    elif configured_email in BLOCKED_EMAILS and not os.environ.get("CI"):
        violations.append(
            f"git config user.email is blocked because GitHub credits it to another account: {configured_email!r}."
        )

    history_matches = _history_bad_email_matches()
    if history_matches:
        violations.append("blocked Git author email still appears in branch/tag history:")
        violations.extend(f"  {line}" for line in history_matches[:20])
        if len(history_matches) > 20:
            violations.append(f"  ... {len(history_matches) - 20} more")

    if violations:
        print("check_git_identity: FAIL")
        for item in violations:
            print(f"  - {item}")
        return 1

    print("check_git_identity: PASS - Git identity and visible history are clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

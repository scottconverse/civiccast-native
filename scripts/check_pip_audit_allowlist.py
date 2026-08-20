#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Fail the security-scan gate on any pip-audit finding not in the allowlist.

Audit item #27. ``pip-audit --format json`` reports every known vulnerability
regardless of whether it's fixable; this script is the triage step — a
finding is either fixed (bump the dependency) or explicitly reviewed and
pinned in ``security/pip-audit-allowlist.json`` with a dated reason. A red
gate the team can't act on trains everyone to ignore it, so nothing is
silently permitted: every ID in the report must appear in the allowlist by
(package, id) or the gate fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "security" / "pip-audit-allowlist.json"


def load_allowlist() -> set[tuple[str, str]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {(entry["package"], entry["id"]) for entry in data["allowed"]}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_pip_audit_allowlist.py <pip-audit-report.json>", file=sys.stderr)
        return 2

    report_path = Path(argv[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    allowlist = load_allowlist()

    unallowed: list[str] = []
    for dependency in report.get("dependencies", []):
        package = dependency.get("name", "")
        for vuln in dependency.get("vulns", []):
            vuln_id = vuln.get("id", "")
            if (package, vuln_id) not in allowlist:
                unallowed.append(f"{package} {dependency.get('version', '?')}: {vuln_id}")

    if unallowed:
        print("pip-audit found findings not in security/pip-audit-allowlist.json:", file=sys.stderr)
        for line in unallowed:
            print(f"  - {line}", file=sys.stderr)
        print(
            "\nFix by upgrading the dependency, or add a dated, reasoned entry "
            "to security/pip-audit-allowlist.json if there is genuinely no fix "
            "and the finding is not reachable.",
            file=sys.stderr,
        )
        return 1

    print("pip-audit: all findings are either absent or explicitly allowlisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

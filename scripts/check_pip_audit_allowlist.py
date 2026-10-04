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

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "security" / "pip-audit-allowlist.json"


def load_allowlist() -> set[tuple[str, str]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("allowed"), list):
        raise ValueError("allowlist must contain an allowed array")
    allowed: set[tuple[str, str]] = set()
    today = date.today()
    for entry in data["allowed"]:
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(key), str) or not entry[key].strip()
            for key in ("package", "id", "reviewed", "review_by", "reason")
        ):
            raise ValueError("each exception requires identity, reason and review dates")
        reviewed = date.fromisoformat(entry["reviewed"])
        review_by = date.fromisoformat(entry["review_by"])
        if not reviewed <= today <= review_by:
            raise ValueError("an exception is expired, future-dated or has reversed dates")
        allowed.add((entry["package"], entry["id"]))
    return allowed


def validate_report(report: object) -> list[dict[str, Any]]:
    """Validate structure; graph completeness is checked against independent input."""
    if not isinstance(report, dict):
        raise ValueError("audit report must be an object")
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("audit report must contain a nonempty dependencies array")
    for dependency in dependencies:
        if not isinstance(dependency, dict) or any(
            not isinstance(dependency.get(key), str) or not dependency[key].strip()
            for key in ("name", "version")
        ):
            raise ValueError("every dependency requires name and version")
        if "skip_reason" in dependency:
            raise ValueError("audit skipped a dependency; complete verification is required")
        vulns = dependency.get("vulns")
        if not isinstance(vulns, list) or any(
            not isinstance(vuln, dict)
            or not isinstance(vuln.get("id"), str)
            or not vuln["id"].strip()
            for vuln in vulns
        ):
            raise ValueError("every dependency requires an explicit vulnerability array with IDs")
    return dependencies


def identities(rows: object) -> dict[str, Version]:
    """Normalize pip/PyPI identity, rejecting duplicate or ambiguous entries."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("independent inventory must be a nonempty array")
    result: dict[str, Version] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("inventory entry must be an object")
        name, version = row.get("name"), row.get("version")
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name
        ):
            raise ValueError("invalid dependency name")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("invalid dependency version")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in result:
            raise ValueError("duplicate normalized dependency identity")
        try:
            result[name] = Version(version)
        except InvalidVersion as exc:
            raise ValueError("invalid dependency version") from exc
    return result


def requirements_inventory(path: Path) -> list[dict[str, str]]:
    """Native exact pins only; not a universal lock or platform-marker resolver."""
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().removesuffix("\\").strip()
        if not line:
            continue
        if re.fullmatch(r"--hash=sha256:[a-f0-9]{64}", line):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            raise ValueError("unsupported native requirement syntax") from exc
        specs = list(requirement.specifier)
        if (
            requirement.marker
            or requirement.url
            or requirement.extras
            or len(specs) != 1
            or specs[0].operator != "=="
            or "*" in specs[0].version
        ):
            raise ValueError(
                "native graph requires exact unmarked pins; universal exports are unsupported"
            )
        result.append({"name": requirement.name, "version": specs[0].version})
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    graph = parser.add_mutually_exclusive_group(required=True)
    graph.add_argument(
        "--inventory", type=Path, help="independent pip list JSON from audited environment"
    )
    graph.add_argument(
        "--requirements", type=Path, help="independent native exact-pin graph (no markers/ranges)"
    )
    parser.add_argument("--scanner-exit-code", type=int, required=True)
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        return 2
    report_path = args.report
    try:
        dependencies = validate_report(json.loads(report_path.read_text(encoding="utf-8")))
        expected = (
            identities(json.loads(args.inventory.read_text(encoding="utf-8")))
            if args.inventory is not None
            else identities(requirements_inventory(args.requirements))
        )
        if identities(dependencies) != expected:
            raise ValueError("audit name/version graph differs from independent inventory")
        findings = any(dependency["vulns"] for dependency in dependencies)
        if args.scanner_exit_code not in (0, 1) or (args.scanner_exit_code == 1) != findings:
            raise ValueError("scanner failed or exit status disagrees with complete receipt")
        allowlist = load_allowlist()
    except (OSError, ValueError) as exc:
        print(f"pip-audit verification incomplete: {exc}", file=sys.stderr)
        return 2

    unallowed: list[str] = []
    for dependency in dependencies:
        package = re.sub(r"[-_.]+", "-", dependency["name"]).lower()
        for vuln in dependency["vulns"]:
            vuln_id = vuln["id"]
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

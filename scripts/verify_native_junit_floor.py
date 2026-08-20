#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail closed when a native JUnit execution is incomplete or below its floor."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def passed_native_cases(junit_path: Path) -> int:
    """Return passed native cases, rejecting missing, skipped, failed, or errored nodes."""
    if not junit_path.is_file():
        raise ValueError(f"JUnit file is missing: {junit_path}")

    native_cases = [
        case
        for case in ET.parse(junit_path).iter("testcase")
        if case.get("classname", "").startswith("tests.native")
    ]
    if not native_cases:
        raise ValueError("JUnit contains no tests.native cases")
    identities = [(case.get("classname", ""), case.get("name", "")) for case in native_cases]
    if len(set(identities)) != len(identities):
        raise ValueError("JUnit contains duplicate tests.native testcase identities")

    incomplete = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in native_cases
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
    ]
    if incomplete:
        shown = ", ".join(incomplete[:20])
        remaining = len(incomplete) - 20
        suffix = f"; and {remaining} more" if remaining > 0 else ""
        raise ValueError(
            f"Native JUnit contains skipped, failed, or errored cases: {shown}{suffix}"
        )
    return len(native_cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--floor", type=int, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if args.floor <= 0:
        parser.error("--floor must be positive")

    try:
        passed = passed_native_cases(args.junit)
    except (ET.ParseError, ValueError) as exc:
        print(f"::error::{args.label} execution is unproven: {exc}")
        return 1

    print(f"{args.label}: {passed} passed (floor: {args.floor})")
    if passed < args.floor:
        print(
            f"::error::{args.label} native pass count {passed} < floor {args.floor}. "
            "The native proof is unproven."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

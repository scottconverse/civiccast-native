# SPDX-License-Identifier: Apache-2.0
"""Classify the single RC1 media limitation explicitly accepted by the owner.

This reads JUnit without rewriting its failed testcase. All other failures,
errors, skips and nonstandard pytest exits remain failures of required CI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from civiccast._version import __version__

_ACCEPTED_IDENTITY = (
    "tests.egress.test_gst_engine_wsl",
    "test_immediate_finite_playlist_reload_holds_rebases_and_stays_on_air",
)


def classify_media_junit(junit: Path, pytest_exit: int, minimum_cases: int) -> tuple[int, int]:
    """Return (passed, failed_but_owner_accepted), rejecting incomplete proof."""
    if pytest_exit not in (0, 1):
        raise ValueError(f"Nonstandard pytest exit: {pytest_exit}")
    root = ET.parse(junit).getroot()
    if any(list(root.iter(tag)) for tag in ("skipped", "error")):
        raise ValueError("Selected coverage was skipped or errored")
    cases = list(root.iter("testcase"))
    if len(cases) < minimum_cases:
        raise ValueError("Selected cases did not all execute")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate media testcase identities")
    accepted = 0
    for case, identity in zip(cases, identities, strict=True):
        if any(case.find(tag) is not None for tag in ("skipped", "error")):
            raise ValueError(f"Selected coverage was skipped or errored: {identity}")
        failures = case.findall("failure")
        if not failures:
            continue
        if __version__ != "1.0.0-rc.1" or identity != _ACCEPTED_IDENTITY or len(failures) != 1:
            raise ValueError(f"Unaccepted media failure: {identity}")
        failure = failures[0]
        message = failure.get("message", "")
        # Require both the exact observed result and the actual failing source
        # assertion. Merely finding these strings in captured logs is insufficient.
        assertions = re.findall(r"^assert .+$", message, re.MULTILINE)
        source_assertions = re.findall(r"^>\s+assert .+$", failure.text or "", re.MULTILINE)
        if (
            not message.startswith("AssertionError: ")
            or assertions != ["assert {66: 1} == {}"]
            or source_assertions != [">       assert _pes_pts_backward_steps(out_ts) == {}, text"]
            or "WORKER_RESULT {'error': None, 'teardown_clean': True}" not in message
            or "CTRL reload committed" not in message
        ):
            raise ValueError(f"Unaccepted media failure assertion: {identity}")
        accepted += 1
    if len(list(root.iter("failure"))) != accepted:
        raise ValueError("Unclassified JUnit failures")
    if bool(pytest_exit) != bool(accepted):
        raise ValueError("Pytest exit and JUnit failure evidence disagree")
    return len(cases) - accepted, accepted

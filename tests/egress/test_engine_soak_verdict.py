# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Failure-path tests for the engine-soak verdict (prototype/engine_soak.py).

A verifier must be proven to FAIL on a known-bad input before its PASS is trusted. The
original soak driver scored a crashed worker (rc=1, early exit) as PASS because it only
checked continuity + reload count, ignoring whether the worker survived. These tests pin
that the verdict now fails closed on every failure mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

# prototype/ is not a package; add it to the path to import the driver's pure logic.
sys.path.insert(0, str(Path(__file__).parent / ".." / ".." / "prototype"))
import engine_soak


def test_verdict_fails_on_early_worker_death() -> None:
    # THE bug that shipped a false PASS: a crashed worker must fail even with clean
    # continuity and reloads that landed before it died.
    assert engine_soak._verdict(worker_died_early=True, cc_full=0, committed=5) == "FAIL"


def test_verdict_fails_on_continuity_errors() -> None:
    assert engine_soak._verdict(worker_died_early=False, cc_full=3, committed=5) == "FAIL"


def test_verdict_fails_when_no_reload_landed() -> None:
    assert engine_soak._verdict(worker_died_early=False, cc_full=0, committed=0) == "FAIL"


def test_verdict_passes_only_when_fully_clean() -> None:
    assert engine_soak._verdict(worker_died_early=False, cc_full=0, committed=5) == "PASS"

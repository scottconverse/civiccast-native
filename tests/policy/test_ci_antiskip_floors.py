# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A CI anti-skip guard must not drift from the tests it guards.

GauntletGate T3 (Major, 2026-07-21). ``tests/live/test_finalization_worker.py``
and ``..._app_wiring.py`` gate their only real-ffmpeg, real-duration proofs
behind ``@pytest.mark.skipif(shutil.which("ffmpeg") is None ...)``. CI installs
ffmpeg but had junit-floor guards for only four OTHER suites -- so if the apt
package were renamed or the install step silently failed on a future runner
image, the only end-to-end proof that a finished broadcast becomes a real,
duration-correct recording would vanish with CI still green.

A floor guard names its tests as strings inside a YAML heredoc, which is
exactly the kind of reference that rots silently. This test fails locally the
moment a guarded test is renamed or moved, instead of leaving that discovery to
a red CI run on someone else's branch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI_TEST_WORKFLOW = ROOT / ".github" / "workflows" / "ci-test.yml"

GUARD_ANCHOR = "recording-finalization real-media proofs"


def _guarded_test_names() -> set[str]:
    """The test names the finalization floor guard requires to have executed."""

    workflow = CI_TEST_WORKFLOW.read_text(encoding="utf-8")
    anchor = workflow.index(GUARD_ANCHOR)
    # Slice the heredoc BODY: skip past the opening `python <<'PYFLOOR'` marker
    # to the closing one, or the slice ends before the set it is looking for.
    body_start = workflow.index("<<'PYFLOOR'", anchor) + len("<<'PYFLOOR'")
    block = workflow[body_start : workflow.index("PYFLOOR", body_start)]
    required = re.search(r"REQUIRED = \{(.*?)\}", block, re.DOTALL)
    assert required is not None, "The finalization floor guard lost its REQUIRED set."
    return set(re.findall(r'"([^"]+)"', required.group(1)))


def test_the_finalization_floor_guard_names_at_least_the_two_known_proofs() -> None:
    names = _guarded_test_names()
    assert {
        "test_real_media_trim_proof_duration_matches_trim_window",
        "test_end_broadcast_reaches_completed_via_app_wired_worker",
    } <= names


@pytest.mark.parametrize("test_name", sorted(_guarded_test_names()))
def test_every_guarded_test_still_exists_in_the_suite(test_name: str) -> None:
    """A renamed or deleted guarded test must fail here, not silently in CI."""

    live_tests = (ROOT / "tests" / "live").glob("test_finalization_worker*.py")
    definitions = [
        path.name
        for path in live_tests
        if re.search(rf"^def {re.escape(test_name)}\(", path.read_text(encoding="utf-8"), re.M)
    ]
    assert definitions, (
        f"CI's anti-skip floor requires {test_name!r} to execute, but no test by "
        "that name exists under tests/live/. Rename the guard in "
        ".github/workflows/ci-test.yml in the same commit as the test."
    )


def test_the_guarded_tests_are_the_ffmpeg_gated_ones() -> None:
    """The guard is pointless if it protects a test that never skips.

    Both guarded tests must actually carry the ffmpeg skip predicate -- that
    is the thing the floor exists to detect.
    """

    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / "tests" / "live").glob("test_finalization_worker*.py")
    }
    for test_name in _guarded_test_names():
        owner = next(
            (name for name, text in sources.items() if f"def {test_name}(" in text),
            None,
        )
        assert owner is not None
        text = sources[owner]
        before_def = text[: text.index(f"def {test_name}(")]
        decorator = before_def.rsplit("@pytest.mark.skipif", 1)
        assert len(decorator) == 2, f"{test_name} is guarded but has no skip predicate."
        assert 'shutil.which("ffmpeg")' in decorator[1], (
            f"{test_name} no longer skips on missing ffmpeg; the CI floor guard "
            "protects a condition that can no longer occur."
        )

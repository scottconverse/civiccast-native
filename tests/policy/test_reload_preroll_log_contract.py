# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""F-1: reject a commit without transaction-specific preroll evidence."""

import pytest

from scripts.ops.check_reload_preroll import check_log

_HELD = "CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=1)"
_READY_FINITE = (
    "CTRL reload: new leg preroll verified (reload_id=1) "
    "held_streams=2 timing=finite mode=immediate"
)
_READY_CLOCK = (
    "CTRL reload: new leg preroll verified (reload_id=1) held_streams=0 timing=clock mode=immediate"
)
_REBASE = (
    "CTRL reload: finite switch rebased to running time 2.171s mode=immediate streams=2 reload_id=1"
)
_FIRE = "CTRL reload: firing (reload_id=1)"
_COMMIT = "CTRL reload committed (elements=146)"


def test_held_and_unheld_preroll_proof() -> None:
    for lines in (
        [_HELD, _READY_FINITE, _FIRE, _REBASE, _COMMIT],
        [_READY_CLOCK, _FIRE, _COMMIT],
    ):
        assert check_log("\n".join(lines), 146) == (1, [])


@pytest.mark.parametrize(
    "lines",
    [
        [_COMMIT],
        [_READY_FINITE, _FIRE, _REBASE, _COMMIT],
        [_HELD, _READY_FINITE, _FIRE, _COMMIT],
        [_HELD, _READY_FINITE.replace("held_streams=2", "held_streams=0"), _FIRE, _REBASE, _COMMIT],
        [_HELD, _READY_CLOCK.replace("held_streams=0", "held_streams=2"), _FIRE, _COMMIT],
        [_HELD, _READY_FINITE, _FIRE.replace("=1", "=2"), _REBASE, _COMMIT],
        [_HELD, _READY_FINITE, _FIRE, _REBASE, _COMMIT, _COMMIT],
        [_HELD, _READY_FINITE, "WORKER_RESULT {'error': None}", _FIRE, _REBASE, _COMMIT],
        [_HELD, _READY_FINITE, _FIRE, _REBASE, _COMMIT.replace("146", "56")],
        [],
    ],
)
def test_missing_stale_reused_or_undersized_proof_fails(lines: list[str]) -> None:
    assert check_log("\n".join(lines), 146)[1]

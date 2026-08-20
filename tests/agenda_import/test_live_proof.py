# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Env-gated live proof against the real Legistar API (plan §8 task 8).

Off by default (skipped) -- matches the repo's existing network-gated
pattern (``tests/installer/test_tsduck_install.py``'s
``CIVICCAST_TSDUCK_NETWORK_TESTS``). When explicitly enabled, this hits
``webapi.legistar.com/v1/seattle`` for real and HARD-FAILS (not skips) on an
empty or malformed result -- "hard-fail, not skip, when enabled and empty"
(plan §9) is the whole point of a proof gate: a green skip must never be
mistaken for a green proof.

Run with:  CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 uv run pytest tests/agenda_import/test_live_proof.py
"""

from __future__ import annotations

import os

import pytest

from civiccast.agenda_import.legistar import LegistarSource

pytestmark = pytest.mark.skipif(
    os.environ.get("CIVICCAST_RUN_AGENDA_SOURCE_PROOF") != "1",
    reason="live-network-gated; set CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 to hit webapi.legistar.com for real",
)


def test_seattle_tenant_returns_a_real_nonempty_agenda() -> None:
    source = LegistarSource(timeout_seconds=15.0)

    meetings = source.fetch_meetings("seattle", since=__import__("datetime").date(2024, 1, 1))
    assert meetings, (
        "live Seattle Events fetch returned zero meetings -- proof gate FAILS, not skips"
    )

    agenda = source.fetch_agenda("seattle", meetings[0].external_id)
    assert agenda.items, (
        "live Seattle EventItems fetch returned zero items -- proof gate FAILS, not skips"
    )
    assert agenda.title

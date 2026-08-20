# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Env-gated live proof against the real PrimeGov API (plan §8 Phase 2 task 7).

Off by default (skipped) -- same convention as
``tests/agenda_import/test_live_proof.py`` (Legistar/Seattle). When
explicitly enabled, this hits ``longmont.primegov.com`` for real and
HARD-FAILS (not skips) if no upcoming meeting has an HTML compiled agenda
at the moment the test runs -- "hard-fail, not skip, when enabled and empty"
(plan §9) is the whole point of a proof gate.

Run with:  CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 uv run pytest tests/agenda_import/test_live_proof_primegov.py
"""

from __future__ import annotations

import os

import pytest

from civiccast.agenda_import.primegov import PrimeGovSource

pytestmark = pytest.mark.skipif(
    os.environ.get("CIVICCAST_RUN_AGENDA_SOURCE_PROOF") != "1",
    reason="live-network-gated; set CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 to hit longmont.primegov.com for real",
)


def test_longmont_tenant_returns_a_real_nonempty_html_agenda() -> None:
    source = PrimeGovSource(timeout_seconds=15.0)

    meetings = source.fetch_meetings("longmont")
    assert meetings, (
        "live Longmont ListUpcomingMeetings fetch returned zero meetings -- proof gate FAILS, not skips"
    )

    # Not every upcoming meeting has an HTML compiled agenda (see primegov.py
    # docstring) -- the proof gate must find at least one that does, not
    # assume the first meeting in the list qualifies.
    errors: list[str] = []
    for meeting in meetings:
        try:
            agenda = source.fetch_agenda("longmont", meeting.external_id)
        except Exception as exc:  # collecting per-meeting failures for the proof message
            errors.append(f"{meeting.external_id}: {exc}")
            continue
        assert agenda.items, (
            f"live Longmont meeting {meeting.external_id} returned an HTML agenda "
            "with zero items -- proof gate FAILS, not skips"
        )
        assert agenda.title
        return

    pytest.fail(
        "no upcoming Longmont meeting had a usable HTML compiled agenda -- "
        f"proof gate FAILS, not skips. Per-meeting errors: {errors}"
    )

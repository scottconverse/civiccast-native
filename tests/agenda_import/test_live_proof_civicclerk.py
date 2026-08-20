# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Env-gated live proof against the real CivicClerk API (plan §8 Phase 3 task 4).

Off by default (skipped) -- same convention as
``tests/agenda_import/test_live_proof.py`` (Legistar) and
``test_live_proof_primegov.py`` (PrimeGov). When explicitly enabled, this
hits ``portagemi.api.civicclerk.com`` (City of Portage, MI -- a real,
independently-found live tenant) for real and HARD-FAILS (not skips) if no
recent meeting has a fetchable, non-empty agenda document at the moment the
test runs -- "hard-fail, not skip, when enabled and empty" (plan §9) is the
whole point of a proof gate.

Run with:  CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 uv run pytest tests/agenda_import/test_live_proof_civicclerk.py
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from civiccast.agenda_import.civicclerk import CivicClerkSource

pytestmark = pytest.mark.skipif(
    os.environ.get("CIVICCAST_RUN_AGENDA_SOURCE_PROOF") != "1",
    reason=(
        "live-network-gated; set CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1 to hit "
        "portagemi.api.civicclerk.com for real"
    ),
)


def test_portage_tenant_returns_a_real_nonempty_agenda() -> None:
    source = CivicClerkSource(timeout_seconds=15.0)

    # fetch_meetings defaults `since` to today, which only returns future
    # meetings without agendas yet published -- look back 90 days for a
    # real meeting that already has a published agenda document.
    meetings = source.fetch_meetings("portagemi", since=date.today() - timedelta(days=90))
    assert meetings, (
        "live portagemi Events fetch returned zero meetings -- proof gate FAILS, not skips"
    )

    errors: list[str] = []
    for meeting in meetings:
        try:
            agenda = source.fetch_agenda("portagemi", meeting.external_id)
        except Exception as exc:  # collecting per-meeting failures for the proof message
            errors.append(f"{meeting.external_id}: {exc}")
            continue
        assert agenda.items, (
            f"live portagemi meeting {meeting.external_id} returned an agenda "
            "with zero items -- proof gate FAILS, not skips"
        )
        assert agenda.title
        return

    pytest.fail(
        "no recent portagemi meeting had a usable agenda document -- proof "
        f"gate FAILS, not skips. Per-meeting errors: {errors}"
    )

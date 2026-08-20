# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the PlayoutDispatcher (S4 slice 3).

The dispatcher's whole job is to enqueue the right engine nudge — ``start`` for
a dark channel, ``reload`` for a running one — using only the existing
EgressCommand actions. Exercised against the real InMemoryEgressStore.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.egress.dispatcher import PlayoutDispatcher
from civiccast.egress.models import EgressStateRow
from civiccast.egress.store import InMemoryEgressStore

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _dispatcher(store: InMemoryEgressStore) -> PlayoutDispatcher:
    return PlayoutDispatcher(store, clock=lambda: _NOW, id_factory=lambda: "abc123")


def _set_state(store: InMemoryEgressStore, channel_id: str, state: str) -> None:
    store.write_state(
        EgressStateRow(channel_id=channel_id, state=state, updated_at=_NOW)  # type: ignore[arg-type]
    )


class TestStartVsReload:
    def test_dark_channel_with_no_state_gets_start(self) -> None:
        store = InMemoryEgressStore()
        outcome = _dispatcher(store).dispatch(channel_id="public", issued_by="dana")
        assert outcome.action == "start"
        pending = store.pop_pending_commands("public")
        assert len(pending) == 1
        assert pending[0].action == "start"
        assert pending[0].issued_by == "dana"
        assert pending[0].command_id == "commit-start-abc123"

    @pytest.mark.parametrize("state", ["STOPPED", "STOPPING", "DRAINING", "ERROR"])
    def test_down_states_get_start(self, state: str) -> None:
        store = InMemoryEgressStore()
        _set_state(store, "public", state)
        outcome = _dispatcher(store).dispatch(channel_id="public", issued_by="dana")
        assert outcome.action == "start"

    @pytest.mark.parametrize("state", ["STARTING", "ON_AIR", "TRANSITIONING", "FALLBACK_SLATE"])
    def test_running_states_get_reload(self, state: str) -> None:
        store = InMemoryEgressStore()
        _set_state(store, "public", state)
        outcome = _dispatcher(store).dispatch(channel_id="public", issued_by="dana")
        assert outcome.action == "reload"
        pending = store.pop_pending_commands("public")
        assert pending[0].action == "reload"
        assert pending[0].command_id == "commit-reload-abc123"


class TestOutcome:
    def test_outcome_fields_and_default_issuer(self) -> None:
        store = InMemoryEgressStore()
        outcome = _dispatcher(store).dispatch(channel_id="public")
        assert outcome.channel_id == "public"
        assert outcome.dispatched_at == _NOW
        assert outcome.command_id == "commit-start-abc123"
        # No issued_by supplied → defaults to a non-empty marker.
        assert store.pop_pending_commands("public")[0].issued_by == "commit-to-air"

    def test_only_targets_the_requested_channel(self) -> None:
        store = InMemoryEgressStore()
        _dispatcher(store).dispatch(channel_id="public", issued_by="dana")
        assert store.pop_pending_commands("gov") == []
        assert len(store.pop_pending_commands("public")) == 1

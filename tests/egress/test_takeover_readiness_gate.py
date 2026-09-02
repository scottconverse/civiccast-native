# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Nothing durable happens for a source that is not observed ready (WP-07).

Audit ENG-003's operational consequence: a manual takeover writes a public
audit row and queues a command that moves air. Both had to become impossible
for a source nobody had checked, whose check had failed, whose check had gone
stale, or which was edited between the operator's ingest plan and the Take.

The assertions here are deliberately about ABSENCE of side effects, not just
about the raised exception -- an exception raised after the audit row was
written would still have left the station with a record of a takeover that
never happened, and a queued command that would move air anyway.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.takeover_service import TakeoverNotReadyError, TakeoverService
from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
from civiccast.live.models import LiveSourceResponse
from civiccast.live.relay import build_ingest_plan

_ENDPOINT = "srt://0.0.0.0:9000?mode=listener"


@dataclass(frozen=True)
class _Verdict:
    ok: bool
    reason: str
    secret_ref: str | None = None


def _source(
    *,
    probe_state: str = "ready",
    age_seconds: float = 1.0,
    credentials_handle: str | None = None,
) -> LiveSourceResponse:
    observed_at = (
        datetime.now(UTC) - timedelta(seconds=age_seconds)
        if probe_state != "never_probed"
        else None
    )
    return LiveSourceResponse(
        live_source_id="council-encoder",
        channel_id="public",
        name="Council Room Encoder",
        source_type="srt",
        endpoint_url=_ENDPOINT,
        credentials_handle=credentials_handle,
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        probe_state=probe_state,  # type: ignore[arg-type]
        probe_observed_at=observed_at,
        probe_detail=None if probe_state != "failed" else "Connection refused by the encoder.",
        probe_error_code=None if probe_state != "failed" else "probe_refused",
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


def _build(engine: Engine, source: LiveSourceResponse, verdict: _Verdict | None = None):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    audit = PostgresTakeoverAuditStore(factory)
    egress = InMemoryEgressStore()
    service = TakeoverService(
        audit,
        egress,
        lambda channel_id: build_ingest_plan(channel_id, [], live_sources=[source]),
        id_factory=lambda: "tok",
        readiness_verifier=(
            None if verdict is None else (lambda *_args: verdict)  # type: ignore[arg-type,return-value]
        ),
    )
    return service, egress, audit


class TestPlanHealthFloor:
    """The floor that applies even with no verifier injected."""

    @pytest.mark.parametrize(
        ("probe_state", "age_seconds"),
        [
            ("never_probed", 0.0),
            ("failed", 1.0),
            ("ready", 3600.0),  # stale
        ],
    )
    def test_unready_source_creates_no_audit_row_and_queues_no_command(
        self, engine: Engine, probe_state: str, age_seconds: float
    ) -> None:
        service, egress, audit = _build(
            engine, _source(probe_state=probe_state, age_seconds=age_seconds)
        )
        with pytest.raises(TakeoverNotReadyError):
            service.take(channel_id="public", operator_id="dana")
        assert audit.get_active("public") is None
        assert audit.list_by_channel("public") == []
        assert egress.pop_pending_commands("public") == []

    def test_an_observed_ready_source_still_takes_air(self, engine: Engine) -> None:
        service, egress, audit = _build(engine, _source())
        session = service.take(channel_id="public", operator_id="dana")
        assert session.source_ref == "council-encoder"
        assert audit.get_active("public") is not None
        assert len(egress.pop_pending_commands("public")) == 1

    def test_state_reports_cannot_takeover_for_an_unchecked_source(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine, _source(probe_state="never_probed"))
        assert service.state("public").can_takeover is False


class TestFreshnessVerifier:
    def test_a_refusing_verifier_leaves_no_audit_row_and_no_command(self, engine: Engine) -> None:
        # The plan says ready (observed one second ago) but the verifier's own
        # fresh probe says no -- the race between preflight and takeover.
        service, egress, audit = _build(
            engine,
            _source(),
            _Verdict(ok=False, reason="Council Room Encoder did not answer the last check."),
        )
        with pytest.raises(TakeoverNotReadyError, match="did not answer"):
            service.take(channel_id="public", operator_id="dana")
        assert audit.get_active("public") is None
        assert audit.list_by_channel("public") == []
        assert egress.pop_pending_commands("public") == []

    def test_an_approving_verifier_lets_the_takeover_through(self, engine: Engine) -> None:
        service, egress, _audit = _build(
            engine, _source(), _Verdict(ok=True, reason="re-checked just now")
        )
        service.take(channel_id="public", operator_id="dana")
        assert len(egress.pop_pending_commands("public")) == 1

    def test_a_credential_handle_reaches_the_persisted_source_plan(self, engine: Engine) -> None:
        service, _egress, audit = _build(
            engine,
            _source(credentials_handle="council-srt-passphrase"),
            _Verdict(ok=True, reason="ok", secret_ref="council-srt-passphrase"),
        )
        session = service.take(channel_id="public", operator_id="dana")
        assert session.source_plan_json is not None
        # A HANDLE, in a durable audit row. The secret is resolved by the
        # worker at element-construction time and is never written here.
        assert "council-srt-passphrase" in session.source_plan_json
        stored = audit.get_active("public")
        assert stored is not None
        assert '"secret_ref":"council-srt-passphrase"' in (stored.source_plan_json or "").replace(
            ": ", ":"
        )

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pre-flight checklist contract evaluator tests (SQLite path).

Sprint 0.4 Slice 1 Commit 5. The evaluator contract under test:

* The canonical nine checks fire in declared order.
* Required checks (network, storage, live_source, recording_target,
  operator_confirm) gate readiness; AI runtime is allowed to be
  ``not_configured``; the publish surfaces never block.
* Every ``fail`` carries an actionable, machine-readable reason code.
* The three publish surfaces (syndication, internet_archive, nas)
  report the station's real provider posture.
* The live_source check depends on a LiveSource row matching the
  session's channel_id; the recording_target check depends on any
  RecordingTarget row.

All scenarios run against the SQLite test path (matches the rest of
the live module's unit-test posture); no real Postgres needed because
the evaluator does not exercise concurrency or DB-level CHECK
constraints.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.live.models
import civiccast.schedule.models  # noqa: F401  -- ATTACH hook on SQLite
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live import (
    PREFLIGHT_CHECK_AI_RUNTIME,
    PREFLIGHT_CHECK_INTERNET_ARCHIVE,
    PREFLIGHT_CHECK_LIVE_SOURCE,
    PREFLIGHT_CHECK_NAS,
    PREFLIGHT_CHECK_NETWORK,
    PREFLIGHT_CHECK_OPERATOR_CONFIRM,
    PREFLIGHT_CHECK_RECORDING_TARGET,
    PREFLIGHT_CHECK_STORAGE,
    PREFLIGHT_CHECK_SYNDICATION,
    PREFLIGHT_STATUS_FAIL,
    PREFLIGHT_STATUS_NOT_CONFIGURED,
    PREFLIGHT_STATUS_PASS,
    LiveSession,
    LiveSource,
    PreflightEvaluator,
    PreflightInputs,
    RecordingTarget,
)
from civiccast.live.preflight import (
    _PREFLIGHT_CHECK_ORDER,
    REASON_AI_RUNTIME_NOT_CONFIGURED,
    REASON_AI_RUNTIME_NOT_READY,
    REASON_LIVE_SESSION_NOT_FOUND,
    REASON_LIVE_SOURCE_NOT_PROBED,
    REASON_NETWORK_NOT_PROBED,
    REASON_NETWORK_UNREACHABLE,
    REASON_NO_LIVE_SOURCE_FOR_CHANNEL,
    REASON_NO_RECORDING_TARGET,
    REASON_OPERATOR_NOT_CONFIRMED,
    REASON_PUBLISH_SURFACE_SIMULATED,
    REASON_STORAGE_INSUFFICIENT,
    REASON_STORAGE_NOT_PROBED,
)
from civiccast.live.recording_paths import REHEARSAL_RECORDING_TARGET_ID

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Per-test ephemeral SQLite engine bound to ``Base.metadata``."""
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def evaluator(engine: Engine) -> PreflightEvaluator:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return PreflightEvaluator(
        session_factory=factory,
        source_probe=lambda source: (True, f"Source {source.live_source_id!r} delivered media."),
    )


def _seed_session_and_source_and_target(engine: Engine) -> None:
    """Seed a LiveSession (idle), a matching LiveSource, and a
    RecordingTarget. Reused by happy-path + most fail-mode tests."""
    with Session(bind=engine) as sess:
        sess.add(
            LiveSession(
                live_session_id="council-2026-05-15",
                channel_id="gov-ch12",
                title="City Council Meeting",
                state="idle",
            )
        )
        sess.add(
            LiveSource(
                live_source_id="room-a-rtmp",
                channel_id="gov-ch12",
                name="Council Room A RTMP",
                source_type="rtmp",
                endpoint_url="rtmp://camera.example/live",
            )
        )
        sess.add(
            RecordingTarget(
                recording_target_id="nas-primary",
                name="NAS Primary",
                target_uri="/srv/civiccast/recordings",
            )
        )
        sess.commit()


def _all_pass_inputs(
    *,
    operator_confirmed: bool = True,
    ai_runtime_ready: bool | None = True,
) -> PreflightInputs:
    """Build inputs that pass the required checks by default."""
    return PreflightInputs(
        live_session_id="council-2026-05-15",
        live_source_id="room-a-rtmp",
        network_reachable=True,
        storage_free_bytes=200 * (1024**3),  # 200 GiB
        ai_runtime_ready=ai_runtime_ready,
        operator_confirmed=operator_confirmed,
    )


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


class TestContractShape:
    """Locks: every evaluation has nine checks in canonical order."""

    def test_nine_checks_in_canonical_order(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs())
        assert [c.name for c in result.checks] == list(_PREFLIGHT_CHECK_ORDER)
        assert len(result.checks) == 9

    def test_canonical_order_includes_all_required_names(self) -> None:
        # The constants and the order tuple must agree.
        expected = {
            PREFLIGHT_CHECK_NETWORK,
            PREFLIGHT_CHECK_STORAGE,
            PREFLIGHT_CHECK_AI_RUNTIME,
            PREFLIGHT_CHECK_LIVE_SOURCE,
            PREFLIGHT_CHECK_RECORDING_TARGET,
            PREFLIGHT_CHECK_OPERATOR_CONFIRM,
            PREFLIGHT_CHECK_SYNDICATION,
            PREFLIGHT_CHECK_INTERNET_ARCHIVE,
            PREFLIGHT_CHECK_NAS,
        }
        assert set(_PREFLIGHT_CHECK_ORDER) == expected


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """All required checks pass + operator confirms + AI ready =>
    ready = True. Placeholders still emit not_configured."""

    def test_all_required_pass_ready_true(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs())
        assert result.ready is True
        by_name = {c.name: c for c in result.checks}
        assert by_name[PREFLIGHT_CHECK_NETWORK].status == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_STORAGE].status == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_AI_RUNTIME].status == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_LIVE_SOURCE].status == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_RECORDING_TARGET].status == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_OPERATOR_CONFIRM].status == PREFLIGHT_STATUS_PASS

    def test_ai_runtime_not_configured_does_not_block_ready(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs(ai_runtime_ready=None))
        assert result.ready is True
        by_name = {c.name: c for c in result.checks}
        ai = by_name[PREFLIGHT_CHECK_AI_RUNTIME]
        assert ai.status == PREFLIGHT_STATUS_NOT_CONFIGURED
        assert ai.reason_code == REASON_AI_RUNTIME_NOT_CONFIGURED

    def test_selected_source_must_exist_on_the_session_channel(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)

        result = evaluator.evaluate(
            _all_pass_inputs().model_copy(update={"live_source_id": "different-camera"})
        )

        assert result.ready is False
        source = next(check for check in result.checks if check.name == PREFLIGHT_CHECK_LIVE_SOURCE)
        assert source.status == PREFLIGHT_STATUS_FAIL
        assert "different-camera" in (source.message or "")


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


class TestPublishSurfaces:
    """Syndication / IA / NAS report the station's real provider posture
    and never block readiness. Full posture matrix:
    tests/live/test_preflight_publish_surfaces.py."""

    @pytest.mark.parametrize(
        "surface",
        [
            PREFLIGHT_CHECK_SYNDICATION,
            PREFLIGHT_CHECK_INTERNET_ARCHIVE,
            PREFLIGHT_CHECK_NAS,
        ],
    )
    def test_default_station_reports_simulated_not_a_stale_roadmap_promise(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
        surface: str,
    ) -> None:
        """On a default install these run on mocks that write nothing.

        The old copy said the integration "lands in a later rung" — false at
        rc17, and it told the operator nothing about their own station.
        """
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[surface]
        assert check.status == PREFLIGHT_STATUS_NOT_CONFIGURED
        assert check.reason_code == REASON_PUBLISH_SURFACE_SIMULATED
        assert check.message is not None
        assert "simulation" in check.message
        assert "later rung" not in check.message

    def test_publish_surfaces_do_not_block_ready(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs())
        # All three surfaces are not_configured, yet ready is True.
        assert result.ready is True


# ---------------------------------------------------------------------------
# Required-check fail modes
# ---------------------------------------------------------------------------


class TestNetworkCheck:
    def test_not_probed_fails_with_actionable_reason(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        inputs = _all_pass_inputs()
        inputs = inputs.model_copy(update={"network_reachable": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NETWORK_NOT_PROBED
        assert check.message is not None and "probe" in check.message.lower()
        assert result.ready is False

    def test_unreachable_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        inputs = _all_pass_inputs().model_copy(update={"network_reachable": False})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NETWORK_UNREACHABLE
        assert result.ready is False


class TestStorageCheck:
    def test_not_probed_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_STORAGE_NOT_PROBED
        assert result.ready is False

    def test_insufficient_free_space_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        # Operator-supplied threshold = 50 GiB; provide 10 GiB free.
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": 10 * (1024**3)})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_STORAGE_INSUFFICIENT
        assert "GiB" in (check.message or "")
        assert result.ready is False

    def test_at_or_above_min_passes(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        # Exactly at the threshold passes.
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": 50 * (1024**3)})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_PASS


class TestAIRuntimeCheck:
    def test_probed_but_not_ready_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        inputs = _all_pass_inputs().model_copy(update={"ai_runtime_ready": False})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_AI_RUNTIME]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_AI_RUNTIME_NOT_READY
        # AI runtime fail DOES block readiness even though it's optional.
        assert result.ready is False

    def test_ai_ready_passes(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs(ai_runtime_ready=True))
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_AI_RUNTIME]
        assert check.status == PREFLIGHT_STATUS_PASS


class TestLiveSourceCheck:
    def test_live_session_not_found_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # No seeding; the session does not exist.
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_LIVE_SESSION_NOT_FOUND
        assert result.ready is False

    def test_no_source_for_channel_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # Seed only the LiveSession + a RecordingTarget; no LiveSource.
        with Session(bind=engine) as sess:
            sess.add(
                LiveSession(
                    live_session_id="council-2026-05-15",
                    channel_id="gov-ch12",
                    title="X",
                    state="idle",
                )
            )
            sess.add(
                RecordingTarget(
                    recording_target_id="nas-primary",
                    name="NAS",
                    target_uri="/srv/recordings",
                )
            )
            sess.commit()
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NO_LIVE_SOURCE_FOR_CHANNEL
        assert result.ready is False

    def test_source_for_different_channel_does_not_count(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # Seed the LiveSession on gov-ch12 but a LiveSource on a
        # different channel; the live_source check must fail.
        with Session(bind=engine) as sess:
            sess.add(
                LiveSession(
                    live_session_id="council-2026-05-15",
                    channel_id="gov-ch12",
                    title="X",
                    state="idle",
                )
            )
            sess.add(
                LiveSource(
                    live_source_id="other-rtmp",
                    channel_id="hoa-ch3",
                    name="HOA Room RTMP",
                    source_type="rtmp",
                    endpoint_url="rtmp://camera/live",
                )
            )
            sess.add(
                RecordingTarget(
                    recording_target_id="nas-primary",
                    name="NAS",
                    target_uri="/srv/recordings",
                )
            )
            sess.commit()
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NO_LIVE_SOURCE_FOR_CHANNEL

    def test_configured_source_without_runtime_probe_fails_closed(
        self,
        engine: Engine,
    ) -> None:
        _seed_session_and_source_and_target(engine)

        @contextmanager
        def factory() -> Iterator[Session]:
            with Session(bind=engine) as session:
                yield session

        result = PreflightEvaluator(session_factory=factory).evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]

        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_LIVE_SOURCE_NOT_PROBED
        assert "server-side media probe" in (check.message or "")
        assert result.ready is False


class TestRecordingTargetCheck:
    def test_no_target_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # Seed LiveSession + LiveSource; no RecordingTarget.
        with Session(bind=engine) as sess:
            sess.add(
                LiveSession(
                    live_session_id="council-2026-05-15",
                    channel_id="gov-ch12",
                    title="X",
                    state="idle",
                )
            )
            sess.add(
                LiveSource(
                    live_source_id="room-a-rtmp",
                    channel_id="gov-ch12",
                    name="Room A RTMP",
                    source_type="rtmp",
                    endpoint_url="rtmp://camera/live",
                )
            )
            sess.commit()
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_RECORDING_TARGET]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NO_RECORDING_TARGET
        assert result.ready is False

    def test_rehearsal_only_target_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
        tmp_path,
    ) -> None:
        # The installer rehearsal target proves setup plumbing; public
        # broadcasts need a separate production target.
        with Session(bind=engine) as sess:
            sess.add(
                LiveSession(
                    live_session_id="council-2026-05-15",
                    channel_id="gov-ch12",
                    title="X",
                    state="idle",
                )
            )
            sess.add(
                LiveSource(
                    live_source_id="room-a-rtmp",
                    channel_id="gov-ch12",
                    name="Room A RTMP",
                    source_type="rtmp",
                    endpoint_url="rtmp://camera/live",
                )
            )
            rehearsal_dir = tmp_path / "private-rehearsals"
            rehearsal_dir.mkdir()
            sess.add(
                RecordingTarget(
                    recording_target_id=REHEARSAL_RECORDING_TARGET_ID,
                    name="Rehearsal only",
                    target_uri=rehearsal_dir.as_uri(),
                )
            )
            sess.commit()

        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_RECORDING_TARGET]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NO_RECORDING_TARGET
        assert "production local" in check.message
        assert result.ready is False


# ---------------------------------------------------------------------------
# Operator confirm gating
# ---------------------------------------------------------------------------


class TestOperatorConfirmGating:
    """Operator-confirm is the explicit human gate: every other check
    passing is not enough until the operator has confirmed."""

    def test_operator_not_confirmed_fails_even_when_others_pass(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        inputs = _all_pass_inputs(operator_confirmed=False)
        result = evaluator.evaluate(inputs)
        confirm = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_OPERATOR_CONFIRM]
        assert confirm.status == PREFLIGHT_STATUS_FAIL
        assert confirm.reason_code == REASON_OPERATOR_NOT_CONFIRMED
        # Every other required check is pass.
        by_name = {c.name: c for c in result.checks}
        for required in (
            PREFLIGHT_CHECK_NETWORK,
            PREFLIGHT_CHECK_STORAGE,
            PREFLIGHT_CHECK_LIVE_SOURCE,
            PREFLIGHT_CHECK_RECORDING_TARGET,
        ):
            assert by_name[required].status == PREFLIGHT_STATUS_PASS
        # Overall ready is False because operator did not confirm.
        assert result.ready is False

    def test_operator_confirmed_does_not_rescue_other_fails(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # No DB seed at all -> live_source fails; operator_confirmed
        # is True, but ready is still False.
        result = evaluator.evaluate(_all_pass_inputs(operator_confirmed=True))
        assert result.ready is False


# ---------------------------------------------------------------------------
# Reason-code completeness
# ---------------------------------------------------------------------------


class TestReasonCodesAreActionable:
    """Locks: every non-pass check carries a non-None reason_code and
    message. The operator UI maps reason_code to per-failure copy;
    relying on a None would be a silent UX bug."""

    def test_every_failed_check_has_reason_code_and_message(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        # No DB seed; no probes; no operator confirm -> maximum fail
        # coverage in a single evaluation.
        inputs = PreflightInputs(
            live_session_id="missing-session",
            live_source_id="missing-source",
            network_reachable=None,
            storage_free_bytes=None,
            ai_runtime_ready=None,
            operator_confirmed=False,
        )
        result = evaluator.evaluate(inputs)
        non_pass = [c for c in result.checks if c.status != PREFLIGHT_STATUS_PASS]
        assert (
            len(non_pass) >= 1
        )  # at minimum the required ones + placeholders fail or not_configured
        for c in non_pass:
            assert c.reason_code is not None, (
                f"check {c.name!r} status={c.status!r} has no reason_code"
            )
            assert c.message is not None, f"check {c.name!r} status={c.status!r} has no message"

    def test_pass_checks_may_omit_reason_code(
        self,
        engine: Engine,
        evaluator: PreflightEvaluator,
    ) -> None:
        _seed_session_and_source_and_target(engine)
        result = evaluator.evaluate(_all_pass_inputs())
        pass_checks = [c for c in result.checks if c.status == PREFLIGHT_STATUS_PASS]
        for c in pass_checks:
            # No reason_code required for pass; this is the contract.
            assert c.reason_code is None


# ---------------------------------------------------------------------------
# Bug B3: the evaluator runs its own network/storage probes when the caller
# (in production, the operator's Run Meeting screen) submits None instead of
# depending on a caller that never actually probed. Field evidence, native
# beta candidate #17: both checks showed "not probed" forever because no
# real caller ever ran one.
# ---------------------------------------------------------------------------


class TestNetworkStorageSelfProbing:
    def _evaluator_with_probes(
        self,
        engine: Engine,
        *,
        network_probe=None,
        storage_probe=None,
    ) -> PreflightEvaluator:
        @contextmanager
        def factory() -> Iterator[Session]:
            with Session(bind=engine) as session:
                yield session

        return PreflightEvaluator(
            session_factory=factory,
            source_probe=lambda source: (
                True,
                f"Source {source.live_source_id!r} delivered media.",
            ),
            network_probe=network_probe,
            storage_probe=storage_probe,
        )

    def test_network_probe_configured_property(self, engine: Engine) -> None:
        evaluator = self._evaluator_with_probes(engine, network_probe=lambda: (True, None))
        assert evaluator.network_probe_configured is True
        assert evaluator.storage_probe_configured is False

    def test_storage_probe_configured_property(self, engine: Engine) -> None:
        evaluator = self._evaluator_with_probes(engine, storage_probe=lambda: (1, None))
        assert evaluator.storage_probe_configured is True
        assert evaluator.network_probe_configured is False

    def test_network_probe_fills_in_when_input_is_none(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(
            engine, network_probe=lambda: (True, "Reached 1.1.1.1:443 over the internet.")
        )
        inputs = _all_pass_inputs().model_copy(update={"network_reachable": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_PASS
        assert check.message == "Reached 1.1.1.1:443 over the internet."
        assert result.ready is True

    def test_network_probe_negative_result_fails_with_probe_message(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(
            engine,
            network_probe=lambda: (False, "Could not reach the internet (tried 1.1.1.1:443)."),
        )
        inputs = _all_pass_inputs().model_copy(update={"network_reachable": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NETWORK_UNREACHABLE
        assert check.message == "Could not reach the internet (tried 1.1.1.1:443)."

    def test_network_probe_exception_falls_back_to_not_probed(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)

        def _boom() -> tuple[bool, str | None]:
            raise RuntimeError("socket exploded")

        evaluator = self._evaluator_with_probes(engine, network_probe=_boom)
        inputs = _all_pass_inputs().model_copy(update={"network_reachable": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_NETWORK_NOT_PROBED

    def test_explicit_network_input_wins_over_probe(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        calls: list[None] = []

        def _tracking_probe() -> tuple[bool, str | None]:
            calls.append(None)
            return False, "should never be used"

        evaluator = self._evaluator_with_probes(engine, network_probe=_tracking_probe)
        # network_reachable=True is explicit (from _all_pass_inputs); the probe must not run.
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_NETWORK]
        assert check.status == PREFLIGHT_STATUS_PASS
        assert calls == []

    def test_storage_probe_fills_in_when_input_is_none(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(
            engine, storage_probe=lambda: (200 * (1024**3), None)
        )
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_PASS
        assert result.ready is True

    def test_storage_probe_insufficient_space_fails(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(engine, storage_probe=lambda: (1024, None))
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_STORAGE_INSUFFICIENT

    def test_storage_probe_none_result_falls_back_to_not_probed(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(
            engine, storage_probe=lambda: (None, "disk unreadable")
        )
        inputs = _all_pass_inputs().model_copy(update={"storage_free_bytes": None})
        result = evaluator.evaluate(inputs)
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_FAIL
        assert check.reason_code == REASON_STORAGE_NOT_PROBED
        assert check.message == "disk unreadable"

    def test_explicit_storage_input_wins_over_probe(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        calls: list[None] = []

        def _tracking_probe() -> tuple[int | None, str | None]:
            calls.append(None)
            return None, "should never be used"

        evaluator = self._evaluator_with_probes(engine, storage_probe=_tracking_probe)
        result = evaluator.evaluate(_all_pass_inputs())
        check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_STORAGE]
        assert check.status == PREFLIGHT_STATUS_PASS
        assert calls == []

    def test_override_probes_at_evaluate_time(self, engine: Engine) -> None:
        _seed_session_and_source_and_target(engine)
        evaluator = self._evaluator_with_probes(engine)
        inputs = _all_pass_inputs().model_copy(
            update={"network_reachable": None, "storage_free_bytes": None}
        )
        result = evaluator.evaluate(
            inputs,
            network_probe_override=lambda: (True, "override reached"),
            storage_probe_override=lambda: (200 * (1024**3), None),
        )
        checks = {c.name: c for c in result.checks}
        assert checks[PREFLIGHT_CHECK_NETWORK].status == PREFLIGHT_STATUS_PASS
        assert checks[PREFLIGHT_CHECK_STORAGE].status == PREFLIGHT_STATUS_PASS
        assert result.ready is True

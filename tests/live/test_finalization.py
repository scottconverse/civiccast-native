# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Recording-finalization tests (SQLite path).

Sprint 0.4 Slice 1 Commit 7. The finalization contract under test:

* Happy path: an ``ending`` session with a recording_uri lands an
  asset row at state ``recorded`` + a ``session.finalized`` event +
  the LiveSession advances to ``recorded``. All three in one
  transaction.
* Idempotency: a duplicate ``finalize_recording`` call against an
  already-``recorded`` session returns the existing asset + event
  with ``idempotent=True``; no new rows are created.
* Wrong-state error: finalizing an ``idle`` / ``preflight`` /
  ``on_air`` session raises ``LiveSessionStateError`` with the
  observed state recorded on the exception.
* Missing session: finalizing a non-existent ``live_session_id``
  raises ``LiveSessionNotFoundError``.
* Asset-id collision: a pre-existing Asset with the same id but a
  different (or NULL) ``source_live_session_id`` surfaces as
  :class:`LiveRecordingAssetCollisionError` -- not silently overwriting.
* Asset shape: the returned ``StaffAssetRow`` carries
  ``source_live_session_id``, ``state == 'recorded'``, and a local
  filesystem path in ``file_path`` even when the event input is a
  ``file://`` URI (D3: registration-time normalization).
* Payload persistence: the event row's ``payload_json`` round-trips
  through ``json.loads`` to the input shape.

Real-Postgres concurrency proof (threading.Barrier race) lives in
:mod:`tests.live.test_real_postgres`; this module exercises the
single-session control-flow against SQLite.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Importing the live + schedule modules registers their SA classes
# against Base.metadata before create_all runs. The schedule import is
# load-bearing on SQLite -- it owns the connect-time ATTACH ':memory:'
# AS civiccast hook.
import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live import (
    LIVE_SESSION_EVENT_FINALIZED,
    LIVE_SESSION_STATE_ENDING,
    LIVE_SESSION_STATE_IDLE,
    LIVE_SESSION_STATE_ON_AIR,
    LIVE_SESSION_STATE_PREFLIGHT,
    LIVE_SESSION_STATE_RECORDED,
    LiveRecordingAssetCollisionError,
    LiveRecordingFinalizer,
    LiveSession,
    LiveSessionEvent,
    LiveSessionNotFoundError,
    LiveSessionStateError,
)
from civiccast.schedule.models import ASSET_STATE_RECORDED, ASSET_STATE_VALIDATED, Asset

# ---------------------------------------------------------------------------
# Fixtures + helpers
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
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    """Context-managed session factory bound to the per-test engine."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def finalizer(session_factory) -> LiveRecordingFinalizer:  # type: ignore[no-untyped-def]
    return LiveRecordingFinalizer(session_factory=session_factory)


def _seed_session_in_state(
    engine: Engine,
    *,
    live_session_id: str = "council-2026-05-15",
    state: str = LIVE_SESSION_STATE_ENDING,
    title: str = "City Council Meeting",
) -> None:
    """Insert a LiveSession row directly at the requested state.

    Lets a test pin a particular starting state without going through
    all the store-layer transitions in sequence; the store-layer
    tests already cover the transition path.
    """
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id=live_session_id,
                channel_id="gov-ch12",
                title=title,
                state=state,
            )
        )
        session.commit()


def _seed_upload_asset(
    engine: Engine,
    *,
    asset_id: str,
    source_live_session_id: str | None = None,
) -> None:
    """Pre-seed an Asset row (upload path) to set up collision tests."""
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title=f"Upload {asset_id}",
                state=ASSET_STATE_VALIDATED,
                source_live_session_id=source_live_session_id,
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Locks: a session in ``ending`` finalizes cleanly with all three
    writes landing in one transaction."""

    def test_returns_asset_event_and_idempotent_false(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/civiccast/recordings/council-2026-05-15.mkv",
            duration_seconds=3720,
        )
        assert result.idempotent is False
        assert result.asset.state == ASSET_STATE_RECORDED
        assert result.asset.asset_id == "council-2026-05-15"
        assert result.asset.source_live_session_id == "council-2026-05-15"
        assert result.asset.file_path == str(
            Path("/srv/civiccast/recordings/council-2026-05-15.mkv")
        )
        assert result.asset.duration_seconds == 3720
        assert result.event.event_type == LIVE_SESSION_EVENT_FINALIZED
        assert result.event.event_seq == 1
        assert result.event.live_session_id == "council-2026-05-15"

    def test_non_local_recording_uri_stores_null_file_path_and_preserves_uri(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        """FALSIFICATION (D3 reviewer-added): a NON-local recording URI (s3://,
        http://) cannot be normalized to a filesystem path. The honest
        registration is file_path=None (assets.file_path is nullable; a None
        reads as not-locally-present, exactly like rc16's broken raw-URI rows
        effectively did) while the original URI stays fully preserved in the
        finalization event payload for relink/diagnostics. Guards the
        `local_path is not None` branch, which no other test exercises."""
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="s3://bucket/recordings/council-2026-05-15.mkv",
        )
        assert result.asset.file_path is None
        assert result.event.payload_json is not None
        payload = json.loads(result.event.payload_json)
        assert payload["recording_uri"] == "s3://bucket/recordings/council-2026-05-15.mkv"

    def test_live_session_advances_to_recorded(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/x.mkv",
        )
        with Session(bind=engine) as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == "council-2026-05-15")
            ).scalar_one()
            assert row.state == LIVE_SESSION_STATE_RECORDED

    def test_event_payload_roundtrips_through_json(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        marker = datetime(2026, 5, 15, 21, 30, 0, tzinfo=UTC)
        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/x.mkv",
            duration_seconds=1800,
            finalized_at=marker,
        )
        assert result.event.payload_json is not None
        payload = json.loads(result.event.payload_json)
        assert payload["recording_uri"] == "file:///srv/recordings/x.mkv"
        assert payload["duration_seconds"] == 1800
        assert payload["finalized_at"] == marker.isoformat()

    def test_asset_title_inherits_from_live_session(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(
            engine,
            state=LIVE_SESSION_STATE_ENDING,
            title="Special Workshop Session",
        )
        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/x.mkv",
        )
        assert result.asset.title == "Special Workshop Session"

    def test_existing_local_recording_persists_trim_without_packaging_in_transaction(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
        tmp_path,
    ) -> None:
        recording = tmp_path / "recording.mp4"
        recording.write_bytes(b"fake video")

        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)

        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri=recording.as_uri(),
            duration_seconds=120,
            trim_in_seconds=10.5,
            trim_out_seconds=42.25,
        )

        assert not (tmp_path / "council-2026-05-15-hls").exists()
        assert result.asset.manifest_url is None
        assert result.asset.trim_in_seconds == 10.5
        assert result.asset.trim_out_seconds == 42.25

    @pytest.mark.parametrize(
        ("trim_in", "trim_out", "duration"),
        [
            (-1.0, 10.0, 120),
            (10.0, 10.0, 120),
            (20.0, 10.0, 120),
            (0.0, 121.0, 120),
        ],
    )
    def test_invalid_trim_values_are_rejected_before_asset_write(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
        trim_in: float,
        trim_out: float,
        duration: int,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)

        with pytest.raises(ValueError):
            finalizer.finalize_recording(
                "council-2026-05-15",
                recording_uri="file:///srv/recordings/x.mkv",
                duration_seconds=duration,
                trim_in_seconds=trim_in,
                trim_out_seconds=trim_out,
            )

        with Session(bind=engine) as session:
            assert session.execute(select(Asset)).all() == []

    def test_finalized_at_defaults_to_now_utc(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        before = datetime.now(UTC).replace(tzinfo=None)
        result = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/x.mkv",
        )
        after = datetime.now(UTC).replace(tzinfo=None)
        assert result.event.payload_json is not None
        payload = json.loads(result.event.payload_json)
        finalized_at = datetime.fromisoformat(payload["finalized_at"])
        finalized_at_naive = finalized_at.replace(tzinfo=None)
        assert before <= finalized_at_naive <= after


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Locks: a duplicate finalize against an already-``recorded`` session
    returns the existing rows with ``idempotent=True`` and creates no new
    rows."""

    def test_duplicate_finalize_returns_idempotent_true(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        first = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/first.mkv",
        )
        second = finalizer.finalize_recording(
            "council-2026-05-15",
            recording_uri="file:///srv/recordings/second.mkv",  # ignored on idempotent path
        )
        assert first.idempotent is False
        assert second.idempotent is True
        # Idempotent call returns the FIRST finalize's payload, not the
        # caller's retry args.
        assert second.event.event_seq == first.event.event_seq
        assert second.asset.file_path == str(Path("/srv/recordings/first.mkv"))

    def test_duplicate_finalize_does_not_create_extra_event_or_asset(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///a.mkv")
        finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///b.mkv")
        with Session(bind=engine) as session:
            event_count = session.execute(
                select(LiveSessionEvent).where(
                    LiveSessionEvent.live_session_id == "council-2026-05-15"
                )
            ).all()
            asset_count = session.execute(
                select(Asset).where(Asset.source_live_session_id == "council-2026-05-15")
            ).all()
        assert len(event_count) == 1
        assert len(asset_count) == 1


# ---------------------------------------------------------------------------
# Wrong-state errors
# ---------------------------------------------------------------------------


class TestWrongStateError:
    """Locks: finalize from any state other than ``ending`` (and not
    already ``recorded``) raises ``LiveSessionStateError``."""

    @pytest.mark.parametrize(
        "starting_state",
        [
            LIVE_SESSION_STATE_IDLE,
            LIVE_SESSION_STATE_PREFLIGHT,
            LIVE_SESSION_STATE_ON_AIR,
        ],
    )
    def test_raises_state_error_with_current_state_recorded(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
        starting_state: str,
    ) -> None:
        _seed_session_in_state(engine, state=starting_state)
        with pytest.raises(LiveSessionStateError) as exc_info:
            finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///x.mkv")
        assert exc_info.value.current_state == starting_state
        assert exc_info.value.attempted_transition == "finalize_recording"
        assert exc_info.value.live_session_id == "council-2026-05-15"

    def test_no_event_or_asset_written_on_state_error(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_IDLE)
        with pytest.raises(LiveSessionStateError):
            finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///x.mkv")
        with Session(bind=engine) as session:
            events = session.execute(select(LiveSessionEvent)).all()
            assets = session.execute(
                select(Asset).where(Asset.source_live_session_id.is_not(None))
            ).all()
        assert events == []
        assert assets == []


# ---------------------------------------------------------------------------
# Missing session
# ---------------------------------------------------------------------------


class TestMissingSession:
    """Locks: finalize against a missing live_session_id raises
    ``LiveSessionNotFoundError``."""

    def test_raises_not_found(
        self,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        with pytest.raises(LiveSessionNotFoundError) as exc_info:
            finalizer.finalize_recording("does-not-exist", recording_uri="file:///x.mkv")
        assert exc_info.value.live_session_id == "does-not-exist"


# ---------------------------------------------------------------------------
# Asset-id collision
# ---------------------------------------------------------------------------


class TestAssetIdCollision:
    """Locks: a pre-existing asset with the same id but no
    ``source_live_session_id`` link surfaces as
    ``LiveRecordingAssetCollisionError`` -- never silently overwrites."""

    def test_collision_with_non_live_asset_raises(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        # An operator previously uploaded an asset with the same slug;
        # that asset has source_live_session_id = NULL.
        _seed_upload_asset(engine, asset_id="council-2026-05-15")
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        with pytest.raises(LiveRecordingAssetCollisionError) as exc_info:
            finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///x.mkv")
        assert exc_info.value.live_session_id == "council-2026-05-15"
        assert exc_info.value.asset_id == "council-2026-05-15"

    def test_collision_leaves_live_session_in_ending(
        self,
        engine: Engine,
        finalizer: LiveRecordingFinalizer,
    ) -> None:
        _seed_upload_asset(engine, asset_id="council-2026-05-15")
        _seed_session_in_state(engine, state=LIVE_SESSION_STATE_ENDING)
        with pytest.raises(LiveRecordingAssetCollisionError):
            finalizer.finalize_recording("council-2026-05-15", recording_uri="file:///x.mkv")
        with Session(bind=engine) as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == "council-2026-05-15")
            ).scalar_one()
            # State must NOT have advanced -- failed finalization is atomic.
            assert row.state == LIVE_SESSION_STATE_ENDING
            # And no event row should have been written.
            events = session.execute(select(LiveSessionEvent)).all()
            assert events == []

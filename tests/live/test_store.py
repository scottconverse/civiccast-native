# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-session store + state-machine transition tests (SQLite path).

Sprint 0.4 Slice 1 Commit 4. The store contract under test:

* ``create_session`` inserts at ``idle``; duplicate id raises
  ``LiveSessionAlreadyExistsError``.
* ``get_session`` returns ``None`` for unknown ids.
* The four forward transitions advance state and stamp the matching
  timestamp where applicable.
* Every illegal transition raises ``LiveSessionStateError`` with the
  current state + attempted transition recorded on the exception.
* A transition against a missing session raises
  ``LiveSessionNotFoundError``.

Real-Postgres concurrency proof of the conditional-UPDATE pattern lives
in :mod:`tests.live.test_real_postgres`; this module exercises the
single-session control-flow against the SQLite test path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# Importing the live + schedule modules registers their SA classes
# against Base.metadata before create_all runs. The schedule import is
# load-bearing on SQLite: it owns the connect-time ATTACH ':memory:' AS
# civiccast hook that lets the schema-qualified CREATE TABLE
# civiccast.live_sessions resolve.
import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live import (
    LIVE_SESSION_STATE_ENDING,
    LIVE_SESSION_STATE_IDLE,
    LIVE_SESSION_STATE_ON_AIR,
    LIVE_SESSION_STATE_PREFLIGHT,
    LIVE_SESSION_STATE_RECORDED,
    SOURCE_TYPE_NDI,
    SOURCE_TYPE_RTMP,
    LiveRelayConfigAlreadyExistsError,
    LiveRelayConfigCreate,
    LiveRelayConfigNotFoundError,
    LiveRelayConfigStore,
    LiveRelayHealthUpdate,
    LiveSessionAlreadyExistsError,
    LiveSessionCreate,
    LiveSessionNotFoundError,
    LiveSessionStateError,
    LiveSessionStore,
    LiveSourceAlreadyExistsError,
    LiveSourceCreate,
    LiveSourceStore,
    RecordingTargetAlreadyExistsError,
    RecordingTargetCreate,
    RecordingTargetStore,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Per-test ephemeral SQLite engine bound to ``Base.metadata``.

    Mirrors :func:`tests.live.test_models.engine` so the store layer
    exercises the same SQLite path the model-layer tests already do.
    """
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> LiveSessionStore:
    """A LiveSessionStore bound to the per-test engine via a context-
    managed session factory."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return LiveSessionStore(session_factory=factory)


def _payload(live_session_id: str = "council-2026-05-15") -> LiveSessionCreate:
    return LiveSessionCreate(
        live_session_id=live_session_id,
        channel_id="gov-ch12",
        title="City Council Meeting",
    )


def _strip_tz(value: datetime | None) -> datetime | None:
    """Normalize tz-aware/naive datetimes for SQLite assertions.

    SQLite's DateTime column has no native tzinfo representation, so a
    timezone-aware Python ``datetime`` is read back as naive. Real
    Postgres in :mod:`tests.live.test_real_postgres` preserves the tz.
    Tests here strip tzinfo so the SQLite path doesn't false-negative
    on a comparison that the production-path test will pin separately.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreateSession:
    """Locks: ``create_session`` inserts at ``idle`` and rejects duplicates."""

    def test_creates_at_idle_state(self, store: LiveSessionStore) -> None:
        response = store.create_session(_payload())
        assert response.live_session_id == "council-2026-05-15"
        assert response.state == LIVE_SESSION_STATE_IDLE
        assert response.started_at is None
        assert response.ended_at is None
        assert response.created_at is not None

    def test_duplicate_id_raises_already_exists(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        with pytest.raises(LiveSessionAlreadyExistsError) as exc_info:
            store.create_session(_payload())
        assert exc_info.value.live_session_id == "council-2026-05-15"


class TestGetSession:
    """Locks: ``get_session`` returns ``None`` for unknown ids, the
    canonical projection otherwise."""

    def test_missing_returns_none(self, store: LiveSessionStore) -> None:
        assert store.get_session("does-not-exist") is None

    def test_existing_returns_response(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        response = store.get_session("council-2026-05-15")
        assert response is not None
        assert response.state == LIVE_SESSION_STATE_IDLE


# ---------------------------------------------------------------------------
# Forward transitions (happy paths)
# ---------------------------------------------------------------------------


class TestForwardTransitions:
    """Locks: each forward transition advances state and, where the
    contract calls for it, stamps the matching timestamp."""

    def test_start_preflight_advances_idle_to_preflight(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        response = store.start_preflight("council-2026-05-15")
        assert response.state == LIVE_SESSION_STATE_PREFLIGHT
        assert response.started_at is None  # only go_on_air stamps this

    def test_go_on_air_advances_preflight_to_on_air_and_stamps_started_at(
        self, store: LiveSessionStore
    ) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        marker = datetime(2026, 5, 15, 19, 0, 0, tzinfo=UTC)
        response = store.go_on_air("council-2026-05-15", now=marker)
        assert response.state == LIVE_SESSION_STATE_ON_AIR
        # SQLite strips tzinfo on DateTime read-back; the Postgres path in
        # tests/live/test_real_postgres.py covers timezone-aware round-trip.
        assert _strip_tz(response.started_at) == _strip_tz(marker)

    def test_end_broadcast_advances_on_air_to_ending_and_stamps_ended_at(
        self, store: LiveSessionStore
    ) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")
        marker = datetime(2026, 5, 15, 21, 30, 0, tzinfo=UTC)
        response = store.end_broadcast("council-2026-05-15", now=marker)
        assert response.state == LIVE_SESSION_STATE_ENDING
        assert _strip_tz(response.ended_at) == _strip_tz(marker)

    def test_mark_recorded_advances_ending_to_recorded(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")
        store.end_broadcast("council-2026-05-15")
        response = store.mark_recorded("council-2026-05-15")
        assert response.state == LIVE_SESSION_STATE_RECORDED

    def test_full_lifecycle_idle_to_recorded(self, store: LiveSessionStore) -> None:
        """End-to-end happy path: idle -> preflight -> on_air -> ending -> recorded."""
        store.create_session(_payload())
        assert store.get_session("council-2026-05-15").state == LIVE_SESSION_STATE_IDLE
        store.start_preflight("council-2026-05-15")
        assert store.get_session("council-2026-05-15").state == LIVE_SESSION_STATE_PREFLIGHT
        store.go_on_air("council-2026-05-15")
        assert store.get_session("council-2026-05-15").state == LIVE_SESSION_STATE_ON_AIR
        store.end_broadcast("council-2026-05-15")
        assert store.get_session("council-2026-05-15").state == LIVE_SESSION_STATE_ENDING
        store.mark_recorded("council-2026-05-15")
        assert store.get_session("council-2026-05-15").state == LIVE_SESSION_STATE_RECORDED


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


class TestIllegalTransitionsFromIdle:
    """idle is the entry state. Only ``start_preflight`` is legal from idle."""

    def test_go_on_air_from_idle_raises(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.go_on_air("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_IDLE
        assert exc_info.value.attempted_transition == "go_on_air"

    def test_end_broadcast_from_idle_raises(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.end_broadcast("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_IDLE

    def test_mark_recorded_from_idle_raises(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.mark_recorded("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_IDLE


class TestIllegalTransitionsFromPreflight:
    """preflight permits only ``go_on_air``. All other transitions raise."""

    def _advance_to_preflight(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")

    def test_start_preflight_again_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_preflight(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.start_preflight("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_PREFLIGHT

    def test_end_broadcast_from_preflight_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_preflight(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.end_broadcast("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_PREFLIGHT

    def test_mark_recorded_from_preflight_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_preflight(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.mark_recorded("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_PREFLIGHT


class TestIllegalTransitionsFromOnAir:
    """on_air permits only ``end_broadcast``."""

    def _advance_to_on_air(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")

    def test_start_preflight_from_on_air_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_on_air(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.start_preflight("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ON_AIR

    def test_go_on_air_again_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_on_air(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.go_on_air("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ON_AIR

    def test_mark_recorded_from_on_air_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_on_air(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.mark_recorded("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ON_AIR


class TestIllegalTransitionsFromEnding:
    """ending permits only ``mark_recorded``."""

    def _advance_to_ending(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")
        store.end_broadcast("council-2026-05-15")

    def test_start_preflight_from_ending_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_ending(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.start_preflight("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ENDING

    def test_go_on_air_from_ending_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_ending(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.go_on_air("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ENDING

    def test_end_broadcast_again_raises(self, store: LiveSessionStore) -> None:
        self._advance_to_ending(store)
        with pytest.raises(LiveSessionStateError) as exc_info:
            store.end_broadcast("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_ENDING


class TestIllegalTransitionsFromRecorded:
    """recorded is terminal. Every transition raises."""

    def _advance_to_recorded(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")
        store.end_broadcast("council-2026-05-15")
        store.mark_recorded("council-2026-05-15")

    @pytest.mark.parametrize(
        "method_name",
        ["start_preflight", "go_on_air", "end_broadcast", "mark_recorded"],
    )
    def test_every_transition_from_recorded_raises(
        self,
        store: LiveSessionStore,
        method_name: str,
    ) -> None:
        self._advance_to_recorded(store)
        method = getattr(store, method_name)
        with pytest.raises(LiveSessionStateError) as exc_info:
            method("council-2026-05-15")
        assert exc_info.value.current_state == LIVE_SESSION_STATE_RECORDED
        assert exc_info.value.attempted_transition == method_name


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


class TestTransitionOnMissingSession:
    """Every transition against a missing session raises NotFoundError,
    not StateError. The store distinguishes the two by re-querying after
    the predicate UPDATE matches zero rows."""

    @pytest.mark.parametrize(
        "method_name",
        ["start_preflight", "go_on_air", "end_broadcast", "mark_recorded"],
    )
    def test_missing_session_raises_not_found(
        self,
        store: LiveSessionStore,
        method_name: str,
    ) -> None:
        method = getattr(store, method_name)
        with pytest.raises(LiveSessionNotFoundError) as exc_info:
            method("never-existed")
        assert exc_info.value.live_session_id == "never-existed"


# ---------------------------------------------------------------------------
# Defaulted ``now`` injection
# ---------------------------------------------------------------------------


class TestDefaultedNow:
    """When ``now`` is omitted, ``go_on_air`` and ``end_broadcast`` stamp
    a real ``datetime.now(UTC)`` rather than leaving the column NULL."""

    def test_go_on_air_default_now_populates_started_at(self, store: LiveSessionStore) -> None:
        before = _strip_tz(datetime.now(UTC))
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        response = store.go_on_air("council-2026-05-15")
        after = _strip_tz(datetime.now(UTC))
        got = _strip_tz(response.started_at)
        assert got is not None
        assert before <= got <= after

    def test_end_broadcast_default_now_populates_ended_at(self, store: LiveSessionStore) -> None:
        store.create_session(_payload())
        store.start_preflight("council-2026-05-15")
        store.go_on_air("council-2026-05-15")
        before = _strip_tz(datetime.now(UTC))
        response = store.end_broadcast("council-2026-05-15")
        after = _strip_tz(datetime.now(UTC))
        got = _strip_tz(response.ended_at)
        assert got is not None
        assert before <= got <= after


# ---------------------------------------------------------------------------
# LiveSourceStore (Slice 1 Commit 6)
# ---------------------------------------------------------------------------


@pytest.fixture
def source_store(engine: Engine) -> LiveSourceStore:
    """A LiveSourceStore bound to the per-test engine."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return LiveSourceStore(session_factory=factory)


def _source_payload(
    live_source_id: str = "rtmp-cam-01",
    *,
    channel_id: str = "gov-ch12",
    source_type: str = SOURCE_TYPE_RTMP,
    endpoint_url: str = "rtmp://encoder.local/live/stream",
    credentials_handle: str | None = None,
) -> LiveSourceCreate:
    return LiveSourceCreate(
        live_source_id=live_source_id,
        channel_id=channel_id,
        name=f"{live_source_id} (test)",
        source_type=source_type,
        endpoint_url=endpoint_url,
        credentials_handle=credentials_handle,
    )


class TestLiveSourceStoreCreate:
    """Locks: ``create`` inserts a row and rejects duplicate ids."""

    def test_creates_and_returns_canonical_response(self, source_store: LiveSourceStore) -> None:
        response = source_store.create(_source_payload())
        assert response.live_source_id == "rtmp-cam-01"
        assert response.channel_id == "gov-ch12"
        assert response.source_type == SOURCE_TYPE_RTMP
        assert response.created_at is not None

    def test_duplicate_id_raises_already_exists(self, source_store: LiveSourceStore) -> None:
        source_store.create(_source_payload())
        with pytest.raises(LiveSourceAlreadyExistsError) as exc_info:
            source_store.create(_source_payload())
        assert exc_info.value.live_source_id == "rtmp-cam-01"

    def test_url_coerced_to_string_at_db_layer(self, source_store: LiveSourceStore) -> None:
        # ``endpoint_url`` is ``HttpUrl | str`` at the Pydantic surface. The
        # store coerces to ``str`` so the DB column is a plain string; this
        # test pins the coercion against an HTTPS URL (which Pydantic
        # parses as an HttpUrl) to prove no Pydantic Url repr leaks into
        # the response.
        response = source_store.create(
            _source_payload(
                live_source_id="https-cam-01",
                endpoint_url="https://encoder.example/stream.m3u8",
            )
        )
        assert isinstance(response.endpoint_url, str)
        assert response.endpoint_url.startswith("https://")


class TestLiveSourceStoreGet:
    """Locks: ``get`` returns ``None`` for unknown ids, the projection otherwise."""

    def test_missing_returns_none(self, source_store: LiveSourceStore) -> None:
        assert source_store.get("does-not-exist") is None

    def test_existing_returns_response(self, source_store: LiveSourceStore) -> None:
        source_store.create(_source_payload())
        response = source_store.get("rtmp-cam-01")
        assert response is not None
        assert response.source_type == SOURCE_TYPE_RTMP


class TestLiveSourceStoreList:
    """Locks: ``list`` returns every row, optionally filtered by channel,
    ordered by ``created_at`` ascending then id."""

    def test_empty_store_returns_empty_list(self, source_store: LiveSourceStore) -> None:
        assert source_store.list() == []

    def test_no_filter_returns_every_row(self, source_store: LiveSourceStore) -> None:
        source_store.create(_source_payload(live_source_id="rtmp-cam-01"))
        source_store.create(
            _source_payload(
                live_source_id="ndi-feed-01",
                source_type=SOURCE_TYPE_NDI,
                endpoint_url="ndi://OBS_STUDIO",
            )
        )
        ids = {row.live_source_id for row in source_store.list()}
        assert ids == {"rtmp-cam-01", "ndi-feed-01"}

    def test_channel_filter_includes_only_matching_rows(
        self, source_store: LiveSourceStore
    ) -> None:
        source_store.create(_source_payload(live_source_id="cam-a", channel_id="gov-ch12"))
        source_store.create(_source_payload(live_source_id="cam-b", channel_id="gov-ch14"))
        result = source_store.list(channel_id="gov-ch12")
        assert [row.live_source_id for row in result] == ["cam-a"]


# ---------------------------------------------------------------------------
# LiveRelayConfigStore (v1.8.7)
# ---------------------------------------------------------------------------


@pytest.fixture
def relay_store(engine: Engine) -> LiveRelayConfigStore:
    """A LiveRelayConfigStore bound to the per-test engine."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return LiveRelayConfigStore(session_factory=factory)


def _relay_payload(
    relay_config_id: str = "project-relay",
    *,
    channel_id: str = "gov-ch12",
    mode: str = "cloud_rtmp_relay",
    endpoint_url: str = "rtmps://relay.example/live/gov",
    provider: str | None = "project-hosted",
    enabled: bool = True,
) -> LiveRelayConfigCreate:
    return LiveRelayConfigCreate(
        relay_config_id=relay_config_id,
        channel_id=channel_id,
        name=f"{relay_config_id} (test)",
        mode=mode,  # type: ignore[arg-type]
        endpoint_url=endpoint_url,
        provider=provider,
        enabled=enabled,
    )


class TestLiveRelayConfigStoreCreate:
    """Locks: ``create`` inserts optional relay config rows."""

    def test_creates_and_returns_canonical_response(
        self, relay_store: LiveRelayConfigStore
    ) -> None:
        response = relay_store.create(_relay_payload())
        assert response.relay_config_id == "project-relay"
        assert response.mode == "cloud_rtmp_relay"
        assert response.health_state == "not_configured"
        assert response.enabled is True
        assert response.created_at is not None

    def test_duplicate_id_raises_already_exists(self, relay_store: LiveRelayConfigStore) -> None:
        relay_store.create(_relay_payload())
        with pytest.raises(LiveRelayConfigAlreadyExistsError) as exc_info:
            relay_store.create(_relay_payload())
        assert exc_info.value.relay_config_id == "project-relay"


class TestLiveRelayConfigStoreList:
    """Locks: ``list`` supports channel and enabled filters."""

    def test_empty_store_returns_empty_list(self, relay_store: LiveRelayConfigStore) -> None:
        assert relay_store.list() == []

    def test_no_filter_returns_every_row(self, relay_store: LiveRelayConfigStore) -> None:
        relay_store.create(_relay_payload(relay_config_id="project-relay"))
        relay_store.create(
            _relay_payload(
                relay_config_id="youtube-backup",
                mode="direct_syndication",
                endpoint_url="rtmps://a.rtmps.youtube.example/live2/key",
                provider="youtube-live",
            )
        )
        ids = {row.relay_config_id for row in relay_store.list()}
        assert ids == {"project-relay", "youtube-backup"}

    def test_channel_and_enabled_filters(self, relay_store: LiveRelayConfigStore) -> None:
        relay_store.create(_relay_payload(relay_config_id="active-gov"))
        relay_store.create(
            _relay_payload(
                relay_config_id="disabled-gov",
                channel_id="gov-ch12",
                enabled=False,
            )
        )
        relay_store.create(_relay_payload(relay_config_id="active-school", channel_id="schools"))

        result = relay_store.list(channel_id="gov-ch12", enabled=True)

        assert [row.relay_config_id for row in result] == ["active-gov"]


class TestLiveRelayConfigStoreHealth:
    """Locks: station probes can update operator-visible relay health."""

    def test_update_health_changes_state_and_heartbeat(
        self, relay_store: LiveRelayConfigStore
    ) -> None:
        relay_store.create(_relay_payload())
        now = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)

        response = relay_store.update_health(
            "project-relay",
            LiveRelayHealthUpdate(
                health_state="ready",
                last_heartbeat_at=now,
                notes="Probe OK",
            ),
        )

        assert response.health_state == "ready"
        assert response.last_heartbeat_at is not None
        assert response.last_heartbeat_at.replace(tzinfo=UTC) == now
        assert response.notes == "Probe OK"

    def test_update_health_missing_raises_not_found(
        self, relay_store: LiveRelayConfigStore
    ) -> None:
        with pytest.raises(LiveRelayConfigNotFoundError) as exc_info:
            relay_store.update_health(
                "missing",
                LiveRelayHealthUpdate(health_state="offline"),
            )
        assert exc_info.value.relay_config_id == "missing"


# ---------------------------------------------------------------------------
# RecordingTargetStore (Slice 1 Commit 6)
# ---------------------------------------------------------------------------


@pytest.fixture
def target_store(engine: Engine) -> RecordingTargetStore:
    """A RecordingTargetStore bound to the per-test engine."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return RecordingTargetStore(session_factory=factory)


def _target_payload(
    recording_target_id: str = "fs-primary",
    *,
    target_uri: str = "file:///srv/civiccast/recordings",
) -> RecordingTargetCreate:
    return RecordingTargetCreate(
        recording_target_id=recording_target_id,
        name=f"{recording_target_id} (test)",
        target_uri=target_uri,
    )


class TestRecordingTargetStoreCreate:
    """Locks: ``create`` inserts a row and rejects duplicate ids."""

    def test_creates_and_returns_canonical_response(
        self, target_store: RecordingTargetStore
    ) -> None:
        response = target_store.create(_target_payload())
        assert response.recording_target_id == "fs-primary"
        assert response.target_uri == "file:///srv/civiccast/recordings"
        assert response.created_at is not None

    def test_duplicate_id_raises_already_exists(self, target_store: RecordingTargetStore) -> None:
        target_store.create(_target_payload())
        with pytest.raises(RecordingTargetAlreadyExistsError) as exc_info:
            target_store.create(_target_payload())
        assert exc_info.value.recording_target_id == "fs-primary"


class TestRecordingTargetStoreGet:
    """Locks: ``get`` returns ``None`` for unknown ids, the projection otherwise."""

    def test_missing_returns_none(self, target_store: RecordingTargetStore) -> None:
        assert target_store.get("does-not-exist") is None

    def test_existing_returns_response(self, target_store: RecordingTargetStore) -> None:
        target_store.create(_target_payload())
        response = target_store.get("fs-primary")
        assert response is not None
        assert response.target_uri == "file:///srv/civiccast/recordings"


class TestRecordingTargetStoreList:
    """Locks: ``list`` returns every row."""

    def test_empty_store_returns_empty_list(self, target_store: RecordingTargetStore) -> None:
        assert target_store.list() == []

    def test_returns_every_row(self, target_store: RecordingTargetStore) -> None:
        target_store.create(_target_payload(recording_target_id="fs-primary"))
        target_store.create(
            _target_payload(
                recording_target_id="fs-archive",
                target_uri="file:///srv/civiccast/archive/2026/",
            )
        )
        ids = {row.recording_target_id for row in target_store.list()}
        assert ids == {"fs-primary", "fs-archive"}

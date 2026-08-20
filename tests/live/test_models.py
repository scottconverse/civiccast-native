# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pydantic + SA shape tests for the v0.4 live-broadcast spine.

Sprint 0.4 Slice 1 Commit 3. Schema-only tests: constant tuples,
Pydantic accept/reject behavior, SA __table_args__ CheckConstraint
strings. No store-layer behavior, no router behavior, no migration
runs (those live in tests/live/test_real_postgres.py).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.models import (
    _LIVE_SESSION_STATES,
    _SOURCE_TYPES,
    LIVE_SESSION_STATE_ENDING,
    LIVE_SESSION_STATE_IDLE,
    LIVE_SESSION_STATE_ON_AIR,
    LIVE_SESSION_STATE_PREFLIGHT,
    LIVE_SESSION_STATE_RECORDED,
    SOURCE_TYPE_NDI,
    SOURCE_TYPE_RTMP,
    SOURCE_TYPE_RTSP,
    SOURCE_TYPE_SRT,
    LiveRelayConfig,
    LiveRelayConfigCreate,
    LiveRelayHealthUpdate,
    LiveSession,
    LiveSessionCreate,
    LiveSource,
    LiveSourceCreate,
    RecordingTargetCreate,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Per-test ephemeral SQLite engine for the live SA models.

    Mirrors ``tests/schedule/conftest.py:engine`` so the SQLite path
    exercises the same bind_engine + create_all pattern. Inline here
    rather than a separate ``tests/live/conftest.py`` to keep the
    Slice 1 Commit 3 correction surface as small as the directive
    allowed.
    """
    # Importing civiccast.live.models registers the live SA classes
    # against Base.metadata before create_all runs.
    import civiccast.live.models

    # Importing civiccast.schedule.models triggers the SA Engine
    # 'connect' event listener that ATTACHes ':memory:' AS civiccast on
    # SQLite connections, which is required for the schema-qualified
    # CREATE TABLE civiccast.live_sessions ... to resolve. The schedule
    # module owns this hook because it was first to need it.
    import civiccast.schedule.models  # noqa: F401

    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


class TestStateConstants:
    """Locks: the five live session states are stable. Changing this
    set requires a follow-up migration that widens or narrows the
    live_sessions_state_check CHECK constraint."""

    def test_state_constants_have_expected_values(self) -> None:
        assert LIVE_SESSION_STATE_IDLE == "idle"
        assert LIVE_SESSION_STATE_PREFLIGHT == "preflight"
        assert LIVE_SESSION_STATE_ON_AIR == "on_air"
        assert LIVE_SESSION_STATE_ENDING == "ending"
        assert LIVE_SESSION_STATE_RECORDED == "recorded"

    def test_state_tuple_membership_and_size(self) -> None:
        assert len(_LIVE_SESSION_STATES) == 5
        for state in (
            LIVE_SESSION_STATE_IDLE,
            LIVE_SESSION_STATE_PREFLIGHT,
            LIVE_SESSION_STATE_ON_AIR,
            LIVE_SESSION_STATE_ENDING,
            LIVE_SESSION_STATE_RECORDED,
        ):
            assert state in _LIVE_SESSION_STATES


class TestSourceTypeConstants:
    """Locks: the four configured source types are stable. SDI is
    explicitly excluded -- it ships in the post-1.0 cable add-on per
    spec section 8.3."""

    def test_source_type_constants_have_expected_values(self) -> None:
        assert SOURCE_TYPE_RTMP == "rtmp"
        assert SOURCE_TYPE_RTSP == "rtsp"
        assert SOURCE_TYPE_NDI == "ndi"
        assert SOURCE_TYPE_SRT == "srt"

    def test_source_type_tuple_membership_and_size(self) -> None:
        assert len(_SOURCE_TYPES) == 4
        for source_type in (
            SOURCE_TYPE_RTMP,
            SOURCE_TYPE_RTSP,
            SOURCE_TYPE_NDI,
            SOURCE_TYPE_SRT,
        ):
            assert source_type in _SOURCE_TYPES

    def test_sdi_explicitly_not_in_types(self) -> None:
        assert "sdi" not in _SOURCE_TYPES


class TestLiveSessionCheckConstraint:
    """Locks: the SA model's live_sessions_state_check constraint
    string names every state in _LIVE_SESSION_STATES, no more, no less.
    The Alembic migration 0007 ships an identical CHECK on Postgres."""

    def test_constraint_present(self) -> None:
        constraint_strings = [
            str(c.sqltext)
            for c in LiveSession.__table__.constraints
            if hasattr(c, "sqltext") and c.name == "live_sessions_state_check"
        ]
        assert len(constraint_strings) == 1, (
            f"Expected exactly one live_sessions_state_check; found {len(constraint_strings)}."
        )
        sql = constraint_strings[0]
        for state in _LIVE_SESSION_STATES:
            assert state in sql, f"State {state!r} missing from live_sessions_state_check: {sql}"


class TestLiveSourceCheckConstraint:
    """Locks: the SA model's live_sources_source_type_check constraint
    string names every type in _SOURCE_TYPES, no more, no less."""

    def test_constraint_present(self) -> None:
        constraint_strings = [
            str(c.sqltext)
            for c in LiveSource.__table__.constraints
            if hasattr(c, "sqltext") and c.name == "live_sources_source_type_check"
        ]
        assert len(constraint_strings) == 1
        sql = constraint_strings[0]
        for source_type in _SOURCE_TYPES:
            assert source_type in sql


class TestLiveRelayConfigCheckConstraint:
    """Locks: relay modes and health states stay explicit at the SA layer."""

    def test_mode_constraint_present(self) -> None:
        constraint_strings = [
            str(c.sqltext)
            for c in LiveRelayConfig.__table__.constraints
            if hasattr(c, "sqltext") and c.name == "live_relay_configs_mode_check"
        ]
        assert len(constraint_strings) == 1
        sql = constraint_strings[0]
        for mode in ("local_rtmp", "cloud_rtmp_relay", "direct_syndication"):
            assert mode in sql

    def test_health_constraint_present(self) -> None:
        constraint_strings = [
            str(c.sqltext)
            for c in LiveRelayConfig.__table__.constraints
            if hasattr(c, "sqltext") and c.name == "live_relay_configs_health_state_check"
        ]
        assert len(constraint_strings) == 1
        sql = constraint_strings[0]
        for health_state in ("not_configured", "ready", "degraded", "offline"):
            assert health_state in sql


class TestLiveSessionCreatePydantic:
    """Pydantic accept/reject for LiveSessionCreate."""

    def test_happy_path_minimal(self) -> None:
        m = LiveSessionCreate(
            live_session_id="city-council-2026-05-15",
            channel_id="gov-ch12",
            title="City Council Meeting",
        )
        assert m.live_session_id == "city-council-2026-05-15"
        assert m.notes is None

    def test_uppercase_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveSessionCreate(
                live_session_id="City-Council-2026-05-15",
                channel_id="gov-ch12",
                title="X",
            )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveSessionCreate(
                live_session_id="sess-1",
                channel_id="gov-ch12",
                title="X",
                state="on_air",  # state is server-controlled, not client
            )


class TestLiveSourceCreatePydantic:
    """Pydantic accept/reject for LiveSourceCreate."""

    def test_happy_path_rtmp(self) -> None:
        m = LiveSourceCreate(
            live_source_id="room-a-rtmp",
            channel_id="gov-ch12",
            name="Council Room A RTMP",
            source_type="rtmp",
            endpoint_url="rtmp://camera.example/live",
        )
        assert m.source_type == "rtmp"

    @pytest.mark.parametrize("source_type", ["rtmp", "rtsp", "ndi", "srt"])
    def test_all_four_source_types_accepted(self, source_type: str) -> None:
        m = LiveSourceCreate(
            live_source_id=f"room-a-{source_type}",
            channel_id="gov-ch12",
            name=f"Room A {source_type.upper()}",
            source_type=source_type,
            endpoint_url=f"{source_type}://camera.example/live",
        )
        assert m.source_type == source_type

    def test_sdi_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveSourceCreate(
                live_source_id="room-a-sdi",
                channel_id="gov-ch12",
                name="Room A SDI",
                source_type="sdi",
                endpoint_url="sdi://camera/0",
            )

    def test_unknown_source_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveSourceCreate(
                live_source_id="room-a-webrtc",
                channel_id="gov-ch12",
                name="Room A WebRTC",
                source_type="webrtc",
                endpoint_url="webrtc://room",
            )


class TestRecordingTargetCreatePydantic:
    """Pydantic accept/reject for RecordingTargetCreate."""

    def test_happy_path_filesystem(self) -> None:
        m = RecordingTargetCreate(
            recording_target_id="nas-primary",
            name="NAS Primary",
            target_uri="/srv/civiccast/recordings",
        )
        assert m.target_uri == "/srv/civiccast/recordings"

    def test_happy_path_file_uri_and_windows_drive_paths(self) -> None:
        for uri in ("file:///C:/recordings", "C:\\recordings", "C:/recordings"):
            m = RecordingTargetCreate(
                recording_target_id="fs-windows",
                name="Windows recordings",
                target_uri=uri,
            )
            assert m.target_uri == uri

    def test_unusable_uris_rejected_with_clear_message(self) -> None:
        """QA-007/QA-003: shapes the worker cannot resolve fail loudly at
        create time instead of silently wedging finalization. Object-store
        URIs (s3://…) were previously accepted as opaque strings; the worker
        only reads local files, so they are rejected until object-store
        support exists."""

        for uri in (
            "s3://civiccast-archive/recordings/",
            "http://example.org/recordings",
            "relative/path",
            "not a uri",
        ):
            with pytest.raises(ValidationError, match="file://"):
                RecordingTargetCreate(
                    recording_target_id="bad-target",
                    name="Bad target",
                    target_uri=uri,
                )

    def test_empty_uri_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RecordingTargetCreate(
                recording_target_id="empty",
                name="Empty",
                target_uri="",
            )


class TestLiveRelayConfigCreatePydantic:
    """Pydantic accept/reject for optional remote ingest configuration."""

    def test_happy_path_cloud_relay(self) -> None:
        m = LiveRelayConfigCreate(
            relay_config_id="project-relay",
            channel_id="gov-ch12",
            name="Project hosted relay",
            mode="cloud_rtmp_relay",
            endpoint_url="rtmps://relay.example/live/gov",
            return_playback_url="https://cdn.example/live/gov.m3u8",
            provider="project-hosted",
        )
        assert m.mode == "cloud_rtmp_relay"
        assert m.enabled is True

    def test_happy_path_direct_syndication(self) -> None:
        m = LiveRelayConfigCreate(
            relay_config_id="youtube-backup",
            channel_id="gov-ch12",
            name="YouTube backup",
            mode="direct_syndication",
            endpoint_url="rtmps://a.rtmps.youtube.example/live2/key",
            provider="youtube-live",
        )
        assert m.mode == "direct_syndication"

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveRelayConfigCreate(
                relay_config_id="bad",
                channel_id="gov-ch12",
                name="Bad",
                mode="vpn_required",  # type: ignore[arg-type]
                endpoint_url="rtmps://relay.example/live/gov",
            )

    def test_endpoint_without_stream_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LiveRelayConfigCreate(
                relay_config_id="bad-scheme",
                channel_id="gov-ch12",
                name="Bad scheme",
                mode="cloud_rtmp_relay",
                endpoint_url="ftp://relay.example/live/gov",
            )

    def test_health_update_rejects_unknown_state(self) -> None:
        with pytest.raises(ValidationError):
            LiveRelayHealthUpdate(health_state="warming-up")  # type: ignore[arg-type]


class TestServerDefaults:
    """Locks: ``server_default`` on each live table's ``created_at``
    column populates a real timestamp when the row is inserted without
    an explicit value.

    Codex audit 2026-05-11 caught that an earlier version used
    ``server_default="now()"`` (string literal) instead of a SQL
    expression. The string-literal path passes ``'now()'`` as a
    quoted SQL literal to the database, not as a function call, and
    populates ``created_at`` with the literal text on SQLite (or
    crashes on Postgres). The fix uses ``server_default=text(
    "CURRENT_TIMESTAMP")``; these tests prove the SA model path
    actually populates a timezone-aware ``datetime``.
    """

    def test_live_session_created_at_default_populates(self, engine) -> None:
        from sqlalchemy.orm import Session

        from civiccast.live.models import LiveSession

        with Session(bind=engine) as sess:
            sess.add(
                LiveSession(
                    live_session_id="default-session",
                    channel_id="gov-ch12",
                    title="Default-test session",
                )
            )
            sess.commit()

            row = sess.get(LiveSession, "default-session")
            assert row is not None
            assert row.created_at is not None
            assert isinstance(row.created_at.year, int) and row.created_at.year >= 2026

    def test_live_source_created_at_default_populates(self, engine) -> None:
        from sqlalchemy.orm import Session

        from civiccast.live.models import LiveSource

        with Session(bind=engine) as sess:
            sess.add(
                LiveSource(
                    live_source_id="default-source",
                    channel_id="gov-ch12",
                    name="Default-test source",
                    source_type="rtmp",
                    endpoint_url="rtmp://camera/live",
                )
            )
            sess.commit()

            row = sess.get(LiveSource, "default-source")
            assert row is not None
            assert row.created_at is not None
            assert isinstance(row.created_at.year, int) and row.created_at.year >= 2026

    def test_recording_target_created_at_default_populates(self, engine) -> None:
        from sqlalchemy.orm import Session

        from civiccast.live.models import RecordingTarget

        with Session(bind=engine) as sess:
            sess.add(
                RecordingTarget(
                    recording_target_id="default-target",
                    name="Default-test target",
                    target_uri="/srv/test",
                )
            )
            sess.commit()

            row = sess.get(RecordingTarget, "default-target")
            assert row is not None
            assert row.created_at is not None
            assert isinstance(row.created_at.year, int) and row.created_at.year >= 2026

    def test_live_relay_config_created_at_default_populates(self, engine) -> None:
        from sqlalchemy.orm import Session

        from civiccast.live.models import LiveRelayConfig

        with Session(bind=engine) as sess:
            sess.add(
                LiveRelayConfig(
                    relay_config_id="default-relay",
                    channel_id="gov-ch12",
                    name="Default-test relay",
                    mode="cloud_rtmp_relay",
                    endpoint_url="rtmps://relay.example/live/gov",
                )
            )
            sess.commit()

            row = sess.get(LiveRelayConfig, "default-relay")
            assert row is not None
            assert row.created_at is not None
            assert isinstance(row.created_at.year, int) and row.created_at.year >= 2026

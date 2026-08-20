# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-broadcast spine store: LiveSession + LiveSource + RecordingTarget.

Sprint 0.4 Slice 1 Commits 4 + 6. Owns:

* ``LiveSessionStore`` -- the LiveSession lifecycle:

      idle -> preflight -> on_air -> ending -> recorded

  Each transition is a conditional UPDATE filtered by the expected
  source state. Concurrent writers racing the same transition produce
  exactly one winner; the loser sees ``LiveSessionStateError`` because
  rowcount is zero after the predicate UPDATE missed. This is the v0.4
  release-plan operator guarantee for "Start/End Live Stream"
  idempotency on retry.

* ``LiveSourceStore`` (Slice 1 Commit 6) -- minimal CRUD over the
  configured ``live_sources`` rows so the staff router can list / get /
  create RTMP/RTSP/NDI/SRT descriptors. The pre-flight evaluator (Slice
  1 Commit 5) already reads ``live_sources`` directly; this store is the
  write-side seam.

* ``RecordingTargetStore`` (Slice 1 Commit 6) -- minimal CRUD over the
  ``recording_targets`` rows. Same posture as ``LiveSourceStore``.

This module does NOT include:

- Recording-finalization handler that writes a typed event row to
  ``live_session_events`` and inserts the recorded asset row in the
  same transaction (Slice 1 Commit 7).

The LiveSession transition set is intentionally forward-only. There is
no ``cancel_preflight`` (preflight -> idle) because operator-cancel
semantics are tied to the preflight evaluator contract that lands in
Slice 1 Commit 5; including a cancel transition here would commit to
a UX before the contract is fixed.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civiccast.live.models import (
    _LIVE_SESSION_STATES,
    LIVE_SESSION_STATE_ENDING,
    LIVE_SESSION_STATE_IDLE,
    LIVE_SESSION_STATE_ON_AIR,
    LIVE_SESSION_STATE_PREFLIGHT,
    LIVE_SESSION_STATE_RECORDED,
    LiveRelayConfig,
    LiveRelayConfigCreate,
    LiveRelayConfigResponse,
    LiveRelayHealthUpdate,
    LiveSession,
    LiveSessionCreate,
    LiveSessionResponse,
    LiveSource,
    LiveSourceCreate,
    LiveSourceResponse,
    RecordingTarget,
    RecordingTargetCreate,
    RecordingTargetResponse,
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class LiveSessionNotFoundError(Exception):
    """Raised when a lookup or transition targets a missing ``live_session_id``.

    Carries the requested id so a router layer can produce a 404 body
    that names the asked-for session without re-querying.
    """

    def __init__(self, live_session_id: str) -> None:
        self.live_session_id = live_session_id
        super().__init__(f"LiveSession {live_session_id!r} not found")


class LiveSessionStateError(Exception):
    """Raised when a transition is requested from a state that does not allow it.

    Carries the session id, the actual current state observed at the
    time the failed UPDATE was retried as a SELECT, and the name of the
    attempted transition. A router layer turns this into a 409 with a
    structured body of (current_state, attempted_transition).
    """

    def __init__(
        self,
        live_session_id: str,
        current_state: str,
        attempted_transition: str,
    ) -> None:
        self.live_session_id = live_session_id
        self.current_state = current_state
        self.attempted_transition = attempted_transition
        super().__init__(
            f"LiveSession {live_session_id!r} cannot {attempted_transition} "
            f"from state {current_state!r}"
        )


class LiveSessionAlreadyExistsError(Exception):
    """Raised when ``create_session`` is called with a ``live_session_id``
    that already exists. Mirrors the schedule store's
    :class:`civiccast.vod.store.AssetAlreadyExistsError` posture so a
    router can map both to 409 uniformly.
    """

    def __init__(self, live_session_id: str) -> None:
        self.live_session_id = live_session_id
        super().__init__(f"LiveSession {live_session_id!r} already exists")


class LiveSourceAlreadyExistsError(Exception):
    """Raised when a ``LiveSource`` create collides on primary key.

    Carries the requested id so the router layer can produce a 409 body
    that names the conflicting source without re-querying.
    """

    def __init__(self, live_source_id: str) -> None:
        self.live_source_id = live_source_id
        super().__init__(f"LiveSource {live_source_id!r} already exists")


class RecordingTargetAlreadyExistsError(Exception):
    """Raised when a ``RecordingTarget`` create collides on primary key."""

    def __init__(self, recording_target_id: str) -> None:
        self.recording_target_id = recording_target_id
        super().__init__(f"RecordingTarget {recording_target_id!r} already exists")


class LiveRelayConfigAlreadyExistsError(Exception):
    """Raised when a relay config create collides on primary key."""

    def __init__(self, relay_config_id: str) -> None:
        self.relay_config_id = relay_config_id
        super().__init__(f"LiveRelayConfig {relay_config_id!r} already exists")


class LiveRelayConfigNotFoundError(Exception):
    """Raised when a relay config lookup or health update targets a missing row."""

    def __init__(self, relay_config_id: str) -> None:
        self.relay_config_id = relay_config_id
        super().__init__(f"LiveRelayConfig {relay_config_id!r} not found")


# ---------------------------------------------------------------------------
# Transition table
# ---------------------------------------------------------------------------


# Maps transition method names to (expected current state, new state).
# Held module-private so the test surface can pin the transitions without
# inviting external callers to bypass the public methods.
_TRANSITIONS: dict[str, tuple[str, str]] = {
    "start_preflight": (LIVE_SESSION_STATE_IDLE, LIVE_SESSION_STATE_PREFLIGHT),
    "go_on_air": (LIVE_SESSION_STATE_PREFLIGHT, LIVE_SESSION_STATE_ON_AIR),
    "end_broadcast": (LIVE_SESSION_STATE_ON_AIR, LIVE_SESSION_STATE_ENDING),
    "mark_recorded": (LIVE_SESSION_STATE_ENDING, LIVE_SESSION_STATE_RECORDED),
}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class LiveSessionStore:
    """SA-backed live-session store with explicit state-machine transitions.

    Constructor takes a session-factory callable (same shape as
    :class:`civiccast.schedule.store.PostgresAssetStore`). Each method
    opens its own context-managed session so the caller never sees a
    leaked SA session and the store remains stateless between calls.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ CRUD

    def create_session(self, payload: LiveSessionCreate) -> LiveSessionResponse:
        """Insert a new LiveSession at state ``idle``.

        Raises :class:`LiveSessionAlreadyExistsError` when the primary
        key collides. ``rollback()`` runs before the re-raise so the
        underlying SA session is reusable for the next call.
        """
        with self._session_factory() as session:
            row = LiveSession(
                live_session_id=payload.live_session_id,
                channel_id=payload.channel_id,
                title=payload.title,
                state=LIVE_SESSION_STATE_IDLE,
                notes=payload.notes,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise LiveSessionAlreadyExistsError(payload.live_session_id) from exc
            session.refresh(row)
            return LiveSessionResponse.model_validate(row)

    def get_session(self, live_session_id: str) -> LiveSessionResponse | None:
        """Return the LiveSession projection, or ``None`` if absent."""
        with self._session_factory() as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == live_session_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return LiveSessionResponse.model_validate(row)

    def list_sessions(
        self,
        *,
        channel_id: str | None = None,
        states: tuple[str, ...] | None = None,
    ) -> list[LiveSessionResponse]:
        """Return live sessions, optionally filtered by channel and state.

        The public portal consumes this through the resident-safe
        ``/api/public/live/current`` route. Ordering is newest-started first,
        then newest-created first so an on-air session wins over stale rows.
        """
        if states is not None:
            for state in states:
                if state not in _LIVE_SESSION_STATES:
                    raise ValueError(
                        f"Unknown live session state {state!r}; "
                        f"expected one of {_LIVE_SESSION_STATES}."
                    )

        with self._session_factory() as session:
            stmt = select(LiveSession).order_by(
                LiveSession.started_at.desc().nulls_last(),
                LiveSession.created_at.desc(),
                LiveSession.live_session_id.asc(),
            )
            if channel_id is not None:
                stmt = stmt.where(LiveSession.channel_id == channel_id)
            if states is not None:
                stmt = stmt.where(LiveSession.state.in_(states))
            rows = session.execute(stmt).scalars().all()
            return [LiveSessionResponse.model_validate(row) for row in rows]

    # ------------------------------------------------------- State transitions

    def start_preflight(self, live_session_id: str) -> LiveSessionResponse:
        """Transition ``idle`` -> ``preflight``.

        Raises :class:`LiveSessionNotFoundError` when no row exists.
        Raises :class:`LiveSessionStateError` when the session is in any
        state other than ``idle``.
        """
        return self._transition(live_session_id, "start_preflight")

    def go_on_air(
        self,
        live_session_id: str,
        *,
        now: datetime | None = None,
    ) -> LiveSessionResponse:
        """Transition ``preflight`` -> ``on_air``; stamp ``started_at`` and
        the resolved recording target (provenance, Beta sprint B1).

        The stamp records which target the recording is expected under so the
        finalization worker never has to guess. Resolution: the oldest
        non-rehearsal target whose URI is a usable local location (the same
        rules the worker applies). No resolvable target stamps NULL — the
        worker's never-appeared deadline surfaces that misconfiguration.

        ``now`` is injectable for deterministic tests; production code
        passes ``None`` and the store records ``datetime.now(UTC)``.
        """
        target_id, target_uri = self._resolve_recording_target()
        return self._transition(
            live_session_id,
            "go_on_air",
            extra_setters={
                "started_at": now or datetime.now(UTC),
                "recording_target_id": target_id,
                "recording_target_uri": target_uri,
            },
        )

    def _resolve_recording_target(self) -> tuple[str | None, str | None]:
        from civiccast.live.recording_paths import (
            REHEARSAL_RECORDING_TARGET_ID,
            local_recording_path,
        )

        with self._session_factory() as session:
            targets = session.execute(
                select(RecordingTarget).order_by(RecordingTarget.created_at.asc())
            ).scalars()
            for target in targets:
                if target.recording_target_id == REHEARSAL_RECORDING_TARGET_ID:
                    continue
                if local_recording_path(target.target_uri) is None:
                    continue
                return target.recording_target_id, target.target_uri
        return None, None

    def end_broadcast(
        self,
        live_session_id: str,
        *,
        now: datetime | None = None,
    ) -> LiveSessionResponse:
        """Transition ``on_air`` -> ``ending`` and stamp ``ended_at``.

        Slice 1 Commit 7 will chain a recording-finalization handler off
        this transition; in this commit the store advances the state
        and stamps ``ended_at`` only.
        """
        return self._transition(
            live_session_id,
            "end_broadcast",
            extra_setters={"ended_at": now or datetime.now(UTC)},
        )

    def mark_recorded(self, live_session_id: str) -> LiveSessionResponse:
        """Transition ``ending`` -> ``recorded``.

        This is the terminal transition. Slice 1 Commit 7 will wrap
        ``mark_recorded`` together with a typed ``session.finalized``
        row insert into ``live_session_events`` and the
        ``ASSET_STATE_RECORDED`` asset-row insert inside a single
        transaction. This commit only advances the LiveSession state.
        """
        return self._transition(live_session_id, "mark_recorded")

    # --------------------------------------------------- Internal transition

    def _transition(
        self,
        live_session_id: str,
        transition_name: str,
        *,
        extra_setters: dict[str, object] | None = None,
    ) -> LiveSessionResponse:
        """Run a state transition as a conditional UPDATE.

        The UPDATE predicate is ``WHERE live_session_id = ? AND state = ?``.
        Two concurrent callers attempting the same transition race the
        UPDATE; exactly one wins (rowcount == 1) and the other sees
        rowcount == 0. The losing caller re-reads to distinguish
        "not found" from "wrong state" and raises the matching domain
        exception so the surface is structured for the router layer.
        """
        expected_state, new_state = _TRANSITIONS[transition_name]
        setters: dict[str, object] = {"state": new_state}
        if extra_setters is not None:
            setters.update(extra_setters)

        with self._session_factory() as session:
            result = session.execute(
                update(LiveSession)
                .where(LiveSession.live_session_id == live_session_id)
                .where(LiveSession.state == expected_state)
                .values(**setters)
            )
            # ``Result`` is the union return type SA gives at the public
            # surface; UPDATE statements always produce a ``CursorResult``
            # which carries ``rowcount``. Cast through Any to satisfy mypy
            # without dragging the cursor-result type into the public API.
            matched: int = result.rowcount  # type: ignore[attr-defined]
            if matched == 1:
                session.commit()
                updated_row = session.execute(
                    select(LiveSession).where(LiveSession.live_session_id == live_session_id)
                ).scalar_one()
                return LiveSessionResponse.model_validate(updated_row)

            # The predicate UPDATE matched zero rows. Either the session
            # does not exist or it is in a state other than ``expected_state``.
            session.rollback()
            current_row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == live_session_id)
            ).scalar_one_or_none()
            if current_row is None:
                raise LiveSessionNotFoundError(live_session_id)
            raise LiveSessionStateError(
                live_session_id=live_session_id,
                current_state=current_row.state,
                attempted_transition=transition_name,
            )


# ---------------------------------------------------------------------------
# LiveSourceStore -- minimal CRUD over live_sources (Slice 1 Commit 6)
# ---------------------------------------------------------------------------


class LiveSourceStore:
    """SA-backed store for configured live-input sources.

    The Slice 1 surface intentionally exposes ``create``, ``get``, and
    ``list`` only. ``delete`` and ``update`` are out of scope until a
    later rung defines the operator-cancel + edit UX; carrying them
    here without a UX would commit to semantics ahead of the contract.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, payload: LiveSourceCreate) -> LiveSourceResponse:
        """Insert a new ``LiveSource``. Raises :class:`LiveSourceAlreadyExistsError`
        on primary-key collision."""
        with self._session_factory() as session:
            row = LiveSource(
                live_source_id=payload.live_source_id,
                channel_id=payload.channel_id,
                name=payload.name,
                source_type=payload.source_type,
                # ``endpoint_url`` is ``HttpUrl | str`` at the Pydantic
                # surface; coerce to ``str`` for the DB column without
                # discarding the Pydantic validation that already ran.
                endpoint_url=str(payload.endpoint_url),
                credentials_handle=payload.credentials_handle,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise LiveSourceAlreadyExistsError(payload.live_source_id) from exc
            session.refresh(row)
            return LiveSourceResponse.model_validate(row)

    def get(self, live_source_id: str) -> LiveSourceResponse | None:
        """Return one ``LiveSource`` by id, or ``None`` if absent."""
        with self._session_factory() as session:
            row = session.execute(
                select(LiveSource).where(LiveSource.live_source_id == live_source_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return LiveSourceResponse.model_validate(row)

    def list(self, *, channel_id: str | None = None) -> list[LiveSourceResponse]:
        """Return every ``LiveSource``, optionally filtered by channel.

        Ordering is ``created_at`` ascending so older operator-configured
        sources surface first in the operator UI list. ``channel_id`` is
        an exact-match filter; pass ``None`` to return every row.
        """
        with self._session_factory() as session:
            stmt = select(LiveSource)
            if channel_id is not None:
                stmt = stmt.where(LiveSource.channel_id == channel_id)
            stmt = stmt.order_by(LiveSource.created_at.asc(), LiveSource.live_source_id.asc())
            rows = session.execute(stmt).scalars().all()
            return [LiveSourceResponse.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# LiveRelayConfigStore -- optional remote ingest / cloud relay targets
# ---------------------------------------------------------------------------


class LiveRelayConfigStore:
    """SA-backed store for optional outbound relay configuration.

    The zero-row posture is meaningful: stations continue to use the local
    self-hosted RTMP path. Rows here add optional cloud relay or direct
    syndication targets and health state for operator visibility.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, payload: LiveRelayConfigCreate) -> LiveRelayConfigResponse:
        """Insert a relay config row."""
        with self._session_factory() as session:
            row = LiveRelayConfig(
                relay_config_id=payload.relay_config_id,
                channel_id=payload.channel_id,
                name=payload.name,
                mode=payload.mode,
                endpoint_url=payload.endpoint_url,
                return_playback_url=payload.return_playback_url,
                provider=payload.provider,
                credentials_handle=payload.credentials_handle,
                enabled=payload.enabled,
                notes=payload.notes,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise LiveRelayConfigAlreadyExistsError(payload.relay_config_id) from exc
            session.refresh(row)
            return LiveRelayConfigResponse.model_validate(row)

    def get(self, relay_config_id: str) -> LiveRelayConfigResponse | None:
        """Return one relay config by id, or ``None`` if absent."""
        with self._session_factory() as session:
            row = session.execute(
                select(LiveRelayConfig).where(LiveRelayConfig.relay_config_id == relay_config_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return LiveRelayConfigResponse.model_validate(row)

    def list(
        self,
        *,
        channel_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[LiveRelayConfigResponse]:
        """Return relay configs, optionally filtered by channel and enabled state."""
        with self._session_factory() as session:
            stmt = select(LiveRelayConfig)
            if channel_id is not None:
                stmt = stmt.where(LiveRelayConfig.channel_id == channel_id)
            if enabled is not None:
                stmt = stmt.where(LiveRelayConfig.enabled == enabled)
            stmt = stmt.order_by(
                LiveRelayConfig.created_at.asc(),
                LiveRelayConfig.relay_config_id.asc(),
            )
            rows = session.execute(stmt).scalars().all()
            return [LiveRelayConfigResponse.model_validate(row) for row in rows]

    def update_health(
        self,
        relay_config_id: str,
        payload: LiveRelayHealthUpdate,
    ) -> LiveRelayConfigResponse:
        """Update operator-visible health for a relay config."""
        setters: dict[str, object] = {
            "health_state": payload.health_state,
            "last_heartbeat_at": payload.last_heartbeat_at or datetime.now(UTC),
        }
        if payload.notes is not None:
            setters["notes"] = payload.notes

        with self._session_factory() as session:
            result = session.execute(
                update(LiveRelayConfig)
                .where(LiveRelayConfig.relay_config_id == relay_config_id)
                .values(**setters)
            )
            matched: int = result.rowcount  # type: ignore[attr-defined]
            if matched == 0:
                session.rollback()
                raise LiveRelayConfigNotFoundError(relay_config_id)
            session.commit()
            row = session.execute(
                select(LiveRelayConfig).where(LiveRelayConfig.relay_config_id == relay_config_id)
            ).scalar_one()
            return LiveRelayConfigResponse.model_validate(row)


# ---------------------------------------------------------------------------
# RecordingTargetStore -- minimal CRUD over recording_targets (Slice 1 Commit 6)
# ---------------------------------------------------------------------------


class RecordingTargetStore:
    """SA-backed store for recording-target descriptors.

    Same Slice 1 posture as ``LiveSourceStore``: create/get/list only.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def create(self, payload: RecordingTargetCreate) -> RecordingTargetResponse:
        """Insert a new ``RecordingTarget``. Raises
        :class:`RecordingTargetAlreadyExistsError` on primary-key collision."""
        with self._session_factory() as session:
            row = RecordingTarget(
                recording_target_id=payload.recording_target_id,
                name=payload.name,
                target_uri=payload.target_uri,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise RecordingTargetAlreadyExistsError(payload.recording_target_id) from exc
            session.refresh(row)
            return RecordingTargetResponse.model_validate(row)

    def get(self, recording_target_id: str) -> RecordingTargetResponse | None:
        """Return one ``RecordingTarget`` by id, or ``None`` if absent."""
        with self._session_factory() as session:
            row = session.execute(
                select(RecordingTarget).where(
                    RecordingTarget.recording_target_id == recording_target_id
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return RecordingTargetResponse.model_validate(row)

    def list(self) -> list[RecordingTargetResponse]:
        """Return every ``RecordingTarget`` ordered by ``created_at`` ascending."""
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(RecordingTarget).order_by(
                        RecordingTarget.created_at.asc(),
                        RecordingTarget.recording_target_id.asc(),
                    )
                )
                .scalars()
                .all()
            )
            return [RecordingTargetResponse.model_validate(row) for row in rows]

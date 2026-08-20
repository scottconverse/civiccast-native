# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-takeover orchestration (CivicCast 3.0 — S5).

Wires the proven engine primitives into a controllable, audited operation:

* **take** — build the live source plan, record a :class:`TakeoverSession`
  (open), and queue an ``EgressCommand(action="takeover")`` for the daemon
  (which calls ``supervisor.request_live_takeover``).
* **handback** — queue ``EgressCommand(action="handback")`` and close the
  session.
* **state** — the runtime :class:`ManualRouteState` (active session +
  can_takeover / can_return), derived from the audit store + live readiness.
* **audit** — the channel's takeover history.

The service touches no engine process directly; it persists + enqueues, and the
daemon consumes the commands (S5 daemon slice). ``clock`` / ``id_factory`` are
injectable for deterministic tests; ``ingest_plan_provider`` is injected so the
service stays decoupled from the live relay-config store.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.live_takeover import build_live_takeover_source_plan
from civiccast.egress.models import EgressCommand, ManualRouteState, TakeoverSession
from civiccast.egress.store import EgressStore
from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
from civiccast.live.models import RELAY_HEALTH_READY, LiveIngestPlan

IngestPlanProvider = Callable[[str], LiveIngestPlan]


class AlreadyLiveError(RuntimeError):
    """The channel is already under live takeover (→ 409)."""


class NotInTakeoverError(RuntimeError):
    """The channel is not currently under live takeover (→ 404)."""


class TakeoverNotReadyError(RuntimeError):
    """No ready live source could be prepared for takeover (→ 422)."""


def _default_token() -> str:
    return secrets.token_urlsafe(12)


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _live_source_ready(plan: LiveIngestPlan) -> bool:
    return any(
        path.enabled and path.health_state == RELAY_HEALTH_READY
        for path in (plan.local_default, *plan.relay_paths)
    )


class TakeoverService:
    """Orchestrates live takeover / handback for one CivicCast deployment."""

    def __init__(
        self,
        audit_store: PostgresTakeoverAuditStore,
        egress_store: EgressStore,
        ingest_plan_provider: IngestPlanProvider,
        *,
        clock: Callable[[], datetime] = _default_clock,
        id_factory: Callable[[], str] = _default_token,
    ) -> None:
        self._audit = audit_store
        self._egress = egress_store
        self._ingest_plan_provider = ingest_plan_provider
        self._clock = clock
        self._id_factory = id_factory

    def take(
        self,
        *,
        channel_id: str,
        operator_id: str,
        operator_name: str | None = None,
        reason: str | None = None,
        path_id: str | None = None,
        duration_seconds: float = 3600.0,
    ) -> TakeoverSession:
        """Begin a live takeover. Raises AlreadyLiveError (409) if one is open,
        TakeoverNotReadyError (422) if no ready live source can be prepared."""
        if self._audit.get_active(channel_id) is not None:
            raise AlreadyLiveError(f"Channel {channel_id!r} is already under live takeover.")

        ingest_plan = self._ingest_plan_provider(channel_id)
        try:
            plan = build_live_takeover_source_plan(
                channel_id=channel_id,
                ingest_plan=ingest_plan,
                path_id=path_id,
                duration_seconds=duration_seconds,
            )
        except (SourcePrepareError, ValueError) as exc:
            raise TakeoverNotReadyError(str(exc)) from exc

        now = self._clock()
        token = self._id_factory()
        segment = plan.segments[0]
        session = TakeoverSession(
            session_id=f"takeover-{token}",
            channel_id=channel_id,
            source_ref=segment.source_ref or path_id or ingest_plan.recommended_path_id,
            source_label=segment.label,
            operator_id=operator_id,
            operator_name=operator_name,
            reason=reason,
            took_over_at=now,
            returned_at=None,
            source_plan_json=plan.model_dump_json(),
            notes=None,
        )
        stored = self._audit.append(session)
        # Queue the engine command AFTER the durable session exists, so the undo
        # trail is never lost (mirrors the commit gate's persist-before-dispatch).
        self._egress.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action="takeover",
                issued_at=now,
                issued_by=operator_id,
                command_id=f"takeover-{token}",
            )
        )
        return stored

    def handback(
        self,
        *,
        channel_id: str,
        operator_id: str,
        notes: str | None = None,
    ) -> TakeoverSession:
        """Return a channel from takeover to its scheduled source. Raises
        NotInTakeoverError (404) if the channel is not currently live."""
        active = self._audit.get_active(channel_id)
        if active is None:
            raise NotInTakeoverError(f"Channel {channel_id!r} is not under live takeover.")

        now = self._clock()
        token = self._id_factory()
        self._egress.enqueue_command(
            EgressCommand(
                channel_id=channel_id,
                action="handback",
                issued_at=now,
                issued_by=operator_id,
                command_id=f"handback-{token}",
            )
        )
        closed = self._audit.close(active.session_id, returned_at=now, notes=notes)
        # close() can only return None if the row vanished between get_active and
        # close (vanishingly unlikely); fall back to the observed active session.
        return closed if closed is not None else active

    def state(self, channel_id: str) -> ManualRouteState:
        """Return the channel's manual-route state (active session + can flags)."""
        active = self._audit.get_active(channel_id)
        ready = False
        if active is None:
            # Only probe live readiness when not already live (cheap + relevant).
            try:
                ready = _live_source_ready(self._ingest_plan_provider(channel_id))
            except Exception:  # readiness is best-effort; never fail the state read
                ready = False
        return ManualRouteState(
            channel_id=channel_id,
            active_session=active,
            can_takeover=active is None and ready,
            can_return=active is not None,
        )

    def audit(self, channel_id: str, *, limit: int = 50) -> list[TakeoverSession]:
        """Return the channel's takeover history (most recent first)."""
        return self._audit.list_by_channel(channel_id, limit=limit)

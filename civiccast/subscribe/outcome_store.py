# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence seam for durable notification-delivery outcomes (WP-05).

One logical delivery per publication x subscription x target x transport, with
numbered attempts beneath it. The unique constraint on the logical identity is
the concurrency guard: :meth:`claim` inserts the row before anything is sent,
so a second concurrent approval loses the insert, reads back the winner's row,
and skips a recipient that is already observed ``sent`` instead of mailing them
twice.

No subscriber PII, webhook URL, secret or signature is written here -- see the
PII note on :class:`civiccast.subscribe.models.NotificationDeliveryOutcome`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civiccast.subscribe.models import (
    NotificationDeliveryAttempt,
    NotificationDeliveryAttemptRecord,
    NotificationDeliveryOutcome,
    NotificationDeliveryOutcomeRecord,
    NotificationDeliveryOutcomeValue,
)

SessionFactory = Callable[[], AbstractContextManager[Session]]

__all__ = [
    "ClaimedDelivery",
    "InMemoryNotificationDeliveryStore",
    "NotificationDeliveryStore",
    "PostgresNotificationDeliveryStore",
    "logical_delivery_key",
]


def logical_delivery_key(
    *,
    publication_id: str,
    subscription_id: str,
    target_type: str,
    target_id: str,
    transport: str,
) -> str:
    """Stable logical delivery key.

    Deliberately excludes the attempt number: this key IS the duplicate-send
    guard, so attempt 1 and attempt 7 of the same recipient must collide on the
    same row (WP-05 plan item 4). Digested rather than concatenated so the key
    stays inside the 80-character column no matter how long a station's target
    ids are, and so it never carries a readable handle.
    """

    digest = hashlib.sha256(
        "\x1f".join((publication_id, subscription_id, target_type, target_id, transport)).encode()
    ).hexdigest()
    return f"ndk-{digest[:40]}"


@dataclass(frozen=True)
class ClaimedDelivery:
    """Result of :meth:`NotificationDeliveryStore.claim`.

    ``already_sent`` is the guard the caller checks before sending: it is
    ``True`` only when a previous run (or a concurrent one that won the insert)
    already observed this recipient delivered.
    """

    record: NotificationDeliveryOutcomeRecord
    created: bool

    @property
    def already_sent(self) -> bool:
        return self.record.outcome == "sent"


class NotificationDeliveryStore(Protocol):
    def claim(
        self,
        *,
        publication_id: str,
        asset_id: str,
        subscription_id: str,
        target_type: str,
        target_id: str,
        transport: str,
        now: datetime | None = None,
    ) -> ClaimedDelivery: ...

    def record_attempt(
        self,
        *,
        delivery_key: str,
        outcome: NotificationDeliveryOutcomeValue,
        error_code: str | None = None,
        detail: str = "",
        retry_id: str | None = None,
        now: datetime | None = None,
    ) -> NotificationDeliveryOutcomeRecord: ...

    def get(self, delivery_key: str) -> NotificationDeliveryOutcomeRecord | None: ...

    def list_for_publication(
        self, publication_id: str
    ) -> list[NotificationDeliveryOutcomeRecord]: ...

    def list_attempts(self, delivery_key: str) -> list[NotificationDeliveryAttemptRecord]: ...


def _new_record(
    *,
    delivery_key: str,
    publication_id: str,
    asset_id: str,
    subscription_id: str,
    target_type: str,
    target_id: str,
    transport: str,
    now: datetime,
) -> NotificationDeliveryOutcomeRecord:
    return NotificationDeliveryOutcomeRecord(
        delivery_key=delivery_key,
        publication_id=publication_id,
        asset_id=asset_id,
        subscription_id=subscription_id,
        target_type=target_type,  # type: ignore[arg-type]
        target_id=target_id,
        transport=transport,  # type: ignore[arg-type]
        outcome="pending",
        attempts=0,
        created_at=now,
        updated_at=now,
    )


def _applied(
    record: NotificationDeliveryOutcomeRecord,
    *,
    outcome: NotificationDeliveryOutcomeValue,
    error_code: str | None,
    detail: str,
    retry_id: str | None,
    now: datetime,
) -> NotificationDeliveryOutcomeRecord:
    attempts = record.attempts + 1
    return record.model_copy(
        update={
            "outcome": outcome,
            "attempts": attempts,
            "error_code": error_code,
            "detail": detail,
            # A successful retry clears the queue linkage; a queued one keeps
            # it so the dead-letter row stays reachable from the publish run.
            "retry_id": retry_id,
            "first_attempted_at": record.first_attempted_at or now,
            "last_attempted_at": now,
            "succeeded_at": now if outcome == "sent" else record.succeeded_at,
            "updated_at": now,
        }
    )


class InMemoryNotificationDeliveryStore:
    """In-memory outcomes for tests and no-durable-storage app instances.

    Single-process only: it cannot provide the cross-process concurrency
    guarantee the UNIQUE constraint gives the Postgres/SQLite store. It is
    still a real duplicate-send guard within one process, which is what an
    ephemeral instance can honestly offer.
    """

    def __init__(self) -> None:
        self._records: dict[str, NotificationDeliveryOutcomeRecord] = {}
        self._attempts: dict[str, list[NotificationDeliveryAttemptRecord]] = {}

    def claim(
        self,
        *,
        publication_id: str,
        asset_id: str,
        subscription_id: str,
        target_type: str,
        target_id: str,
        transport: str,
        now: datetime | None = None,
    ) -> ClaimedDelivery:
        resolved_now = now or datetime.now(UTC)
        key = logical_delivery_key(
            publication_id=publication_id,
            subscription_id=subscription_id,
            target_type=target_type,
            target_id=target_id,
            transport=transport,
        )
        existing = self._records.get(key)
        if existing is not None:
            return ClaimedDelivery(record=existing, created=False)
        record = _new_record(
            delivery_key=key,
            publication_id=publication_id,
            asset_id=asset_id,
            subscription_id=subscription_id,
            target_type=target_type,
            target_id=target_id,
            transport=transport,
            now=resolved_now,
        )
        self._records[key] = record
        return ClaimedDelivery(record=record, created=True)

    def record_attempt(
        self,
        *,
        delivery_key: str,
        outcome: NotificationDeliveryOutcomeValue,
        error_code: str | None = None,
        detail: str = "",
        retry_id: str | None = None,
        now: datetime | None = None,
    ) -> NotificationDeliveryOutcomeRecord:
        resolved_now = now or datetime.now(UTC)
        record = self._records.get(delivery_key)
        if record is None:
            raise KeyError(delivery_key)
        updated = _applied(
            record,
            outcome=outcome,
            error_code=error_code,
            detail=detail,
            retry_id=retry_id,
            now=resolved_now,
        )
        self._records[delivery_key] = updated
        self._attempts.setdefault(delivery_key, []).append(
            NotificationDeliveryAttemptRecord(
                delivery_key=delivery_key,
                attempt_number=updated.attempts,
                attempted_at=resolved_now,
                outcome=outcome,
                error_code=error_code,
                detail=detail,
                retry_id=retry_id,
            )
        )
        return updated

    def get(self, delivery_key: str) -> NotificationDeliveryOutcomeRecord | None:
        return self._records.get(delivery_key)

    def list_for_publication(self, publication_id: str) -> list[NotificationDeliveryOutcomeRecord]:
        return sorted(
            (
                record
                for record in self._records.values()
                if record.publication_id == publication_id
            ),
            key=lambda record: record.delivery_key,
        )

    def list_attempts(self, delivery_key: str) -> list[NotificationDeliveryAttemptRecord]:
        return sorted(
            self._attempts.get(delivery_key, []), key=lambda attempt: attempt.attempt_number
        )


class PostgresNotificationDeliveryStore:
    """SQLAlchemy-backed durable outcomes (Postgres in production, SQLite locally)."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def claim(
        self,
        *,
        publication_id: str,
        asset_id: str,
        subscription_id: str,
        target_type: str,
        target_id: str,
        transport: str,
        now: datetime | None = None,
    ) -> ClaimedDelivery:
        resolved_now = now or datetime.now(UTC)
        key = logical_delivery_key(
            publication_id=publication_id,
            subscription_id=subscription_id,
            target_type=target_type,
            target_id=target_id,
            transport=transport,
        )
        with self._session_factory() as session:
            existing = session.get(NotificationDeliveryOutcome, key)
            if existing is not None:
                return ClaimedDelivery(record=_to_record(existing), created=False)
            session.add(
                NotificationDeliveryOutcome(
                    delivery_key=key,
                    publication_id=publication_id,
                    asset_id=asset_id,
                    subscription_id=subscription_id,
                    target_type=target_type,
                    target_id=target_id,
                    transport=transport,
                    outcome="pending",
                    attempts=0,
                    detail="",
                    created_at=resolved_now,
                    updated_at=resolved_now,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # Another approval won the insert. The UNIQUE constraint --
                # not an in-memory set -- is what makes this safe across
                # processes; read back the winner's row and let the caller
                # decide (it will skip an already-sent recipient).
                session.rollback()
                winner = session.get(NotificationDeliveryOutcome, key)
                if winner is None:
                    winner = session.execute(
                        select(NotificationDeliveryOutcome).where(
                            NotificationDeliveryOutcome.publication_id == publication_id,
                            NotificationDeliveryOutcome.subscription_id == subscription_id,
                            NotificationDeliveryOutcome.target_type == target_type,
                            NotificationDeliveryOutcome.target_id == target_id,
                            NotificationDeliveryOutcome.transport == transport,
                        )
                    ).scalar_one()
                return ClaimedDelivery(record=_to_record(winner), created=False)
            row = session.get(NotificationDeliveryOutcome, key)
            assert row is not None  # nosec B101 - just committed above
            return ClaimedDelivery(record=_to_record(row), created=True)

    def record_attempt(
        self,
        *,
        delivery_key: str,
        outcome: NotificationDeliveryOutcomeValue,
        error_code: str | None = None,
        detail: str = "",
        retry_id: str | None = None,
        now: datetime | None = None,
    ) -> NotificationDeliveryOutcomeRecord:
        resolved_now = now or datetime.now(UTC)
        with self._session_factory() as session:
            row = session.get(NotificationDeliveryOutcome, delivery_key)
            if row is None:
                raise KeyError(delivery_key)
            updated = _applied(
                _to_record(row),
                outcome=outcome,
                error_code=error_code,
                detail=detail,
                retry_id=retry_id,
                now=resolved_now,
            )
            row.outcome = updated.outcome
            row.attempts = updated.attempts
            row.error_code = updated.error_code
            row.detail = updated.detail
            row.retry_id = updated.retry_id
            row.first_attempted_at = updated.first_attempted_at
            row.last_attempted_at = updated.last_attempted_at
            row.succeeded_at = updated.succeeded_at
            row.updated_at = updated.updated_at
            session.add(
                NotificationDeliveryAttempt(
                    delivery_key=delivery_key,
                    attempt_number=updated.attempts,
                    attempted_at=resolved_now,
                    outcome=outcome,
                    error_code=error_code,
                    detail=detail,
                    retry_id=retry_id,
                )
            )
            session.commit()
            return updated

    def get(self, delivery_key: str) -> NotificationDeliveryOutcomeRecord | None:
        with self._session_factory() as session:
            row = session.get(NotificationDeliveryOutcome, delivery_key)
            return None if row is None else _to_record(row)

    def list_for_publication(self, publication_id: str) -> list[NotificationDeliveryOutcomeRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(NotificationDeliveryOutcome)
                .where(NotificationDeliveryOutcome.publication_id == publication_id)
                .order_by(NotificationDeliveryOutcome.delivery_key.asc())
            ).all()
            return [_to_record(row) for row in rows]

    def list_attempts(self, delivery_key: str) -> list[NotificationDeliveryAttemptRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(NotificationDeliveryAttempt)
                .where(NotificationDeliveryAttempt.delivery_key == delivery_key)
                .order_by(NotificationDeliveryAttempt.attempt_number.asc())
            ).all()
            return [
                NotificationDeliveryAttemptRecord(
                    delivery_key=row.delivery_key,
                    attempt_number=row.attempt_number,
                    attempted_at=_aware(row.attempted_at),
                    outcome=row.outcome,  # type: ignore[arg-type]
                    error_code=row.error_code,
                    detail=row.detail,
                    retry_id=row.retry_id,
                )
                for row in rows
            ]


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; re-attach UTC so callers see aware datetimes."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _optional_aware(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


def _to_record(row: NotificationDeliveryOutcome) -> NotificationDeliveryOutcomeRecord:
    return NotificationDeliveryOutcomeRecord(
        delivery_key=row.delivery_key,
        publication_id=row.publication_id,
        asset_id=row.asset_id,
        subscription_id=row.subscription_id,
        target_type=row.target_type,  # type: ignore[arg-type]
        target_id=row.target_id,
        transport=row.transport,  # type: ignore[arg-type]
        outcome=row.outcome,  # type: ignore[arg-type]
        attempts=row.attempts,
        error_code=row.error_code,
        detail=row.detail,
        retry_id=row.retry_id,
        first_attempted_at=_optional_aware(row.first_attempted_at),
        last_attempted_at=_optional_aware(row.last_attempted_at),
        succeeded_at=_optional_aware(row.succeeded_at),
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )

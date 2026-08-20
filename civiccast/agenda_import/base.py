# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""``AgendaSource`` Protocol + the shared error taxonomy (plan §5, §10).

Every adapter (``legistar.py``, ``primegov.py``, ``civicclerk.py``) implements
this Protocol so the router and mapper never branch on vendor. Errors are
vendor-agnostic too, so the router's exception handling (plan §6 API
surface) does not grow a new ``except`` clause per vendor:

* :class:`AgendaSourceAuthRequiredError` — 401/403 from a token-gated tenant.
  Distinct from a generic upstream failure so the operator/LPM gets an
  actionable message ("get a token from city IT"), never a bare 502
  (plan §3 "New risk to design around").
* :class:`AgendaSourceUpstreamError` — 5xx, timeout, or a malformed/empty
  response. "Fail loud, never silently import nothing" (plan Part 1) — an
  empty items list from a real event is treated as malformed, not a valid
  zero-item agenda. PrimeGov also raises this (rather than fabricating
  items) when a meeting has no HTML compiled agenda and no verified
  anonymous PDF fetch path (see ``primegov.py``'s docstring).
* :class:`AgendaSourceNotAvailableError` — the requested source name is not
  implemented in this release. All three vendors (Legistar, PrimeGov,
  CivicClerk) resolve to a working adapter as of Phase 3; this error now
  only fires for a genuinely unknown source name, but stays part of the
  taxonomy so the router's exception handling doesn't need to change if a
  future vendor is wired the same way the first three were (plan §8 task 5).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from civiccast.agenda_import.models import ExternalAgenda, ExternalMeetingSummary


class AgendaSourceError(RuntimeError):
    """Base error for every :class:`AgendaSource` adapter failure."""


class AgendaSourceAuthRequiredError(AgendaSourceError):
    """A token-gated tenant rejected the request with 401/403."""


class AgendaSourceUpstreamError(AgendaSourceError):
    """5xx, timeout, or a malformed/empty upstream response."""


class AgendaSourceNotAvailableError(AgendaSourceError):
    """The requested source name has no adapter in this release."""


class AgendaSource(Protocol):
    """One agenda-system adapter: list meetings, fetch one meeting's agenda."""

    def fetch_meetings(
        self, client_code: str, *, since: date | None = None
    ) -> list[ExternalMeetingSummary]:
        """Meetings for ``client_code`` on/after ``since`` (default: today)."""
        ...

    def fetch_agenda(self, client_code: str, event_id: str) -> ExternalAgenda:
        """The full normalized agenda for one meeting."""
        ...


__all__ = [
    "AgendaSource",
    "AgendaSourceAuthRequiredError",
    "AgendaSourceError",
    "AgendaSourceNotAvailableError",
    "AgendaSourceUpstreamError",
]

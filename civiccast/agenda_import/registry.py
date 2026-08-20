# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Resolve a source name to an :class:`AgendaSource` adapter (plan §8 task 5).

All three vendors now resolve to a working adapter (Phase 3 completes the
trio). ``primegov`` and ``civicclerk`` both ignore ``token`` -- neither
vendor's public tenant API has a verified token/auth convention (plan §3),
unlike Legistar's.
"""

from __future__ import annotations

from civiccast.agenda_import.base import AgendaSource, AgendaSourceNotAvailableError
from civiccast.agenda_import.civicclerk import CivicClerkSource
from civiccast.agenda_import.legistar import LegistarSource
from civiccast.agenda_import.primegov import PrimeGovSource


def build_source(name: str, *, timeout_seconds: float, token: str | None) -> AgendaSource:
    if name == "legistar":
        return LegistarSource(timeout_seconds=timeout_seconds, token=token)
    if name == "primegov":
        return PrimeGovSource(timeout_seconds=timeout_seconds)
    if name == "civicclerk":
        return CivicClerkSource(timeout_seconds=timeout_seconds)
    raise AgendaSourceNotAvailableError(
        f"Agenda source {name!r} is not implemented in this CivicCast release; "
        "'legistar', 'primegov', and 'civicclerk' are available."
    )


__all__ = ["build_source"]

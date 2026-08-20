# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Normalized, vendor-agnostic agenda shapes (plan §5).

Every :class:`~civiccast.agenda_import.base.AgendaSource` adapter (Legistar
and PrimeGov now; CivicClerk in Phase 3) returns these shapes. Nothing
vendor-specific (Legistar's ``EventId``, PrimeGov's ``documentList``, ...)
leaks past the adapter boundary — :mod:`civiccast.agenda_import.mapper` only
ever sees :class:`ExternalAgenda`.

These are untrusted-input shapes: no URL-scheme validation happens here (a
vendor API can return anything). The mapper applies the same
``http``/``https`` allowlist :func:`civiccast.agenda.models.
validate_source_doc_url` already enforces for operator-typed URLs, because
vendor data crosses the exact same trust boundary (plan §10).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

#: The three vendors this sprint targets. All three have working adapters as
#: of Phase 3 -- ``"legistar"`` (Phase 1), ``"primegov"`` (Phase 2),
#: ``"civicclerk"`` (Phase 3, pure reuse of Phase 2's docparse.py).
AgendaSourceName = Literal["legistar", "primegov", "civicclerk"]
AGENDA_SOURCE_NAMES: tuple[str, ...] = ("legistar", "primegov", "civicclerk")


class ExternalAgendaItem(BaseModel):
    """One agenda item as reported by a vendor, before any domain validation."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=0)
    title: Annotated[str, Field(min_length=1, max_length=400)]
    number: Annotated[str | None, Field(default=None, max_length=40)] = None
    # Untrusted: no scheme allowlist here. video_timecode_s is intentionally
    # absent — the operator aligns timecodes after import (plan §5).
    doc_url: Annotated[str | None, Field(default=None, max_length=2000)] = None


class ExternalAgenda(BaseModel):
    """One meeting's full agenda as reported by a vendor."""

    model_config = ConfigDict(extra="forbid")

    external_id: Annotated[str, Field(min_length=1, max_length=120)]
    title: Annotated[str, Field(min_length=1, max_length=400)]
    meeting_datetime: datetime | None = None
    source_doc_url: Annotated[str | None, Field(default=None, max_length=2000)] = None
    items: list[ExternalAgendaItem] = Field(default_factory=list)


class ExternalMeetingSummary(BaseModel):
    """One row of the discovery dropdown (plan §6 GET .../meetings)."""

    model_config = ConfigDict(extra="forbid")

    external_id: Annotated[str, Field(min_length=1, max_length=120)]
    title: Annotated[str, Field(min_length=1, max_length=400)]
    meeting_datetime: datetime | None = None


__all__ = [
    "AGENDA_SOURCE_NAMES",
    "AgendaSourceName",
    "ExternalAgenda",
    "ExternalAgendaItem",
    "ExternalMeetingSummary",
]

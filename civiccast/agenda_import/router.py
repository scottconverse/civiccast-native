# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Agenda import API surface (plan §6): import + discovery routes.

``CIVICCAST_AGENDA_SOURCE=off`` (the default) makes both routes act as if
they don't exist -- a 404 naming the env var, never a 500 or a startup
failure (plan §7). Role gating mirrors :mod:`civiccast.agenda.router`'s
``_AUTHOR`` scopes (``records_clerk`` / ``meeting_operator``): agenda import
is a staff-only write path, same trust level as the existing agenda CRUD.

Both routes are wired generically against the
:class:`~civiccast.agenda_import.base.AgendaSource` Protocol (plan §8 task 5)
-- all three vendors (``legistar``, ``primegov``, ``civicclerk``) resolve to
a working adapter as of Phase 3.
"""

from __future__ import annotations

import functools
import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from civiccast.agenda.models import AgendaItem
from civiccast.agenda.router import get_agenda_store
from civiccast.agenda.store import AgendaItemOrderConflictError, AgendaNotFoundError, AgendaStore
from civiccast.agenda_import.base import (
    AgendaSourceAuthRequiredError,
    AgendaSourceNotAvailableError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.config import AgendaImportSettings, validate_client_code
from civiccast.agenda_import.mapper import import_external_agenda
from civiccast.agenda_import.models import AgendaSourceName, ExternalMeetingSummary
from civiccast.agenda_import.provenance import AgendaImportProvenanceStore
from civiccast.agenda_import.registry import build_source
from civiccast.auth.roles import require_any_role

logger = logging.getLogger(__name__)

_AUTHOR = ("records_clerk", "meeting_operator")
_AUTHOR_EXTRA = {"x-required-roles": list(_AUTHOR)}

_DISABLED_DETAIL = (
    "Agenda import is not enabled. Set CIVICCAST_AGENDA_SOURCE to 'legistar', "
    "'primegov', or 'civicclerk' to turn it on."
)


@functools.cache
def _settings() -> AgendaImportSettings:
    """Cached env read (matches ``civiccast.agenda.router._station_id``'s
    convention). Tests that flip ``CIVICCAST_AGENDA_SOURCE`` mid-run must
    call ``_settings.cache_clear()``."""
    return AgendaImportSettings.from_env()


def get_agenda_import_settings() -> AgendaImportSettings:
    """DI seam so tests can override without touching the environment."""
    return _settings()


def _require_enabled(settings: AgendaImportSettings) -> None:
    if not settings.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_DISABLED_DETAIL)


def _require_store(store: AgendaStore | None) -> AgendaStore:
    if store is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Durable storage is not ready yet."
        )
    return store


def get_agenda_import_provenance_store() -> AgendaImportProvenanceStore | None:
    """DI seam -- overridden by the app factory. ``None`` means "don't record
    provenance"; it is bookkeeping only and never blocks an import."""
    return None


router = APIRouter(prefix="/api/staff", tags=["staff", "agenda-import"])


class AgendaImportExternalRequest(BaseModel):
    """POST .../import-external body (plan §6)."""

    model_config = ConfigDict(extra="forbid")

    source: AgendaSourceName
    client_code: Annotated[
        str, Field(min_length=1, max_length=64), AfterValidator(validate_client_code)
    ]
    event_id: Annotated[str, Field(min_length=1, max_length=120)]


@router.post(
    "/agenda/{agenda_id}/import-external",
    response_model=list[AgendaItem],
    summary="Import agenda items from an external agenda system",
    dependencies=[Depends(require_any_role(*_AUTHOR))],
    openapi_extra=_AUTHOR_EXTRA,
    responses={
        404: {"description": "Agenda import disabled, or meeting agenda not found"},
        422: {"description": "Source not yet available in this release"},
        502: {"description": "Upstream fetch failed (includes token-gated tenants)"},
        503: {"description": "Durable storage is not ready yet"},
    },
)
def import_external(
    agenda_id: str,
    payload: AgendaImportExternalRequest,
    store: AgendaStore | None = Depends(get_agenda_store),
    settings: AgendaImportSettings = Depends(get_agenda_import_settings),
    provenance_store: AgendaImportProvenanceStore | None = Depends(
        get_agenda_import_provenance_store
    ),
) -> list[AgendaItem]:
    _require_enabled(settings)
    resolved_store = _require_store(store)
    try:
        source = build_source(
            payload.source, timeout_seconds=settings.timeout_seconds, token=settings.token
        )
        external = source.fetch_agenda(payload.client_code, payload.event_id)
        written = import_external_agenda(resolved_store, agenda_id, external)
        if provenance_store is not None:
            try:
                provenance_store.record_import(
                    agenda_id=agenda_id,
                    source=payload.source,
                    client_code=payload.client_code,
                    external_id=external.external_id,
                )
            except Exception:
                # Bookkeeping only, never blocks an import (see
                # get_agenda_import_provenance_store's docstring) -- the
                # agenda items above are already durably committed, so a
                # provenance-write race (e.g. a double-submitted import)
                # must not turn an already-successful import into a
                # reported failure.
                logger.exception("agenda_import.record_import failed for agenda_id=%s", agenda_id)
        return written
    except AgendaNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgendaItemOrderConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AgendaSourceNotAvailableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (AgendaSourceAuthRequiredError, AgendaSourceUpstreamError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        # Hostile doc_url (bad scheme) rejected by validate_source_doc_url,
        # or any other malformed-payload ValueError from the mapper -- fail
        # loud, nothing was written.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/agenda-sources/{source}/{client_code}/meetings",
    response_model=list[ExternalMeetingSummary],
    summary="List upcoming/recent meetings from an external agenda system",
    dependencies=[Depends(require_any_role(*_AUTHOR))],
    openapi_extra=_AUTHOR_EXTRA,
    responses={
        404: {"description": "Agenda import disabled"},
        422: {"description": "Source not yet available in this release"},
        502: {"description": "Upstream fetch failed (includes token-gated tenants)"},
    },
)
def list_external_meetings(
    source: AgendaSourceName,
    client_code: Annotated[str, AfterValidator(validate_client_code)],
    since: Annotated[
        date | None, Query(description="Only meetings on/after this date (default: today)")
    ] = None,
    settings: AgendaImportSettings = Depends(get_agenda_import_settings),
) -> list[ExternalMeetingSummary]:
    _require_enabled(settings)
    try:
        adapter = build_source(
            source, timeout_seconds=settings.timeout_seconds, token=settings.token
        )
        return adapter.fetch_meetings(client_code, since=since)
    except AgendaSourceNotAvailableError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (AgendaSourceAuthRequiredError, AgendaSourceUpstreamError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


__all__ = ["get_agenda_import_provenance_store", "get_agenda_import_settings", "router"]

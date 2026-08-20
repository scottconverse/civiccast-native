# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff reporting routes for aggregate analytics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from civiccast.analytics.audience_reports import (
    AudienceReport,
    _period_bounds,
    build_audience_report,
    export_audience_csv,
    export_audience_xml,
)
from civiccast.analytics.models import AnalyticsReport
from civiccast.analytics.store import AnalyticsStoreProtocol, cast_analytics_store
from civiccast.auth.roles import ALL_OPERATOR_ROLES, require_any_role
from civiccast.platform.stores import resolve_app_store

staff_router = APIRouter(prefix="/api/staff/analytics", tags=["staff", "analytics"])


def get_analytics_store(request: Request) -> AnalyticsStoreProtocol:
    return cast_analytics_store(
        resolve_app_store(request, "analytics_store", surface="Analytics store")
    )


@staff_router.get(
    "/reports/overview",
    response_model=AnalyticsReport,
    summary="Read aggregate-only station analytics report",
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def read_analytics_report(
    range_days: Annotated[int, Query(ge=1, le=366)] = 30,
    store: AnalyticsStoreProtocol = Depends(get_analytics_store),
) -> AnalyticsReport:
    return store.report(range_days=range_days)


@staff_router.get(
    "/reports/audience",
    response_model=AudienceReport,
    summary=(
        "Build a packaged audience report — the franchise-authority deliverable. "
        "Use ?format=csv or ?format=xml for export-ready downloads."
    ),
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def read_audience_report(
    kind: Annotated[
        Literal["weekly", "monthly", "custom"], Query(description="period preset")
    ] = "monthly",
    period_start: Annotated[
        date | None, Query(description="ISO date; required for kind=custom")
    ] = None,
    period_end: Annotated[date | None, Query(description="ISO date; defaults to today UTC")] = None,
    range_days: Annotated[int, Query(ge=1, le=366)] = 30,
    top_assets_limit: Annotated[int, Query(ge=1, le=200)] = 25,
    fmt: Annotated[Literal["json", "csv", "xml"], Query(alias="format")] = "json",
    store: AnalyticsStoreProtocol = Depends(get_analytics_store),
) -> AudienceReport | Response:
    """Build + serve the franchise-deliverable audience report.

    The ``json`` response is the default and returns the full ``AudienceReport``
    pydantic model. ``csv`` and ``xml`` return a download-shaped Response with
    the appropriate Content-Type + Content-Disposition so the operator's
    browser saves the file with a sensible name.
    """
    try:
        period_start_bound, _period_end_bound = _period_bounds(
            kind, period_start=period_start, period_end=period_end
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # range_days is a store-pull *width*; the resolved period can reach
    # further back than that (e.g. a historical kind=custom range), so widen
    # the store pull to cover it — build_audience_report then filters the
    # per-day points down to the exact resolved period.
    today = datetime.now(UTC).date()
    lookback_days = min(max(range_days, (today - period_start_bound).days, 1), 366)

    try:
        base = store.report(range_days=lookback_days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        report = build_audience_report(
            base,
            kind=kind,
            period_start=period_start,
            period_end=period_end,
            top_assets_limit=top_assets_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if fmt == "json":
        return report

    period = f"{report.period_start.isoformat()}-to-{report.period_end.isoformat()}"
    if fmt == "csv":
        body = "﻿" + export_audience_csv(report)  # BOM for Excel
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (f'attachment; filename="audience-report-{period}.csv"')
            },
        )
    # xml
    body = export_audience_xml(report)
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Content-Disposition": (f'attachment; filename="audience-report-{period}.xml"')},
    )

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Aggregate-only analytics contracts for station reporting."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReportDimension = Literal[
    "asset",
    "live_concurrency",
    "geography",
    "device",
    "platform",
    "caption",
    "audio",
    "subscription",
    "podcast",
]


class AnalyticsRetainedEvent(BaseModel):
    """Stored event after dropping viewer/session identifiers."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=160)
    event_name: str = Field(min_length=1, max_length=80)
    occurred_at: datetime
    app_target: str = Field(min_length=1, max_length=80)
    channel_id: str | None = Field(default=None, max_length=160)
    content_id: str | None = Field(default=None, max_length=160)
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AssetViewPoint(BaseModel):
    """Per-day aggregate playback totals for one asset."""

    model_config = ConfigDict(extra="forbid")

    content_id: str
    day: date
    views: int = Field(ge=0)
    view_seconds: int = Field(ge=0)


class LiveConcurrentPoint(BaseModel):
    """Per-day concurrent viewer trend for one channel."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    day: date
    peak_concurrent_viewers: int = Field(ge=0)
    average_concurrent_viewers: float = Field(ge=0)
    samples: int = Field(ge=0)


class AnalyticsDimensionCount(BaseModel):
    """Aggregate dimension count with no viewer/session identity."""

    model_config = ConfigDict(extra="forbid")

    dimension: ReportDimension
    key: str
    count: int = Field(ge=0)


class AnalyticsReport(BaseModel):
    """Station reporting snapshot with aggregate-only analytics."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    range_days: int = Field(ge=1, le=366)
    asset_views: list[AssetViewPoint] = Field(default_factory=list)
    live_concurrent_viewers: list[LiveConcurrentPoint] = Field(default_factory=list)
    geography: list[AnalyticsDimensionCount] = Field(default_factory=list)
    device_breakdown: list[AnalyticsDimensionCount] = Field(default_factory=list)
    platform_breakdown: list[AnalyticsDimensionCount] = Field(default_factory=list)
    caption_usage: list[AnalyticsDimensionCount] = Field(default_factory=list)
    audio_usage: list[AnalyticsDimensionCount] = Field(default_factory=list)
    subscription_growth: list[AnalyticsDimensionCount] = Field(default_factory=list)
    podcast_downloads: list[AnalyticsDimensionCount] = Field(default_factory=list)
    retained_fields: list[str]
    privacy_boundary: str

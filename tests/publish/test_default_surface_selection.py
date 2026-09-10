# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Hostile review of PR #216, B3: an approval that names no surfaces publishes
the canonical Portal surface only.

``approved_surface_ids=None`` used to mean EVERY surface -- Internet Archive,
both local NAS archives, YouTube Live/VOD and the cable package -- so an API
approval with the field omitted permanently published a closed session. The
"Portal only" default from the beta.5 walkthrough (F-23, safety) lived only
in the React screen. The server now shares it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from civiccast.platform.providers import ProviderRegistry, default_registry
from civiccast.publish.models import PublishApprovalRequest
from civiccast.publish.service import (
    approve_publish,
    build_initial_surfaces,
    default_approved_surface_ids,
)
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow


def _asset() -> StaffAssetRow:
    return StaffAssetRow(
        asset_id="council-2026-07-08",
        title="Council - July 8, 2026",
        state="validated",
        manifest_url="https://cdn.example/council-2026-07-08/playlist.m3u8",
        published_at=datetime(2026, 7, 8, 20, 0, tzinfo=UTC),
        retention_policy="meeting",
        version=1,
    )


class _SpyRegistry:
    """Wraps the shipped registry and records every client resolution."""

    def __init__(self, inner: ProviderRegistry) -> None:
        self._inner = inner
        self.resolved: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def resolve(self, kind: str) -> Any:
        self.resolved.append(kind)
        return self._inner.resolve(kind)


def test_default_selection_is_the_canonical_surface_only() -> None:
    assert default_approved_surface_ids(_asset()) == {"portal"}
    kinds = {surface.id: surface.kind for surface in build_initial_surfaces(_asset())}
    assert kinds["portal"] == "canonical"
    assert {kind for sid, kind in kinds.items() if sid != "portal"} >= {"archive", "reach"}


def test_omitted_surface_ids_publish_portal_only_and_touch_no_provider() -> None:
    registry = _SpyRegistry(default_registry())
    request = PublishApprovalRequest(
        operator_id="staff-1",
        operator_display_name="Avery Operator",
    )
    assert request.approved_surface_ids is None

    record = approve_publish(
        asset=_asset(),
        request=request,
        store=InMemoryPublishStore(),
        registry=registry,  # type: ignore[arg-type]
    )

    by_id = {surface.id: surface for surface in record.surfaces}
    assert by_id["portal"].state == "succeeded"
    assert by_id["portal"].approval == "approved"
    for surface_id, surface in by_id.items():
        if surface_id == "portal":
            continue
        assert surface.approval == "pending", surface_id
        assert surface.state == "pending", surface_id
    assert registry.resolved == []
    assert {event.surface_id for event in record.audit_events} == {"portal"}


@pytest.mark.parametrize("surface_id", ["internet-archive", "youtube-vod", "local-nas-rsync"])
def test_named_archive_and_reach_surfaces_are_still_opt_in(surface_id: str) -> None:
    request = PublishApprovalRequest(
        operator_id="staff-1",
        operator_display_name="Avery Operator",
        approved_surface_ids=["portal", surface_id],
    )
    record = approve_publish(asset=_asset(), request=request, store=InMemoryPublishStore())
    by_id = {surface.id: surface for surface in record.surfaces}
    assert by_id[surface_id].approval == "approved"

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Provider registry tests (Stage C).

External-provider touchpoints (Internet Archive, local NAS, YouTube, mail,
webhooks) previously hard-instantiated their mock clients at the call site
("mock only; no factory/registry/config switch" — capability matrix). The
registry gives every kind a config-driven seam: mocks stay the defaults,
unknown names fail fast with the registered options, and a real adapter can be
registered without touching call sites.
"""

from __future__ import annotations

import pytest

from civiccast.archive.models import MockInternetArchiveClient, MockLocalNasArchiveClient
from civiccast.platform.providers import (
    PROVIDER_KINDS,
    ProviderConfigurationError,
    ProviderRegistry,
    default_registry,
)
from civiccast.subscribe.delivery import LocalMailbox, LocalWebhookClient
from civiccast.syndicate.models import MockYouTubeClient

_PROVIDER_ENV = tuple(f"CIVICCAST_PROVIDER_{kind.upper()}" for kind in PROVIDER_KINDS)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_kinds_cover_the_mock_only_capability_rows(self) -> None:
        assert set(PROVIDER_KINDS) == {
            "internet_archive",
            "local_nas",
            "youtube",
            "mail",
            "webhook",
        }

    @pytest.mark.parametrize(
        ("kind", "expected_type"),
        [
            ("internet_archive", MockInternetArchiveClient),
            ("local_nas", MockLocalNasArchiveClient),
            ("youtube", MockYouTubeClient),
            ("mail", LocalMailbox),
            ("webhook", LocalWebhookClient),
        ],
    )
    def test_default_resolution_is_the_mock(self, kind: str, expected_type: type) -> None:
        registry = default_registry()
        assert isinstance(registry.resolve(kind), expected_type)

    def test_explicit_mock_selection_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "mock")
        registry = default_registry()
        assert isinstance(registry.resolve("youtube"), MockYouTubeClient)


class TestFailFast:
    def test_unknown_provider_name_fails_listing_registered_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # "real" is a registered name since Beta B5; a typo'd / never-shipped
        # name must still fail fast listing what IS registered.
        monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "carrier-pigeon")
        with pytest.raises(ProviderConfigurationError) as excinfo:
            default_registry().resolve("youtube")
        message = str(excinfo.value)
        assert "CIVICCAST_PROVIDER_YOUTUBE" in message
        assert "mock" in message
        assert "real" in message

    def test_unknown_kind_fails(self) -> None:
        with pytest.raises(ProviderConfigurationError, match="kind"):
            default_registry().resolve("carrier-pigeon")


class TestExtensionPoint:
    def test_registered_custom_factory_becomes_resolvable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class RealYouTubeClient:
            pass

        registry = ProviderRegistry()
        registry.register("youtube", "mock", MockYouTubeClient)
        registry.register("youtube", "real", RealYouTubeClient)
        monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "real")
        assert isinstance(registry.resolve("youtube"), RealYouTubeClient)


class TestPublishResolvesThroughRegistry:
    def test_approve_publish_uses_injected_registry(self) -> None:
        """The publish workflow's archive/reach clients come from the
        registry seam, not hard-instantiated classes (Stage C).

        WP-03: approval only resolves the provider kinds the operator
        actually selected -- resolving local_nas/youtube here too (the old
        behavior) would let an unrelated, unselected provider's
        misconfiguration block an internet-archive-only approval, which the
        WP-03 plan (item 9) forbids.
        """

        from datetime import UTC, datetime

        from civiccast.publish.models import PublishApprovalRequest
        from civiccast.publish.service import approve_publish
        from civiccast.publish.store import InMemoryPublishStore
        from civiccast.schedule.models import StaffAssetRow

        resolved_kinds: list[str] = []

        class RecordingRegistry(ProviderRegistry):
            def resolve(self, kind: str):
                resolved_kinds.append(kind)
                return super().resolve(kind)

        registry = RecordingRegistry()
        registry.register("internet_archive", "mock", MockInternetArchiveClient)
        registry.register("local_nas", "mock", MockLocalNasArchiveClient)
        registry.register("youtube", "mock", MockYouTubeClient)

        record = approve_publish(
            asset=StaffAssetRow(
                asset_id="council-2026-06-09",
                title="Council - June 9, 2026",
                state="validated",
                manifest_url="https://cdn.example/council-2026-06-09/playlist.m3u8",
                published_at=datetime(2026, 6, 9, 20, 0, tzinfo=UTC),
                retention_policy="meeting",
                version=1,
            ),
            request=PublishApprovalRequest(
                operator_id="staff-1",
                operator_display_name="Avery Operator",
                approved_surface_ids=["internet-archive"],
            ),
            store=InMemoryPublishStore(),
            registry=registry,
        )

        assert set(resolved_kinds) == {"internet_archive"}, (
            "only the selected surface's provider kind should be resolved"
        )
        surface = next(s for s in record.surfaces if s.id == "internet-archive")
        assert surface.state == "succeeded"

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""DI-wiring contracts for app-owned store bundles."""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy.engine import Engine

from civiccast.app import create_app
from civiccast.captions import router as captions_router
from civiccast.podcast import router as podcast_router
from civiccast.publish import router as publish_router
from civiccast.records import router as records_router
from civiccast.schedule import router as schedule_router
from civiccast.schedule.router import get_asset_store, get_postgres_store, get_schedule_store
from civiccast.schedule.store import PostgresAssetStore
from civiccast.subscribe import router as subscribe_router
from civiccast.summary import router as summary_router
from civiccast.vod import router as vod_router
from civiccast.vod.router import get_store
from civiccast.vod.store import InMemoryAssetStore


class TestAppFactoryUnsetEnv:
    def test_store_bundle_is_app_scoped_when_database_url_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)

        first = create_app()
        second = create_app()

        assert get_store not in first.dependency_overrides
        assert get_asset_store not in first.dependency_overrides
        first_store = first.state.store_bundle.asset_store()
        assert isinstance(first_store, InMemoryAssetStore)
        assert first.state.store_bundle.asset_store() is first_store
        assert second.state.store_bundle.asset_store() is not first_store

    def test_import_civiccast_app_does_not_raise_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import civiccast.app as app_mod

        importlib.reload(app_mod)


class TestAppFactorySetEnv:
    def test_store_bundle_resolves_postgres_asset_store_when_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

        app = create_app()

        assert get_store not in app.dependency_overrides
        assert get_asset_store not in app.dependency_overrides
        assert get_postgres_store in app.dependency_overrides
        assert get_schedule_store in app.dependency_overrides
        assert isinstance(app.state.store_bundle.asset_store(), PostgresAssetStore)

    def test_create_app_does_not_call_engine_connect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        calls: list[None] = []
        original_connect = Engine.connect

        def _spy(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(None)
            return original_connect(self, *args, **kwargs)

        monkeypatch.setattr(Engine, "connect", _spy)

        create_app()

        assert calls == [], "create_app() must not open a DB connection during app construction."


class TestRouterModuleStoreGlobalsRemoved:
    def test_router_modules_do_not_own_default_store_singletons(self) -> None:
        modules = (
            vod_router,
            schedule_router,
            captions_router,
            summary_router,
            records_router,
            publish_router,
            subscribe_router,
            podcast_router,
        )

        for module in modules:
            names = set(vars(module))
            assert "set_default_store" not in names
            assert not any(name.startswith("_default") for name in names)
            assert not any(
                name.startswith("_DEFAULT_") and name.endswith("_STORE") for name in names
            )

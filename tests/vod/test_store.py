# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.vod.store — Protocol + InMemoryAssetStore."""

from __future__ import annotations

import pytest

from civiccast.vod.models import AssetMetadata
from civiccast.vod.store import AssetAlreadyExistsError, AssetStore, InMemoryAssetStore


def _make_asset(asset_id: str = "abc123") -> AssetMetadata:
    return AssetMetadata(
        asset_id=asset_id,
        title="Test asset",
        manifest_url="https://cdn.example/abc/playlist.m3u8",  # type: ignore[arg-type]
    )


class TestInMemoryAssetStore:
    def test_implements_asset_store_protocol(self) -> None:
        store = InMemoryAssetStore()
        assert isinstance(store, AssetStore)

    def test_get_returns_none_for_unknown_id(self) -> None:
        store = InMemoryAssetStore()
        assert store.get("does-not-exist") is None

    def test_put_then_get_roundtrips(self) -> None:
        store = InMemoryAssetStore()
        asset = _make_asset()
        store.put(asset)
        assert store.get(asset.asset_id) is asset

    def test_put_overwrites_existing(self) -> None:
        store = InMemoryAssetStore()
        store.put(_make_asset())
        new = AssetMetadata(
            asset_id="abc123",
            title="Replaced",
            manifest_url="https://cdn.example/abc/v2/playlist.m3u8",  # type: ignore[arg-type]
        )
        store.put(new)
        result = store.get("abc123")
        assert result is not None
        assert result.title == "Replaced"

    def test_initial_assets_are_seeded(self) -> None:
        asset = _make_asset()
        store = InMemoryAssetStore({asset.asset_id: asset})
        assert store.get(asset.asset_id) is asset

    def test_list_empty_returns_empty_list(self) -> None:
        store = InMemoryAssetStore()
        result = store.list()
        assert isinstance(result, list)
        assert result == []

    def test_list_returns_all_inserted(self) -> None:
        store = InMemoryAssetStore()
        store.put(_make_asset(asset_id="a-1"))
        store.put(_make_asset(asset_id="b-2"))
        result = store.list()
        assert {a.asset_id for a in result} == {"a-1", "b-2"}

    def test_create_persists_and_returns_asset(self) -> None:
        store = InMemoryAssetStore()
        asset = _make_asset(asset_id="new-1")
        returned = store.create(asset)
        assert returned.asset_id == "new-1"
        out = store.get("new-1")
        assert out is not None
        assert out.asset_id == "new-1"

    def test_create_duplicate_raises_AssetAlreadyExistsError(self) -> None:
        store = InMemoryAssetStore()
        asset = _make_asset(asset_id="dup-1")
        store.create(asset)
        with pytest.raises(AssetAlreadyExistsError):
            store.create(asset)

    def test_AssetAlreadyExistsError_carries_asset_id_attribute(self) -> None:
        err = AssetAlreadyExistsError(asset_id="foo")
        assert err.asset_id == "foo"

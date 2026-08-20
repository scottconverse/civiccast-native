# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Conformance tests for the AssetStore Protocol.

Locks the contract that PostgresAssetStore (against ephemeral SQLite for speed)
and InMemoryAssetStore present byte-equal behavior under the AssetStore
Protocol surface defined at civiccast/vod/store.py:18-28.

Per plan.md §4 `tests/schedule/test_store_conformance.py`. Director Decision 6
binds the conformance suite to live here, not in tests/vod/.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.schedule.models import Asset
from civiccast.schedule.store import PostgresAssetStore
from civiccast.vod.models import AssetMetadata
from civiccast.vod.store import AssetAlreadyExistsError, AssetStore, InMemoryAssetStore

from .conftest import _make_asset


def _seed_postgres_store(session_factory, asset: AssetMetadata) -> None:
    """Insert an AssetMetadata into the SQL store via the Asset SA model."""
    with session_factory() as sess:
        sess.add(Asset.from_metadata(asset))
        sess.commit()


def _seed_inmem_store(store: InMemoryAssetStore, asset: AssetMetadata) -> None:
    store.put(asset)


@pytest.fixture(params=["inmem", "postgres-sqlite"])
def store(request, session_factory):
    """Indirect-parametrized fixture yielding both store implementations.

    Each test using `store` runs once per parametrize id with identical
    assertions. The seeding adapter is exposed via `request.node` so tests
    can insert assets through the implementation-appropriate path.
    """
    impl = request.param
    if impl == "inmem":
        s: AssetStore = InMemoryAssetStore()

        def _seed(asset: AssetMetadata) -> None:
            _seed_inmem_store(s, asset)  # type: ignore[arg-type]

    else:
        s = PostgresAssetStore(session_factory)

        def _seed(asset: AssetMetadata) -> None:
            _seed_postgres_store(session_factory, asset)

    request.node._asset_seed = _seed  # type: ignore[attr-defined]
    return s


def _seed(request, asset: AssetMetadata) -> None:
    request.node._asset_seed(asset)


class TestAssetStoreProtocolConformance:
    """Locks: every parametrized store satisfies the AssetStore Protocol."""

    def test_store_isinstance_asset_store(self, store) -> None:
        assert isinstance(store, AssetStore)


class TestGetReturnsAssetWhenPresent:
    """Locks: store.get(known_id) returns an AssetMetadata with the inserted
    field values, on every parametrized store."""

    def test_get_returns_asset_metadata_when_present(self, store, request) -> None:
        asset = _make_asset(
            asset_id="known-id",
            title="Known asset",
            description="A description",
            manifest_url="https://cdn.example/known/playlist.m3u8",
            poster_url="https://cdn.example/known/poster.jpg",
            duration_seconds=1800,
            published_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        )
        _seed(request, asset)
        result = store.get("known-id")
        assert result is not None
        assert isinstance(result, AssetMetadata)
        assert result.asset_id == "known-id"
        assert result.title == "Known asset"
        assert result.description == "A description"
        assert str(result.manifest_url) == "https://cdn.example/known/playlist.m3u8"
        assert str(result.poster_url) == "https://cdn.example/known/poster.jpg"
        assert result.duration_seconds == 1800
        assert result.published_at == datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


class TestGetReturnsNoneWhenAbsent:
    """Locks: store.get(unknown_id) returns None on every parametrized store."""

    def test_get_returns_none_when_absent(self, store) -> None:
        assert store.get("never-inserted") is None


class TestGetIsCaseSensitive:
    """Locks: get is case-sensitive — slug-pattern semantics carry through to
    the persistence layer (uppercase ids are not allowed by the Pydantic
    pattern, so only the lowercase variant exists)."""

    def test_uppercase_lookup_after_lowercase_insert_returns_none(self, store, request) -> None:
        asset = _make_asset(asset_id="abc123")
        _seed(request, asset)
        # Uppercase lookup of a lowercase-seeded id must miss.
        assert store.get("ABC123") is None


class TestRoundTripPreservesAllFields:
    """Locks: every field survives write -> read with byte-equal values,
    including None for the four nullable fields."""

    def test_round_trip_preserves_all_seven_fields_with_nulls(self, store, request) -> None:
        asset = _make_asset(
            asset_id="rt-min",
            title="Minimal",
            manifest_url="https://cdn.example/m/playlist.m3u8",
            description=None,
            poster_url=None,
            duration_seconds=None,
            published_at=None,
        )
        _seed(request, asset)
        out = store.get("rt-min")
        assert out is not None
        assert out.asset_id == "rt-min"
        assert out.title == "Minimal"
        assert out.description is None
        assert str(out.manifest_url) == "https://cdn.example/m/playlist.m3u8"
        assert out.poster_url is None
        assert out.duration_seconds is None
        assert out.published_at is None

    def test_round_trip_preserves_all_seven_fields_when_populated(self, store, request) -> None:
        asset = _make_asset(
            asset_id="rt-full",
            title="Full",
            description="Long description text",
            manifest_url="https://cdn.example/f/playlist.m3u8",
            poster_url="https://cdn.example/f/poster.jpg",
            duration_seconds=3600,
            published_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        _seed(request, asset)
        out = store.get("rt-full")
        assert out is not None
        assert out.asset_id == asset.asset_id
        assert out.title == asset.title
        assert out.description == asset.description
        assert str(out.manifest_url) == str(asset.manifest_url)
        assert str(out.poster_url) == str(asset.poster_url)
        assert out.duration_seconds == asset.duration_seconds
        assert out.published_at == asset.published_at


class TestList:
    """Locks: store.list() returns every persisted asset on every parametrized
    store. Per Q5, ordering is implementation-pluggable so assertions use
    set-comparison, not list-equality."""

    def test_list_empty_store_returns_empty_list(self, store) -> None:
        result = store.list()
        assert isinstance(result, list)
        assert result == []

    def test_list_returns_all_inserted_assets(self, store, request) -> None:
        _seed(request, _make_asset(asset_id="alpha-1", title="Alpha"))
        _seed(request, _make_asset(asset_id="beta-2", title="Beta"))
        _seed(request, _make_asset(asset_id="gamma-3", title="Gamma"))
        result = store.list()
        assert {a.asset_id for a in result} == {"alpha-1", "beta-2", "gamma-3"}

    def test_list_preserves_all_fields(self, store, request) -> None:
        asset = _make_asset(
            asset_id="full-1",
            title="Full",
            description="A description",
            manifest_url="https://cdn.example/full/playlist.m3u8",
            poster_url="https://cdn.example/full/poster.jpg",
            duration_seconds=3600,
            published_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        _seed(request, asset)
        result = store.list()
        assert len(result) == 1
        out = result[0]
        assert out.asset_id == asset.asset_id
        assert out.title == asset.title
        assert out.description == asset.description
        assert str(out.manifest_url) == str(asset.manifest_url)
        assert str(out.poster_url) == str(asset.poster_url)
        assert out.duration_seconds == asset.duration_seconds
        assert out.published_at == asset.published_at


class TestCreate:
    """Locks: store.create() persists, returns the canonical asset, and
    raises AssetAlreadyExistsError on duplicate asset_id (per Decision 3)."""

    def test_create_persists_asset(self, store) -> None:
        asset = _make_asset(asset_id="created-1", title="Created")
        store.create(asset)
        out = store.get("created-1")
        assert out is not None
        assert out.asset_id == "created-1"
        assert out.title == "Created"

    def test_create_returns_canonical_asset(self, store) -> None:
        asset = _make_asset(asset_id="canonical-1", title="Canonical")
        returned = store.create(asset)
        canonical = store.get("canonical-1")
        assert canonical is not None
        # Q6: return value of create equals what get() would return.
        assert returned.asset_id == canonical.asset_id
        assert returned.title == canonical.title
        assert str(returned.manifest_url) == str(canonical.manifest_url)

    def test_create_duplicate_asset_id_raises_AssetAlreadyExistsError(self, store) -> None:
        asset = _make_asset(asset_id="dup-1")
        store.create(asset)
        with pytest.raises(AssetAlreadyExistsError) as exc_info:
            store.create(asset)
        assert exc_info.value.asset_id == "dup-1"


class TestRollbackAfterDuplicate:
    """Locks: a duplicate-error leaves the store/session in a usable state
    for a subsequent successful create (per Decision 3 adjacent action)."""

    def test_store_clean_after_duplicate_error(self, store) -> None:
        asset_a = _make_asset(asset_id="a-1", title="A")
        asset_b = _make_asset(asset_id="b-1", title="B")
        store.create(asset_a)
        with pytest.raises(AssetAlreadyExistsError):
            store.create(asset_a)
        # Store/session must still be usable for further operations.
        store.create(asset_b)
        out = store.get("b-1")
        assert out is not None
        assert out.asset_id == "b-1"


class TestExtendedProtocolConformance:
    """Locks: both stores still satisfy isinstance(store, AssetStore) after
    the Protocol extension adds list() and create() (per Decision 1)."""

    def test_store_satisfies_extended_AssetStore_Protocol(self, store) -> None:
        # @runtime_checkable Protocol — must continue to hold once list/create
        # land on the Protocol AND on every implementer.
        assert isinstance(store, AssetStore)
        assert hasattr(store, "list")
        assert hasattr(store, "create")
        assert callable(store.list)
        assert callable(store.create)


class TestFieldNamesMatch:
    """Risk-4 mitigation: every Pydantic AssetMetadata field must have a
    matching SA Asset column. SA may carry additional columns (e.g. ingest
    fields added in Sprint 0.3) that the v0.2-compatible AssetMetadata does
    not yet expose — that asymmetry is intentional. What must never happen is
    an AssetMetadata field with no backing column."""

    def test_sa_columns_match_pydantic_fields(self) -> None:
        sa_columns = {col.name for col in Asset.__table__.columns}
        pydantic_fields = set(AssetMetadata.model_fields.keys())
        assert pydantic_fields.issubset(sa_columns), (
            f"AssetMetadata fields missing from SA Asset columns: {pydantic_fields - sa_columns}"
        )

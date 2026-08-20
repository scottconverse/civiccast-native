# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S26 paywall data layer — models + PaywallStore + migration 0059.

Slice 1 lock-ins:

* model validation (slugs, email shape, scheme allowlist on tier price_ids,
  status / scope_kind / granted_via literals, DC-1 default-off baseline)
* store CRUD round-trips + idempotent upsert + the "unique config per
  station" pre-check + the hot-path ``has_grant_for`` gating
* migration ``0059_paywall_access`` up + down + the three new tables +
  every CHECK / INDEX it creates

These are real-SQLite unit tests (the migration is run end-to-end against
a temp SQLite DB). The real-PG locks live in
``tests/live/test_real_postgres.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.paywall.models import (
    AccessGrant,
    PaywallConfig,
    PaywallConfigInput,
    PaywallConfigUpdate,
    PaywallTier,
    PublicAccessDecision,
    Subscription,
    _validate_email,
)
from civiccast.paywall.store import (
    AccessGrantNotFoundError,
    PaywallConfigNotFoundError,
    PaywallStationConfigConflictError,
    PaywallStore,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PaywallStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'p.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield PaywallStore(factory)
    finally:
        eng.dispose()


# --- models -----------------------------------------------------------------


class TestPaywallConfigModel:
    def test_default_off(self) -> None:
        c = PaywallConfig(config_id="pw-1", station_id="civiccast-station")
        assert c.enabled is False
        assert c.provider == "stripe"
        assert c.tiers == []
        assert c.signing_secret is None

    def test_uppercase_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaywallConfig(config_id="PW-Bad", station_id="sta")

    def test_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValueError):
            PaywallConfig(config_id="pw-x", station_id="sta", provider="paypal")  # type: ignore[arg-type]

    def test_tier_input_validates(self) -> None:
        t = PaywallTier(tier_id="basic", name="Basic", price_id="price_123")
        assert t.interval == "month"

    def test_yearly_tier_accepted(self) -> None:
        t = PaywallTier(tier_id="pro", name="Pro", price_id="price_p", interval="year")
        assert t.interval == "year"

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValueError):
            PaywallConfig(
                config_id="pw-x",
                station_id="sta",
                undocumented="hi",  # type: ignore[call-arg]
            )

    def test_input_creates_then_serializes(self) -> None:
        i = PaywallConfigInput(config_id="pw-x", station_id="sta")
        # Round-trip through PaywallConfig (status implicitly draft-equivalent → default off)
        c = PaywallConfig(config_id=i.config_id, station_id=i.station_id)
        assert c.enabled is False

    def test_update_partial(self) -> None:
        u = PaywallConfigUpdate(enabled=True)
        assert u.enabled is True
        assert u.tiers is None  # absent = unchanged

    def test_signing_secret_max_length(self) -> None:
        with pytest.raises(ValueError):
            PaywallConfig(
                config_id="pw-x",
                station_id="sta",
                signing_secret="x" * 201,
            )


class TestAccessGrantModel:
    def test_valid_minimal(self) -> None:
        g = AccessGrant(
            grant_id="g-1",
            station_id="sta",
            email="user@example.com",
            scope_kind="all",
            granted_via="comp",
        )
        assert g.scope_id == ""
        assert g.subscription_id is None
        assert g.expires_at is None

    def test_email_lowercased_and_trimmed(self) -> None:
        g = AccessGrant(
            grant_id="g-2",
            station_id="sta",
            email="  Alice@Example.COM ",
            scope_kind="asset",
            scope_id="vod-january",
            granted_via="subscription",
        )
        assert g.email == "alice@example.com"

    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValueError):
            AccessGrant(
                grant_id="g-3",
                station_id="sta",
                email="not-an-email",
                scope_kind="asset",
                scope_id="x",
                granted_via="subscription",
            )

    def test_invalid_scope_kind_rejected(self) -> None:
        with pytest.raises(ValueError):
            AccessGrant(
                grant_id="g-4",
                station_id="sta",
                email="a@b.co",
                scope_kind="universe",  # type: ignore[arg-type]
                granted_via="comp",
            )

    def test_invalid_granted_via_rejected(self) -> None:
        with pytest.raises(ValueError):
            AccessGrant(
                grant_id="g-5",
                station_id="sta",
                email="a@b.co",
                scope_kind="all",
                granted_via="freebie",  # type: ignore[arg-type]
            )

    def test_validate_email_helper(self) -> None:
        assert _validate_email("X@y.z") == "x@y.z"
        with pytest.raises(ValueError):
            _validate_email("nope")
        with pytest.raises(ValueError):
            _validate_email("@nope.com")
        with pytest.raises(ValueError):
            _validate_email("a@b")


class TestSubscriptionModel:
    def test_valid(self) -> None:
        s = Subscription(
            sub_id="sub_abc",
            station_id="sta",
            email="a@b.co",
            tier_id="pro",
            status="active",
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )
        assert s.status == "active"

    def test_unknown_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            Subscription(
                sub_id="sub_x",
                station_id="sta",
                email="a@b.co",
                tier_id="x",
                status="paused",  # type: ignore[arg-type]
                current_period_end=datetime.now(UTC),
            )

    def test_email_normalized(self) -> None:
        s = Subscription(
            sub_id="sub_y",
            station_id="sta",
            email=" MIXED@example.COM",
            tier_id="x",
            status="active",
            current_period_end=datetime.now(UTC),
        )
        assert s.email == "mixed@example.com"


class TestPublicAccessDecisionProjection:
    def test_key_set_is_only_allowed_and_reason(self) -> None:
        d = PublicAccessDecision(allowed=False, reason="subscription required")
        assert set(d.model_dump().keys()) == {"allowed", "reason"}

    def test_allowed_true_can_omit_reason(self) -> None:
        d = PublicAccessDecision(allowed=True)
        assert d.reason is None

    def test_no_email_leak_possible(self) -> None:
        with pytest.raises(ValueError):
            PublicAccessDecision(allowed=True, email="x@y.z")  # type: ignore[call-arg]


# --- store -----------------------------------------------------------------


class TestPaywallStoreConfig:
    def test_upsert_then_get(self, store: PaywallStore) -> None:
        c = PaywallConfig(config_id="pw-1", station_id="civiccast-station", enabled=True)
        stored = store.upsert_config(c)
        assert stored.enabled is True
        assert store.get_config("pw-1") is not None
        assert store.get_config_for_station("civiccast-station") is not None

    def test_get_unknown_returns_none(self, store: PaywallStore) -> None:
        assert store.get_config("missing") is None
        assert store.get_config_for_station("missing-station") is None

    def test_upsert_is_idempotent(self, store: PaywallStore) -> None:
        c = PaywallConfig(config_id="pw-1", station_id="sta", enabled=False)
        store.upsert_config(c)
        c2 = PaywallConfig(config_id="pw-1", station_id="sta", enabled=True)
        store.upsert_config(c2)
        assert store.get_config("pw-1").enabled is True  # type: ignore[union-attr]

    def test_second_config_for_station_conflicts(self, store: PaywallStore) -> None:
        store.upsert_config(PaywallConfig(config_id="pw-1", station_id="sta"))
        with pytest.raises(PaywallStationConfigConflictError):
            store.upsert_config(PaywallConfig(config_id="pw-2", station_id="sta"))

    def test_tiers_round_trip_through_json(self, store: PaywallStore) -> None:
        c = PaywallConfig(
            config_id="pw-1",
            station_id="sta",
            tiers=[
                PaywallTier(tier_id="basic", name="Basic", price_id="price_b"),
                PaywallTier(
                    tier_id="pro",
                    name="Pro",
                    price_id="price_p",
                    interval="year",
                ),
            ],
        )
        store.upsert_config(c)
        loaded = store.get_config("pw-1")
        assert loaded is not None
        assert len(loaded.tiers) == 2
        assert loaded.tiers[1].interval == "year"

    def test_delete_config(self, store: PaywallStore) -> None:
        store.upsert_config(PaywallConfig(config_id="pw-1", station_id="sta"))
        store.delete_config("pw-1")
        assert store.get_config("pw-1") is None

    def test_delete_unknown_config_raises(self, store: PaywallStore) -> None:
        with pytest.raises(PaywallConfigNotFoundError):
            store.delete_config("missing")


class TestPaywallStoreGrants:
    def _grant(self, **kw: object) -> AccessGrant:
        base = {
            "grant_id": "g-1",
            "station_id": "sta",
            "email": "user@example.com",
            "scope_kind": "asset",
            "scope_id": "vod-jan",
            "granted_via": "comp",
        }
        base.update(kw)
        return AccessGrant(**base)  # type: ignore[arg-type]

    def test_upsert_then_get(self, store: PaywallStore) -> None:
        g = self._grant()
        store.upsert_grant(g)
        assert store.get_grant("g-1") is not None

    def test_upsert_idempotent(self, store: PaywallStore) -> None:
        g = self._grant(scope_kind="asset", scope_id="A")
        store.upsert_grant(g)
        g2 = self._grant(scope_kind="asset", scope_id="B")  # same grant_id
        store.upsert_grant(g2)
        assert store.get_grant("g-1").scope_id == "B"  # type: ignore[union-attr]

    def test_list_grants_for_email(self, store: PaywallStore) -> None:
        store.upsert_grant(self._grant(grant_id="g-1", scope_id="A"))
        store.upsert_grant(self._grant(grant_id="g-2", scope_id="B"))
        # Different email — should not appear.
        store.upsert_grant(self._grant(grant_id="g-3", email="other@x.co"))
        assert len(store.list_grants_for_email("sta", "user@example.com")) == 2

    def test_has_grant_for_specific_asset(self, store: PaywallStore) -> None:
        store.upsert_grant(self._grant(scope_kind="asset", scope_id="vod-jan"))
        assert store.has_grant_for("sta", "user@example.com", "asset", "vod-jan")
        # Different asset — no match.
        assert not store.has_grant_for("sta", "user@example.com", "asset", "vod-feb")

    def test_has_grant_for_catch_all(self, store: PaywallStore) -> None:
        store.upsert_grant(self._grant(scope_kind="all", scope_id="", granted_via="comp"))
        # The "all" grant unlocks any specific asset.
        assert store.has_grant_for("sta", "user@example.com", "asset", "any-asset")
        assert store.has_grant_for("sta", "user@example.com", "series", "any-series")

    def test_has_grant_excludes_expired(self, store: PaywallStore) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        store.upsert_grant(self._grant(scope_kind="all", scope_id="", expires_at=past))
        assert not store.has_grant_for("sta", "user@example.com", "asset", "a")

    def test_has_grant_excludes_different_station(self, store: PaywallStore) -> None:
        store.upsert_grant(self._grant(scope_kind="all"))
        # Same email + scope, different station.
        assert not store.has_grant_for("other-sta", "user@example.com", "asset", "a")

    def test_has_grant_false_when_no_rows(self, store: PaywallStore) -> None:
        assert not store.has_grant_for("sta", "nobody@example.com", "asset", "a")

    def test_revoke_grants_for_subscription_returns_count(self, store: PaywallStore) -> None:
        store.upsert_grant(self._grant(grant_id="g-1", subscription_id="sub_x"))
        store.upsert_grant(self._grant(grant_id="g-2", subscription_id="sub_x"))
        store.upsert_grant(self._grant(grant_id="g-3", subscription_id=None))
        removed = store.revoke_grants_for_subscription("sub_x")
        assert removed == 2
        assert store.get_grant("g-3") is not None
        assert store.get_grant("g-1") is None

    def test_delete_unknown_grant_raises(self, store: PaywallStore) -> None:
        with pytest.raises(AccessGrantNotFoundError):
            store.delete_grant("missing")


class TestPaywallStoreSubscriptions:
    def _sub(self, **kw: object) -> Subscription:
        base = {
            "sub_id": "sub_abc",
            "station_id": "sta",
            "email": "user@example.com",
            "tier_id": "basic",
            "status": "active",
            "current_period_end": datetime.now(UTC) + timedelta(days=30),
        }
        base.update(kw)
        return Subscription(**base)  # type: ignore[arg-type]

    def test_upsert_then_get(self, store: PaywallStore) -> None:
        s = self._sub()
        store.upsert_subscription(s)
        assert store.get_subscription("sub_abc") is not None

    def test_upsert_overwrites_status(self, store: PaywallStore) -> None:
        store.upsert_subscription(self._sub(status="active"))
        store.upsert_subscription(self._sub(status="canceled"))
        assert store.get_subscription("sub_abc").status == "canceled"  # type: ignore[union-attr]

    def test_get_unknown_returns_none(self, store: PaywallStore) -> None:
        assert store.get_subscription("missing") is None


# --- migration ----------------------------------------------------------------


def _make_cfg(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


class TestMigration0059UpgradeDowngrade:
    """The migration must create all three tables + the CHECKs/INDEXes and
    cleanly downgrade back to ``0058_meeting_agenda``. Real-SQLite here;
    the real-PG locks live in ``tests/live/test_real_postgres.py``."""

    def test_upgrade_creates_three_tables(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        eng = create_engine(url, future=True)
        try:
            names = set(inspect(eng).get_table_names())
            assert "paywall_configs" in names
            assert "access_grants" in names
            assert "paywall_subscriptions" in names
        finally:
            eng.dispose()

    def test_upgrade_creates_unique_index_on_station(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig2.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        eng = create_engine(url, future=True)
        try:
            with eng.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO paywall_configs "
                        "(config_id, station_id, enabled, provider, tiers, "
                        "created_at, updated_at) VALUES "
                        "('a', 'sta', 0, 'stripe', '[]', "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )
                conn.commit()
                # SQLite raises sqlite3.IntegrityError; SQLAlchemy wraps it in
                # ``IntegrityError``. Match the wrapper directly rather than the
                # base ``Exception`` (BLE001).
                from sqlalchemy.exc import IntegrityError

                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO paywall_configs "
                            "(config_id, station_id, enabled, provider, tiers, "
                            "created_at, updated_at) VALUES "
                            "('b', 'sta', 0, 'stripe', '[]', "
                            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        )
                    )
        finally:
            eng.dispose()

    def test_downgrade_drops_three_tables(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig3.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0058_meeting_agenda")
        eng = create_engine(url, future=True)
        try:
            names = set(inspect(eng).get_table_names())
            assert "paywall_configs" not in names
            assert "access_grants" not in names
            assert "paywall_subscriptions" not in names
        finally:
            eng.dispose()

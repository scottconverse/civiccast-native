# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 system-resource sampler tests (spec §3.8/§6.6)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from civiccast.alerting.models import SystemResourceSample
from civiccast.alerting.resource_sampler import (
    ResourceProbes,
    ResourceThresholds,
    build_resource_sample,
    default_resource_probes,
    derive_resource_conditions,
    sample_and_record,
)
from civiccast.alerting.store import get_alert_events, recent_resource_samples

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
_TH = ResourceThresholds(
    min_media_free_gb=20.0, min_backup_free_gb=20.0, max_clock_skew_seconds=5.0
)


def _sample(**kw) -> SystemResourceSample:
    base = {
        "sampled_at": _NOW,
        "cpu_percent": 30.0,
        "ram_used_gb": 4.0,
        "ram_total_gb": 16.0,
        "media_volume_free_gb": 500.0,
        "backup_volume_free_gb": 500.0,
        "db_reachable": True,
        "backup_volume_writable": True,
        "service_running": True,
        "clock_skew_seconds": 0.2,
    }
    base.update(kw)
    return SystemResourceSample(**base)


# ---------------------------------------------------------------------------
# derive_resource_conditions (pure)
# ---------------------------------------------------------------------------


class TestDeriveResourceConditions:
    def test_healthy_has_no_conditions(self) -> None:
        assert derive_resource_conditions(_sample(), _TH) == []

    def test_low_media_volume_is_disk_low(self) -> None:
        conds = dict(derive_resource_conditions(_sample(media_volume_free_gb=5.0), _TH))
        assert "disk-low" in conds
        assert "media" in conds["disk-low"]

    def test_low_backup_volume_is_disk_low(self) -> None:
        conds = dict(derive_resource_conditions(_sample(backup_volume_free_gb=1.0), _TH))
        assert "disk-low" in conds
        assert "backup" in conds["disk-low"]

    def test_both_volumes_low_single_disk_low_condition(self) -> None:
        conds = derive_resource_conditions(
            _sample(media_volume_free_gb=5.0, backup_volume_free_gb=1.0), _TH
        )
        assert [k for k, _ in conds].count("disk-low") == 1

    def test_clock_skew_positive_and_negative(self) -> None:
        assert "clock-skew" in dict(
            derive_resource_conditions(_sample(clock_skew_seconds=9.0), _TH)
        )
        assert "clock-skew" in dict(
            derive_resource_conditions(_sample(clock_skew_seconds=-9.0), _TH)
        )

    def test_db_unreachable(self) -> None:
        assert "db-unreachable" in dict(
            derive_resource_conditions(_sample(db_reachable=False), _TH)
        )

    def test_service_down(self) -> None:
        assert "service-down" in dict(
            derive_resource_conditions(_sample(service_running=False), _TH)
        )

    def test_none_metrics_never_breach(self) -> None:
        s = _sample(media_volume_free_gb=None, backup_volume_free_gb=None, clock_skew_seconds=None)
        assert derive_resource_conditions(s, _TH) == []


# ---------------------------------------------------------------------------
# sample_and_record (against the real store)
# ---------------------------------------------------------------------------


class TestSampleAndRecord:
    def test_healthy_persists_sample_no_alerts(self, db_session: Session) -> None:
        sample_and_record(db_session, _sample(), _TH, now=_NOW)
        assert len(recent_resource_samples(db_session, now=_NOW)) == 1
        assert get_alert_events(db_session, state="firing") == []

    def test_low_disk_fires_once_then_dedupes(self, db_session: Session) -> None:
        sample_and_record(db_session, _sample(media_volume_free_gb=5.0), _TH, now=_NOW)
        sample_and_record(db_session, _sample(media_volume_free_gb=4.0), _TH, now=_NOW)
        firing = [
            e for e in get_alert_events(db_session, state="firing") if e.condition == "disk-low"
        ]
        assert len(firing) == 1
        assert firing[0].occurrence_count == 2  # second tick bumped, did not duplicate

    def test_db_unreachable_fires_critical_condition(self, db_session: Session) -> None:
        sample_and_record(db_session, _sample(db_reachable=False), _TH, now=_NOW)
        firing = get_alert_events(db_session, state="firing")
        assert any(e.condition == "db-unreachable" for e in firing)

    def test_service_down_fires(self, db_session: Session) -> None:
        sample_and_record(db_session, _sample(service_running=False), _TH, now=_NOW)
        assert any(
            e.condition == "service-down" for e in get_alert_events(db_session, state="firing")
        )

    def test_recovery_resolves_the_condition(self, db_session: Session) -> None:
        # Breach, then a healthy sample clears it.
        sample_and_record(db_session, _sample(media_volume_free_gb=5.0), _TH, now=_NOW)
        assert any(e.condition == "disk-low" for e in get_alert_events(db_session, state="firing"))
        sample_and_record(db_session, _sample(), _TH, now=_NOW)
        assert not any(
            e.condition == "disk-low" for e in get_alert_events(db_session, state="firing")
        )
        assert any(
            e.condition == "disk-low" for e in get_alert_events(db_session, state="resolved")
        )


# ---------------------------------------------------------------------------
# build_resource_sample + default_resource_probes
# ---------------------------------------------------------------------------


def _probes(**overrides) -> ResourceProbes:
    base = {
        "cpu_percent": lambda: 25.0,
        "ram": lambda: (4.0, 16.0),
        "gpu": lambda: (None, None),
        "media_free_gb": lambda: 500.0,
        "backup_free_gb": lambda: 400.0,
        "backup_writable": lambda: True,
        "db_reachable": lambda: True,
        "service_running": lambda: True,
        "clock_skew_seconds": lambda: 0.1,
    }
    base.update(overrides)
    return ResourceProbes(**base)


class TestBuildResourceSample:
    def test_maps_probe_outputs_to_fields(self) -> None:
        s = build_resource_sample(_probes(), now=_NOW)
        assert s.sampled_at == _NOW
        assert s.cpu_percent == 25.0
        assert (s.ram_used_gb, s.ram_total_gb) == (4.0, 16.0)
        assert s.media_volume_free_gb == 500.0
        assert s.backup_volume_free_gb == 400.0
        assert s.db_reachable is True
        assert s.service_running is True
        assert s.clock_skew_seconds == 0.1

    def test_crashing_metric_probe_degrades_to_none(self) -> None:
        def boom():
            raise RuntimeError("probe failed")

        s = build_resource_sample(_probes(cpu_percent=boom, media_free_gb=boom), now=_NOW)
        assert s.cpu_percent is None
        assert s.media_volume_free_gb is None

    def test_crashing_db_probe_is_fail_closed(self) -> None:
        def boom():
            raise RuntimeError("no db")

        s = build_resource_sample(_probes(db_reachable=boom), now=_NOW)
        assert s.db_reachable is False  # unknown reachability -> down, never a false "up"

    def test_default_probes_produce_a_valid_live_sample(self) -> None:
        probes = default_resource_probes(db_reachable=lambda: True, service_running=lambda: True)
        s = build_resource_sample(probes, now=_NOW)
        assert isinstance(s.cpu_percent, float)
        assert s.ram_total_gb is not None and s.ram_total_gb > 0
        assert s.media_volume_free_gb is None  # no media_path given
        assert s.db_reachable is True

    def test_default_probes_disk_free_when_path_given(self, tmp_path) -> None:
        probes = default_resource_probes(
            db_reachable=lambda: True,
            service_running=lambda: True,
            media_path=tmp_path,
            backup_path=tmp_path,
        )
        s = build_resource_sample(probes, now=_NOW)
        assert s.media_volume_free_gb is not None and s.media_volume_free_gb > 0
        assert s.backup_volume_writable is True  # tmp_path is writable

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U60: ``EgressDaemon.warm_source_plan`` -- the daemon end of the look-ahead.

The automation's rollover look-ahead (``_warm_upcoming_plan``) knows WHICH
boundary is a full lead away; it does not know the channel's config. The daemon
does, and it is the config that matters: the conform-cache key
(``SourcePreparer._cache_key``) hashes the canonical profile and the loudness
target/tolerance, so warming against anything other than the config the air path
will use populates an entry nothing ever reads -- a whole-asset encode for
nothing, on a box that is already behind.

So this layer exists to do exactly three things, and each one is a test here:
resolve the STORE config, refuse to warm for a channel that has none (or is
disabled), and never let any of it raise into the dispatch tick that called it.

No station is touched.
"""

from __future__ import annotations

from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.store import InMemoryEgressStore


def _config(*, channel_id: str = "gov", enabled: bool = True) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=enabled,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        loudness_tolerance_lufs=1.0,
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _plan(tmp_path: Path, *, label: str = "Item 5") -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(tmp_path / "item-5.ts"),
                duration_seconds=290.0,
                kind="program",
                source_ref="item-5",
            )
        ],
    )


def _no_plan(_channel_id: str) -> EgressSourcePlan:
    raise AssertionError("warm_source_plan must not resolve a plan itself")


class _RecordingWarmer:
    def __init__(self) -> None:
        self.calls: list[tuple[EgressConfig, EgressSourcePlan]] = []

    def __call__(self, config: EgressConfig, plan: EgressSourcePlan) -> None:
        self.calls.append((config, plan))


def _daemon(store: InMemoryEgressStore, tmp_path: Path, warmer: object | None) -> EgressDaemon:
    return EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=_no_plan,
        source_plan_warmer=warmer,  # type: ignore[arg-type]
    )


def test_warm_source_plan_hands_the_warmer_the_stores_own_config(tmp_path: Path) -> None:
    """The cache key is config-derived, so the config must be the air path's."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    warmer = _RecordingWarmer()
    daemon = _daemon(store, tmp_path, warmer)
    plan = _plan(tmp_path)

    daemon.warm_source_plan("gov", plan)

    assert len(warmer.calls) == 1
    config, warmed_plan = warmer.calls[0]
    assert warmed_plan is plan
    assert config.channel_id == "gov"
    assert config.loudness_target_lufs == -24.0
    assert config.canonical_profile.video_bitrate_kbps == 1200


def test_warm_source_plan_is_a_no_op_without_a_warmer(tmp_path: Path) -> None:
    """An old caller (no ``source_plan_warmer``) stays byte-identical in behaviour."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    daemon = _daemon(store, tmp_path, None)

    daemon.warm_source_plan("gov", _plan(tmp_path))  # must not raise


def test_warm_source_plan_skips_a_channel_with_no_config(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    warmer = _RecordingWarmer()
    daemon = _daemon(store, tmp_path, warmer)

    daemon.warm_source_plan("gov", _plan(tmp_path))

    assert warmer.calls == []


def test_warm_source_plan_skips_a_disabled_channel(tmp_path: Path) -> None:
    """A disabled channel has no air path -- there is nothing to warm it for."""

    store = InMemoryEgressStore()
    store.upsert_config(_config(enabled=False))
    warmer = _RecordingWarmer()
    daemon = _daemon(store, tmp_path, warmer)

    daemon.warm_source_plan("gov", _plan(tmp_path))

    assert warmer.calls == []


def test_warm_source_plan_survives_a_config_read_that_raises(tmp_path: Path) -> None:
    """``get_config`` touches the database; the tick that called this is on air time."""

    class _BrokenStore(InMemoryEgressStore):
        def get_config(self, channel_id: str) -> EgressConfig | None:  # type: ignore[override]
            raise RuntimeError("database is unavailable")

    warmer = _RecordingWarmer()
    daemon = _daemon(_BrokenStore(), tmp_path, warmer)

    daemon.warm_source_plan("gov", _plan(tmp_path))  # must not raise

    assert warmer.calls == []


def test_warm_source_plan_survives_a_warmer_that_raises(tmp_path: Path) -> None:
    """Belt and braces: ``warm_plan`` is total, but the tick is not the place to find out."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())

    def exploding_warmer(_config: EgressConfig, _plan: EgressSourcePlan) -> None:
        raise RuntimeError("warm backend unavailable")

    daemon = _daemon(store, tmp_path, exploding_warmer)

    daemon.warm_source_plan("gov", _plan(tmp_path))  # must not raise

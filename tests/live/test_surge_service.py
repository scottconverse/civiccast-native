# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the app-level surge-switch service (observe -> switch -> URL)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from civiccast.live.surge_service import SurgeSwitchService
from civiccast.stream.cdn.stub import StubCDNAdapter


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _StubEgressStore:
    """Resolves one channel to one live dir via an hls sink (file:// uri)."""

    def __init__(self, channel_id: str, live_dir: Path) -> None:
        self._channel_id = channel_id
        self._uri = live_dir.resolve().as_uri()

    def get_config(self, channel_id: str) -> Any:
        if channel_id != self._channel_id:
            return None
        return SimpleNamespace(sinks=[SimpleNamespace(kind="hls", uri=self._uri)])


def _service(
    *,
    clock: _Clock,
    threshold: int = 2,
    buffer_seconds: float = 3.0,
    store: Any = None,
    adapter: Any = None,
) -> SurgeSwitchService:
    return SurgeSwitchService(
        egress_store_provider=lambda: store,
        cdn_adapter_provider=lambda: adapter,
        threshold=threshold,
        buffer_seconds=buffer_seconds,
        clock=clock,
    )


# --- from_env (off by default) -----------------------------------------------


def test_from_env_is_disabled_without_a_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICCAST_LIVE_SURGE_THRESHOLD", raising=False)
    svc = SurgeSwitchService.from_env(
        egress_store_provider=lambda: None, cdn_adapter_provider=lambda: None
    )
    assert svc is None


def test_from_env_builds_when_threshold_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_LIVE_SURGE_THRESHOLD", "120")
    svc = SurgeSwitchService.from_env(
        egress_store_provider=lambda: None, cdn_adapter_provider=lambda: None
    )
    assert svc is not None


def test_from_env_rejects_a_nonpositive_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_LIVE_SURGE_THRESHOLD", "0")
    with pytest.raises(ValueError):
        SurgeSwitchService.from_env(
            egress_store_provider=lambda: None, cdn_adapter_provider=lambda: None
        )


def test_from_env_rejects_a_nonpositive_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_LIVE_SURGE_THRESHOLD", "50")
    monkeypatch.setenv("CIVICCAST_LIVE_SURGE_BUFFER_SECONDS", "-5")
    with pytest.raises(ValueError):
        SurgeSwitchService.from_env(
            egress_store_provider=lambda: None, cdn_adapter_provider=lambda: None
        )


# --- behaviour ----------------------------------------------------------------


def test_stays_local_when_no_cdn_is_configured(tmp_path: Path) -> None:
    clock = _Clock()
    svc = _service(clock=clock, threshold=1, store=_StubEgressStore("c", tmp_path), adapter=None)
    svc.observe("c", "v1")  # load 1 >= threshold, but no CDN -> clean fallback
    assert svc.switch.state("c") == "local"
    assert svc.manifest_url("c") is None


def test_observe_throttles_ticks_to_the_segment_cadence(tmp_path: Path) -> None:
    clock = _Clock()
    live = tmp_path / "live"
    live.mkdir()
    (live / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    svc = _service(
        clock=clock,
        threshold=2,
        store=_StubEgressStore("c", live),
        adapter=StubCDNAdapter(tmp_path / "cdn"),
    )
    # Two viewers arrive in the same tick window: the first observe ticks (load
    # 1, below threshold); the second is throttled, so the switch does not warm
    # until the next tick interval sees the higher load.
    svc.observe("c", "v1")
    svc.observe("c", "v2")
    assert svc.switch.state("c") == "local"


def test_switches_to_cdn_after_the_buffer_then_serves_the_cdn_url(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    (live / "seg000000000.ts").write_bytes(b"x" * 32)
    (live / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    cdn_root = tmp_path / "cdn"
    clock = _Clock()
    svc = _service(
        clock=clock,
        threshold=2,
        buffer_seconds=3.0,
        store=_StubEgressStore("gov-ch12", live),
        adapter=StubCDNAdapter(cdn_root),
    )

    def poll() -> None:
        svc.observe("gov-ch12", "v1")
        svc.observe("gov-ch12", "v2")

    poll()  # t=0: first tick sees load 1 -> local
    clock.t = 2.0
    poll()  # t=2: tick sees load 2 -> warming, cold-start publish
    assert svc.switch.state("gov-ch12") == "warming"
    assert svc.manifest_url("gov-ch12") is None  # buffer covers -> still local
    clock.t = 4.0
    poll()  # warming (2s < 3s buffer)
    clock.t = 6.0
    poll()  # t=6: buffer (4s) elapsed -> switch to CDN

    assert svc.switch.state("gov-ch12") == "cdn"
    assert (
        svc.manifest_url("gov-ch12") == (cdn_root / "live" / "gov-ch12" / "playlist.m3u8").as_uri()
    )
    # the publisher actually pushed the rolling window to the CDN
    assert (cdn_root / "live" / "gov-ch12" / "seg000000000.ts").is_file()


def test_concurrent_observes_build_at_most_one_publisher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # observe() runs on Starlette's threadpool; without the per-channel lock,
    # racing ticks would each build a publisher and orphan one on the CDN.
    import civiccast.live.surge_service as mod

    live = tmp_path / "live"
    live.mkdir()
    (live / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    (live / "seg000000000.ts").write_bytes(b"x" * 16)

    built = 0
    built_lock = threading.Lock()
    original = mod.LiveCDNPublisher

    class _Counting(original):  # type: ignore[valid-type,misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            nonlocal built
            with built_lock:
                built += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(mod, "LiveCDNPublisher", _Counting)

    svc = SurgeSwitchService(
        egress_store_provider=lambda: _StubEgressStore("c", live),
        cdn_adapter_provider=lambda: StubCDNAdapter(tmp_path / "cdn"),
        threshold=1,
        buffer_seconds=15.0,
    )

    threads = [threading.Thread(target=svc.observe, args=("c", f"v{i}")) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert built <= 1  # the per-channel lock + throttle prevent a double-publisher

# SPDX-License-Identifier: Apache-2.0
"""Native-service startup ordering for the live caption runtime."""

from __future__ import annotations

from types import SimpleNamespace

from civiccast.app import _maybe_start_background_supervisors


class _Supervisor:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def start(self) -> None:
        self._events.append(f"start:{self._name}")


class _Runtime:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.device = "cuda"
        self.compute_type = "float16"
        self.num_workers = 3
        self._model = SimpleNamespace(model=SimpleNamespace(device="cuda", compute_type="float16"))

    def prepare(self) -> None:
        self._events.append("prepare")

    def on_cuda(self) -> bool:
        return True


def test_live_caption_runtime_is_prepared_before_channel_automation_starts(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    events: list[str] = []
    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            supervisor_mode="normal",
            caption_tap_worker=SimpleNamespace(_runtime=_Runtime(events)),
            background_supervisors=[
                _Supervisor("civiccast-channel-automation", events),
                _Supervisor("civiccast-caption-tap-worker", events),
            ],
            startup_condition_hooks=[],
        )
    )

    _maybe_start_background_supervisors(app)

    assert events == [
        "prepare",
        "start:civiccast-channel-automation",
        "start:civiccast-caption-tap-worker",
    ]


def test_live_caption_runtime_preparation_failure_does_not_block_startup(
    caplog, monkeypatch
) -> None:
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    events: list[str] = []

    class _BrokenRuntime(_Runtime):
        def prepare(self) -> None:
            events.append("prepare")
            raise RuntimeError("model load failed")

    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            supervisor_mode="normal",
            caption_tap_worker=SimpleNamespace(_runtime=_BrokenRuntime(events)),
            background_supervisors=[_Supervisor("civiccast-channel-automation", events)],
            startup_condition_hooks=[],
        )
    )

    _maybe_start_background_supervisors(app)

    assert events == ["prepare", "start:civiccast-channel-automation"]
    assert "prewarm failed" in caplog.text.lower()

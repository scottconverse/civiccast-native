# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
from __future__ import annotations

import json
import subprocess

import pytest

from civiccast.recording.input_presets import (
    RecordingInputPreset,
    RecordingInputPresetCatalog,
    parse_decklink_devices,
    parse_dshow_video_devices,
)
from civiccast.recording.models import RecordingSource
from civiccast.stream._ffmpeg import FfmpegResult


def test_decklink_probe_parser_accepts_indexed_and_plain_device_rows() -> None:
    output = """
Auto-detected sources for decklink:
  [0] 'DeckLink Duo 2 (1)'
  DeckLink Duo 2 (2)
"""

    assert parse_decklink_devices(output) == ["DeckLink Duo 2 (1)", "DeckLink Duo 2 (2)"]


def test_dshow_probe_parser_keeps_video_devices_and_ignores_audio_and_aliases() -> None:
    output = """
[dshow @ 0001] \"Cam Link HDMI\" (video)
[dshow @ 0001]   Alternative name \"@device_pnp_example\"
[dshow @ 0001] \"U-Phoria USB\" (audio)
"""

    assert parse_dshow_video_devices(output) == ["Cam Link HDMI"]


def test_catalog_discovers_decklink_sdi_and_directshow_hdmi_presets() -> None:
    def runner(args: list[str]) -> FfmpegResult:
        if "decklink" in args:
            return FfmpegResult(0, "Auto-detected sources for decklink:\nDeckLink Duo 2 (2)\n", "")
        return FfmpegResult(1, "", '[dshow @ x] "Cam Link HDMI" (video)\n')

    catalog = RecordingInputPresetCatalog(ffmpeg_runner=runner)

    rows = catalog.list_presets()

    assert [(row.source_kind, row.backend, row.device_name) for row in rows] == [
        ("sdi", "decklink", "DeckLink Duo 2 (2)"),
        ("hdmi", "dshow", "Cam Link HDMI"),
    ]
    assert all(row.origin == "detected" for row in rows)


def test_catalog_loads_configured_presets_and_builds_backend_specific_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CIVICCAST_RECORDING_INPUT_PRESETS_JSON",
        json.dumps(
            [
                {
                    "preset_id": "lpm-decklink-ch2",
                    "label": "LPM DeckLink camera 2",
                    "source_kind": "sdi",
                    "backend": "decklink",
                    "device_name": "DeckLink Duo 2 (2)",
                    "format_code": "Hp60",
                },
                {
                    "preset_id": "cam-link-hdmi",
                    "label": "Portable HDMI capture",
                    "source_kind": "hdmi",
                    "backend": "dshow",
                    "device_name": "Cam Link HDMI",
                    "audio_device_name": "U-Phoria USB",
                },
            ]
        ),
    )
    catalog = RecordingInputPresetCatalog.from_env(
        ffmpeg_runner=lambda _args: FfmpegResult(1, "", "")
    )

    assert catalog.resolve_args(RecordingSource(kind="sdi", input_id="lpm-decklink-ch2")) == [
        "-f",
        "decklink",
        "-format_code",
        "Hp60",
        "-i",
        "DeckLink Duo 2 (2)",
    ]
    assert catalog.resolve_args(RecordingSource(kind="hdmi", input_id="cam-link-hdmi")) == [
        "-f",
        "dshow",
        "-i",
        "video=Cam Link HDMI:audio=U-Phoria USB",
    ]


def test_catalog_refuses_a_preset_used_with_the_wrong_source_kind() -> None:
    catalog = RecordingInputPresetCatalog(
        [
            RecordingInputPreset(
                preset_id="decklink-main",
                label="DeckLink main",
                source_kind="sdi",
                backend="decklink",
                device_name="DeckLink Duo 2 (1)",
            )
        ]
    )

    assert catalog.resolve_args(RecordingSource(kind="hdmi", input_id="decklink-main")) is None


def test_catalog_treats_a_timed_out_probe_as_no_detected_device() -> None:
    def runner(args: list[str]) -> FfmpegResult:
        raise subprocess.TimeoutExpired(args, 10)

    catalog = RecordingInputPresetCatalog(ffmpeg_runner=runner)

    assert catalog.list_presets() == []

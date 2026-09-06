# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 88 (measured in sandbox run 17, soak-a6d7871-20260906-213332Z, Opus
diagnosis): the caption-audio-tap fork's ``queue`` element used to be plain
(default, NON-leaky) and its ``appsink`` used ``drop: False`` -- together
capable of backing up the tee it forks from, starving the mux's audio pad
and stopping real TS output. This file proves the graph-side half of the
fix: ``GstPlayoutEngine._audio_tap_element_specs`` (a pure, gi-free function
-- see its definition) builds a queue with ``leaky=2``
(``GST_QUEUE_LEAK_DOWNSTREAM``), a deep buffer cap, and an appsink with
``drop=True``, in the same element order as before.

Uses the same fake-``gi``/``Gst`` fixture as
``test_gst_engine_first_output_timeout.py`` and
``test_gst_engine_preroll_timeout.py`` -- no real GStreamer install needed,
since ``ElementSpec`` is a plain dataclass and this function never
constructs an actual ``Gst.Element``.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"


@pytest.fixture
def engine_module():
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_repository = types.ModuleType("gi.repository")
    fake_glib = types.ModuleType("gi.repository.GLib")
    fake_glib.timeout_add_seconds = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_repository.GLib = fake_glib  # type: ignore[attr-defined]
    fake_repository.Gst = fake_gst  # type: ignore[attr-defined]
    fake_gi.repository = fake_repository  # type: ignore[attr-defined]

    patched_names = ("gi", "gi.repository", "gi.repository.GLib", "gi.repository.Gst")
    saved = {name: sys.modules.get(name) for name in (*patched_names, _ENGINE_MODULE_NAME)}
    for name in patched_names:
        sys.modules[name] = {
            "gi": fake_gi,
            "gi.repository": fake_repository,
            "gi.repository.GLib": fake_glib,
            "gi.repository.Gst": fake_gst,
        }[name]
    sys.modules.pop(_ENGINE_MODULE_NAME, None)
    try:
        module = importlib.import_module(_ENGINE_MODULE_NAME)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_audio_tap_specs_element_order_is_unchanged(engine_module) -> None:
    specs = engine_module._audio_tap_element_specs()
    assert [spec.factory for spec in specs] == [
        "queue",
        "audioconvert",
        "audioresample",
        "capsfilter",
        "appsink",
    ]
    assert [spec.name for spec in specs] == [
        "caption_audio_tap_queue",
        "caption_audio_tap_convert",
        "caption_audio_tap_resample",
        "caption_audio_tap_caps",
        "caption_audio_tap_sink",
    ]


def test_audio_tap_queue_is_downstream_leaky_with_a_deep_buffer_cap(engine_module) -> None:
    """Item 88: a non-leaky queue could back up the tee once the appsink
    callback fell behind -- ``leaky=2`` (GST_QUEUE_LEAK_DOWNSTREAM) drops the
    OLDEST buffered data instead. ``max-size-buffers=200`` is GStreamer's own
    stock ``queue`` default (kept explicit here, not "deepened"). The real
    fix is ``max-size-time=0``, disabling the stock 1s default -- this tap's
    audio format takes ~4.6s to fill 200 buffers, so leaving the 1s time
    bound in place would have made TIME the first (and far too tight) limit
    reached, not buffer count. ``max-size-bytes`` is deliberately left at
    GStreamer's own stock 10 MB default as a memory guard of last resort --
    this should never actually trigger in normal operation; it is the
    backstop of last resort, not the primary fix (the primary fix is the
    writer thread in ``audio_tap.py``)."""
    specs = engine_module._audio_tap_element_specs()
    queue_spec = specs[0]
    assert queue_spec.factory == "queue"
    assert queue_spec.props["leaky"] == 2
    assert queue_spec.props["max-size-buffers"] == 200
    assert queue_spec.props["max-size-time"] == 0
    assert queue_spec.props["max-size-bytes"] == 10_485_760


def test_audio_tap_appsink_drops_rather_than_blocks(engine_module) -> None:
    """Item 88: the appsink used to be ``drop: False`` -- exactly as capable
    of backing up the tee as the non-leaky queue was. ``drop=True`` bounds
    this sink's own contribution to the same failure mode."""
    specs = engine_module._audio_tap_element_specs()
    appsink_spec = specs[-1]
    assert appsink_spec.factory == "appsink"
    assert appsink_spec.props["drop"] is True
    assert appsink_spec.props["max-buffers"] == 32
    assert appsink_spec.props["emit-signals"] is True
    assert appsink_spec.props["sync"] is False


def test_audio_tap_caps_unchanged_mono_16k_s16le(engine_module) -> None:
    specs = engine_module._audio_tap_element_specs()
    caps_spec = specs[3]
    assert caps_spec.factory == "capsfilter"
    assert caps_spec.props["caps"] == (
        "audio/x-raw,format=S16LE,rate=16000,channels=1,layout=interleaved"
    )

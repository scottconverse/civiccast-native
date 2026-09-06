# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the H1 concat-aggregator-naming collision fix (measured on real
hardware, 2026-09-06: a seamless plan rollover collided its own ``vconcat_program``/
``aconcat_program`` aggregators with the still-live outgoing leg's aggregators of the
same name, GStreamer's ``Gst.Bin.add()`` silently refused the duplicate, and the
reload never actually joined the pipeline).

Unlike ``tests/egress/test_gst_engine_wsl.py``, these do NOT require a real
GStreamer/gi install: ``civiccast.egress.gst.engine`` is loaded fresh against a small
FAKE ``gi``/``Gst`` (installed into ``sys.modules`` only for the duration of the
import, then restored) that is just enough to exercise ``GstPlayoutEngine._make`` and
``_build_playlist`` -- the two methods H1's fix touches -- without a real pipeline,
decoder, or main loop. The fake ``Gst.Pipeline.add()`` mirrors the real
``Gst.Bin.add()`` contract this bug turned on: it returns ``False`` (never raises) on
a duplicate element name in the same bin, exactly like the real GStreamer runtime
does ("Name '<name>' is not unique in bin ... not adding")."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest

# Import the gi-free graph module directly (no fake gi needed for these types).
from civiccast.egress.gst.graph import ElementSpec, PlaylistLeg

_ENGINE_MODULE_NAME = "civiccast.egress.gst.engine"


class _FakePadLinkReturn:
    OK = 0


class _FakePad:
    """Minimal stand-in for ``Gst.Pad`` -- only what ``_build_playlist``'s
    no-decoder path touches: linking a sub-chain's tail into a concat's request
    pad."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.peer: _FakePad | None = None

    def link(self, other: _FakePad) -> int:
        self.peer = other
        other.peer = self
        return _FakePadLinkReturn.OK


class _FakeElement:
    """Minimal stand-in for ``Gst.Element``."""

    def __init__(self, factory: str, name: str) -> None:
        self._factory = factory
        self._name = name
        self.props: dict[str, Any] = {}
        self._pads: dict[str, _FakePad] = {}
        self._request_pad_count = 0

    def set_property(self, key: str, value: Any) -> None:
        self.props[key] = value

    def get_name(self) -> str:
        return self._name

    def get_factory(self) -> Any:
        return types.SimpleNamespace(get_name=lambda: self._factory)

    def get_static_pad(self, name: str) -> _FakePad:
        return self._pads.setdefault(name, _FakePad(f"{self._name}.{name}"))

    def request_pad_simple(self, _pattern: str) -> _FakePad:
        self._request_pad_count += 1
        return _FakePad(f"{self._name}.req{self._request_pad_count}")

    def connect(self, *_a: Any, **_k: Any) -> None:  # pragma: no cover - unused here
        pass


class _FakePipeline:
    """Mirrors the ONE real-``Gst.Bin`` contract this bug turned on:
    ``add()`` returns ``False`` (never raises) on a duplicate element name in
    the same bin, exactly like ``Gst.Bin.add()`` really does."""

    def __init__(self) -> None:
        self._names: set[str] = set()
        self.added: list[str] = []

    def add(self, element: _FakeElement) -> bool:
        if element.get_name() in self._names:
            return False
        self._names.add(element.get_name())
        self.added.append(element.get_name())
        return True


class _FakeElementFactory:
    _auto_counter = 0

    @classmethod
    def make(cls, factory: str, name: str | None = None) -> _FakeElement:
        if name is None:  # pragma: no cover - every ElementSpec here names itself
            cls._auto_counter += 1
            name = f"{factory}{cls._auto_counter}"
        return _FakeElement(factory, name)


class _FakeCaps:
    @staticmethod
    def from_string(value: str) -> str:  # pragma: no cover - no caps props in these tests
        return value


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.ElementFactory = _FakeElementFactory  # type: ignore[attr-defined]
    fake_gst.Caps = _FakeCaps  # type: ignore[attr-defined]
    fake_gst.PadLinkReturn = _FakePadLinkReturn  # type: ignore[attr-defined]
    return fake_gst


@pytest.fixture
def engine_module():
    """Load ``civiccast.egress.gst.engine`` fresh against a fake ``gi``/``Gst`` that
    needs no real GStreamer install, without disturbing ``sys.modules`` for any
    other test in the session (a real ``gi`` install, if present, is restored
    after this fixture tears down)."""
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None  # type: ignore[attr-defined]
    fake_repository = types.ModuleType("gi.repository")
    fake_glib = types.ModuleType("gi.repository.GLib")
    fake_gst = _install_fake_gst()
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


def _bare_engine(module: types.ModuleType) -> Any:
    """A ``GstPlayoutEngine`` with none of ``__init__``'s heavy pipeline-building
    run (it needs a real ``Gst.init``, registry, selectors, encoder chain, etc.,
    none of which these tests exercise) -- just the attributes ``_make`` and
    ``_build_playlist`` actually touch."""
    engine = object.__new__(module.GstPlayoutEngine)
    engine.pipeline = _FakePipeline()
    engine._collecting = None
    engine._source_leg_seq = 0
    return engine


# --- item 1: _make fails loud on a refused pipeline.add() -------------------------


def test_make_raises_on_a_duplicate_element_name(engine_module) -> None:
    engine = _bare_engine(engine_module)
    engine._make(ElementSpec("concat", "vconcat_program"))  # first add succeeds

    with pytest.raises(RuntimeError, match="vconcat_program"):
        engine._make(ElementSpec("concat", "vconcat_program"))  # duplicate: refused


def test_make_succeeds_when_the_pipeline_accepts_the_element(engine_module) -> None:
    engine = _bare_engine(engine_module)
    element = engine._make(ElementSpec("concat", "vconcat_unique"))
    assert element.get_name() == "vconcat_unique"
    assert engine.pipeline.added == ["vconcat_unique"]


# --- item 2: _source_leg_seq makes every build's aggregator name unique -----------


def _program_leg() -> PlaylistLeg:
    # No decoder in the sub-chain and no audio_tail: keeps this test scoped to the
    # naming collision (H1) rather than exercising dynamic-pad audio/video linking,
    # which is unrelated to the defect this fix addresses.
    return PlaylistLeg(
        label="program",
        subchains=((ElementSpec("videotestsrc"),),),
    )


def test_reloading_the_same_labeled_leg_does_not_collide(engine_module) -> None:
    """Proves the fix: building the "program" leg twice on the SAME pipeline (as
    happens when ``reload_program`` builds a replacement while the outgoing leg's
    own aggregator is still in the bin) produces two DISTINCT ``vconcat_program_*``
    names instead of the bare, always-colliding ``vconcat_program`` the pre-fix code
    used -- so the second build's ``_make`` call does not raise."""
    engine = _bare_engine(engine_module)
    leg = _program_leg()

    vconcat_1, aconcat_1 = engine._build_playlist(leg)  # e.g. the initial _build()
    vconcat_2, aconcat_2 = engine._build_playlist(leg)  # e.g. a later reload

    assert aconcat_1 is None and aconcat_2 is None  # no audio_tail on this leg
    assert vconcat_1.get_name() != vconcat_2.get_name()
    assert vconcat_1.get_name().startswith("vconcat_program_")
    assert vconcat_2.get_name().startswith("vconcat_program_")
    # Both aggregators actually joined the fake pipeline (pipeline.add() returned
    # True for both) -- the old bare-label naming would have refused the second.
    assert engine.pipeline.added.count(vconcat_1.get_name()) == 1
    assert engine.pipeline.added.count(vconcat_2.get_name()) == 1
    assert len(set(engine.pipeline.added)) == len(engine.pipeline.added)  # all unique


def test_the_pre_fix_bare_label_would_have_collided(engine_module) -> None:
    """Falsification: proves the OLD naming scheme (bare ``f"vconcat_{leg.label}"``,
    with no sequence number) really would have hit the fail-loud ``_make`` check
    added by item 1 -- i.e. that item 2's sequence number is load-bearing, not
    cosmetic. Builds the aggregator by hand (bypassing ``_build_playlist``, which
    now always appends the sequence) to reproduce the pre-fix name directly."""
    engine = _bare_engine(engine_module)
    leg = _program_leg()
    engine._make(ElementSpec("concat", f"vconcat_{leg.label}"))  # simulates the initial build

    with pytest.raises(RuntimeError, match="vconcat_program"):
        # simulates a reload rebuilding the SAME bare name while the first is
        # still in the bin -- exactly the measured H1 defect.
        engine._make(ElementSpec("concat", f"vconcat_{leg.label}"))

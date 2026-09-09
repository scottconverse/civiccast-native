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
    pad. Also tracks ``unlink`` calls for the F2 selector-pad-release tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.peer: _FakePad | None = None
        self.unlinked_with: list[_FakePad] = []

    def link(self, other: _FakePad) -> int:
        self.peer = other
        other.peer = self
        return _FakePadLinkReturn.OK

    def unlink(self, other: _FakePad) -> bool:
        self.unlinked_with.append(other)
        return True


class _FakeElement:
    """Minimal stand-in for ``Gst.Element``."""

    def __init__(self, factory: str, name: str) -> None:
        self._factory = factory
        self._name = name
        self.props: dict[str, Any] = {}
        self._pads: dict[str, _FakePad] = {}
        self._request_pad_count = 0
        self.states: list[Any] = []

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

    def set_state(self, state: Any) -> None:
        self.states.append(state)


class _FakeState:
    NULL = "NULL"


class _FakePipeline:
    """Mirrors the ONE real-``Gst.Bin`` contract this bug turned on:
    ``add()`` returns ``False`` (never raises) on a duplicate element name in
    the same bin, exactly like ``Gst.Bin.add()`` really does. ``remove`` frees
    the name for reuse (mirroring real ``Gst.Bin.remove``) and records the
    call, for the F2 dispose-on-failure tests."""

    def __init__(self) -> None:
        self._names: set[str] = set()
        self.added: list[str] = []
        self.removed: list[str] = []

    def add(self, element: _FakeElement) -> bool:
        if element.get_name() in self._names:
            return False
        self._names.add(element.get_name())
        self.added.append(element.get_name())
        return True

    def remove(self, element: _FakeElement) -> None:
        self._names.discard(element.get_name())
        self.removed.append(element.get_name())


class _FakeAddError(Exception):
    """Stand-in for ``Gst.AddError`` -- see ``_FakeOverrideStylePipeline``."""


class _FakeOverrideStylePipeline:
    """Candidate-3 smoke regression (2026-09-06): mirrors gst-python's
    ``overrides/Gst.py`` ``Bin.add()`` contract, confirmed directly against
    the real installed GStreamer 1.28.5 closure -- NOT the raw C
    ``gst_bin_add()`` contract ``_FakePipeline`` above models. ``add()``
    returns ``None`` on a SUCCESSFUL add (never a bare ``True``) and RAISES
    ``Gst.AddError`` (here, ``_FakeAddError``) on a genuine duplicate name --
    never returns a bare ``False``. ``_make``'s old
    ``if not self.pipeline.add(element):`` treated that ``None`` success
    return as a failure, so the very FIRST element ever added to a real
    pipeline always raised -- this is the fixture that would have caught
    that regression, which ``_FakePipeline`` (returns a real bool, matching
    the assumed-but-wrong contract) could not."""

    def __init__(self) -> None:
        self._names: set[str] = set()
        self.added: list[str] = []
        self.removed: list[str] = []

    def add(self, element: _FakeElement) -> None:
        if element.get_name() in self._names:
            raise _FakeAddError(element)
        self._names.add(element.get_name())
        self.added.append(element.get_name())

    def remove(self, element: _FakeElement) -> None:
        self._names.discard(element.get_name())
        self.removed.append(element.get_name())


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


class _FakeSelector:
    """Minimal stand-in for the ``input-selector`` element
    ``_link_leg_to_selectors`` requests pads from -- tracks
    ``release_request_pad`` calls for the F2 pad-release-on-failure tests."""

    def __init__(self, name: str = "sel") -> None:
        self._name = name
        self._request_count = 0
        self.released: list[_FakePad] = []

    def request_pad_simple(self, _pattern: str) -> _FakePad:
        self._request_count += 1
        return _FakePad(f"{self._name}.req{self._request_count}")

    def release_request_pad(self, pad: _FakePad) -> None:
        self.released.append(pad)


def _install_fake_gst() -> types.ModuleType:
    fake_gst = types.ModuleType("gi.repository.Gst")
    fake_gst.ElementFactory = _FakeElementFactory  # type: ignore[attr-defined]
    fake_gst.Caps = _FakeCaps  # type: ignore[attr-defined]
    fake_gst.PadLinkReturn = _FakePadLinkReturn  # type: ignore[attr-defined]
    fake_gst.State = _FakeState  # type: ignore[attr-defined]
    fake_gst.AddError = _FakeAddError  # type: ignore[attr-defined]
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


def _bare_engine_with_override_style_pipeline(module: types.ModuleType) -> Any:
    """Same as ``_bare_engine``, but with ``_FakeOverrideStylePipeline`` --
    real gst-python's ``None``-on-success/raises-on-failure ``Bin.add()``
    contract, not the raw-bool one ``_bare_engine`` models."""
    engine = object.__new__(module.GstPlayoutEngine)
    engine.pipeline = _FakeOverrideStylePipeline()
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


# --- candidate-3 smoke regression (2026-09-06): _bin_add must normalize BOTH
# real Gst.Bin.add() contracts, not just the raw-bool one ------------------


def test_bin_add_accepts_the_none_on_success_override_style_contract(engine_module) -> None:
    """Direct unit coverage of ``_bin_add`` against
    ``_FakeOverrideStylePipeline`` (gst-python's real ``overrides/Gst.py``
    contract, confirmed against GStreamer 1.28.5): a successful add returns
    ``None``, not ``True`` -- the pre-fix ``if not self.pipeline.add(...):``
    treated that as a failure, so a fresh pipeline's VERY FIRST element (the
    video selector, "sel") always raised, even though GStreamer's own C code
    had genuinely just added it. Proves ``_make`` no longer raises for a
    first-ever, genuinely-unique add against this contract."""
    engine = _bare_engine_with_override_style_pipeline(engine_module)

    element = engine._make(ElementSpec("input-selector", "sel"))

    assert element.get_name() == "sel"
    assert engine.pipeline.added == ["sel"]


def test_bin_add_still_raises_on_a_genuine_duplicate_under_the_override_style_contract(
    engine_module,
) -> None:
    """Same fixture, the failure side: a genuine duplicate name raises
    ``Gst.AddError`` (never returns a bare ``False``) under this contract --
    ``_make`` must still fail loud, just via a different underlying signal."""
    engine = _bare_engine_with_override_style_pipeline(engine_module)
    engine._make(ElementSpec("input-selector", "sel"))

    with pytest.raises(RuntimeError, match="sel"):
        engine._make(ElementSpec("input-selector", "sel"))


def test_selector_and_source_leg_names_stay_unique_across_initial_build_and_three_reloads(
    engine_module,
) -> None:
    """Candidate-3 smoke regression, item 3: asserts name uniqueness holds
    across an initial build's selector creation PLUS a program leg built
    once (the initial build) and rebuilt three more times (simulating three
    content-reloads), using ``_FakeOverrideStylePipeline`` so this would
    have caught the actual regression (a real ``Gst.Bin.add()`` returning
    ``None`` on every successful add, not just on a duplicate) -- the
    existing ``_FakePipeline``-based tests above only prove the SEQUENCE
    NUMBER logic; this proves the add-result handling underneath it too."""
    engine = _bare_engine_with_override_style_pipeline(engine_module)
    leg = _program_leg()

    # Initial build: both selectors, then the program leg's first build.
    engine._make(ElementSpec("input-selector", "sel"))
    engine._make(ElementSpec("input-selector", "asel"))
    vconcat_initial, _ = engine._build_playlist(leg)

    # Three simulated content-reloads: each rebuilds the SAME-labeled leg
    # while the previous one(s) are still (in this simplified model) present
    # in the bin -- exactly the shape a real deferred-switch reload leaves
    # behind until the outgoing leg is disposed.
    reload_names = []
    for _ in range(3):
        vconcat_reload, _ = engine._build_playlist(leg)
        reload_names.append(vconcat_reload.get_name())

    all_names = ["sel", "asel", vconcat_initial.get_name(), *reload_names]
    assert len(all_names) == len(set(all_names)), all_names
    # No add() call across the whole sequence (selectors, the initial leg
    # build, and all three reload rebuilds -- including each build's own
    # videotestsrc sub-chain elements) ever collided: every element the
    # fake pipeline accepted has a distinct name.
    assert len(engine.pipeline.added) == len(set(engine.pipeline.added)), engine.pipeline.added
    assert set(all_names) <= set(engine.pipeline.added)


# --- F2 (hostile-review follow-up, 2026-09-06): a build/link failure must not
# leak the elements/pads already claimed before it ------------------------------


def test_a_mid_build_failure_disposes_the_elements_already_added(engine_module) -> None:
    """``_instantiate_source_leg``: a build failure partway through a sub-chain
    (here, the SECOND element of one sub-chain colliding on name with the
    FIRST -- simulating ``_make``'s fail-loud ``pipeline.add`` refusal) must
    NULL-and-remove whatever was already added to the pipeline before the
    failure (the aggregator built first, plus the first sub-chain element),
    not just re-raise and leak them."""
    engine = _bare_engine(engine_module)
    leg = PlaylistLeg(
        label="program",
        subchains=(
            (
                ElementSpec("videotestsrc", name="dup"),
                ElementSpec("videoconvert", name="dup"),  # collides -> _make raises
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="dup"):
        engine._instantiate_source_leg(leg)

    # The aggregator (vconcat_program_1) and the first sub-chain element
    # ("dup", the videotestsrc) were both successfully added before the
    # failure -- both must have been disposed (NULLed + removed), and the
    # duplicate name is free again in the pipeline's own bookkeeping.
    assert engine.pipeline.added == ["vconcat_program_1", "dup"]
    assert sorted(engine.pipeline.removed) == ["dup", "vconcat_program_1"]
    assert "dup" not in engine.pipeline._names
    assert "vconcat_program_1" not in engine.pipeline._names


def test_dispose_elements_best_effort_suppresses_a_raise_and_still_disposes_the_rest(
    engine_module,
) -> None:
    """Hostile-review follow-up (third pass), item 5a: direct unit coverage of
    ``_dispose_elements_best_effort`` itself, exercising BOTH of its raise-suppression
    seams independently -- an element whose ``set_state`` raises, and one whose
    removal (``pipeline.remove``) raises -- proving each is swallowed (never replaces
    the caller's context, never aborts the loop) AND that every OTHER element in the
    batch still gets both its ``set_state(NULL)`` and its ``pipeline.remove`` call,
    not just the ones before the raising element."""
    engine = _bare_engine(engine_module)

    class _RaisingSetStateElement(_FakeElement):
        def set_state(self, state: Any) -> None:
            self.states.append(state)
            raise RuntimeError("simulated set_state failure")

    class _RaisingRemovePipeline(_FakePipeline):
        def remove(self, element: _FakeElement) -> None:
            if element.get_name() == "ok-2":
                raise RuntimeError("simulated pipeline.remove failure")
            super().remove(element)

    engine.pipeline = _RaisingRemovePipeline()
    bad_set_state = _RaisingSetStateElement("videotestsrc", "bad-set-state")
    ok_1 = _FakeElement("videotestsrc", "ok-1")
    bad_remove = _FakeElement("videoconvert", "ok-2")  # its remove() raises
    ok_3 = _FakeElement("videoconvert", "ok-3")
    elements = [bad_set_state, ok_1, bad_remove, ok_3]
    for element in elements:
        engine.pipeline.add(element)

    # Must not raise -- both failures are swallowed.
    engine._dispose_elements_best_effort(elements)

    # set_state(NULL) was attempted on every element, including the one whose
    # call itself raised.
    for element in elements:
        assert element.states == [engine_module.Gst.State.NULL]
    # pipeline.remove was attempted on every element too -- the one that raised
    # did not stop "ok-3" (added after it in the list) from being removed.
    assert sorted(engine.pipeline.removed) == ["bad-set-state", "ok-1", "ok-3"]
    assert "ok-2" in engine.pipeline._names  # its own remove raised, so it's still "in" the bin
    for name in ("bad-set-state", "ok-1", "ok-3"):
        assert name not in engine.pipeline._names


def test_link_failure_releases_the_video_pad_it_already_requested(engine_module) -> None:
    """``_link_leg_to_selectors``: when audio is enabled but the leg has no
    audio pad, the method already successfully requested (and linked) a VIDEO
    selector pad before discovering the audio problem -- that pad must be
    unlinked and released, not left as a permanently-orphaned selector request
    pad (a request pad is never automatically freed)."""
    engine = _bare_engine(engine_module)
    video_selector = _FakeSelector("vsel")
    audio_selector = _FakeSelector("asel")
    engine.selector = video_selector
    engine.audio_selector = audio_selector
    out_pad = _FakePad("leg.video_src")

    with pytest.raises(RuntimeError, match="no audio leg"):
        engine._link_leg_to_selectors("test-leg", out_pad, None)  # audio_out_pad=None

    assert len(video_selector.released) == 1
    released_pad = video_selector.released[0]
    assert released_pad.name == "vsel.req1"  # the video sink pad it requested
    assert out_pad.unlinked_with == [released_pad]
    assert audio_selector.released == []  # never got as far as requesting one


def test_link_failure_releases_both_pads_when_the_audio_link_itself_fails(
    engine_module,
) -> None:
    """Same as above, but the audio leg DOES exist and gets as far as
    requesting its own selector pad -- when ITS link then fails (modeled here
    via a pad whose ``link`` reports failure), both the video AND the audio
    request pads must be released, not just the video one."""
    engine = _bare_engine(engine_module)
    video_selector = _FakeSelector("vsel")
    audio_selector = _FakeSelector("asel")
    engine.selector = video_selector
    engine.audio_selector = audio_selector
    out_pad = _FakePad("leg.video_src")

    class _NeverLinksPad(_FakePad):
        def link(self, other: _FakePad) -> int:  # pragma: no cover - trivial
            return 1  # anything other than _FakePadLinkReturn.OK (0)

    audio_out_pad = _NeverLinksPad("leg.audio_src")

    with pytest.raises(RuntimeError, match="failed to link audio"):
        engine._link_leg_to_selectors("test-leg", out_pad, audio_out_pad)

    assert len(video_selector.released) == 1
    assert len(audio_selector.released) == 1
    assert out_pad.unlinked_with == video_selector.released
    # The audio pad's own link failed, so nothing ever linked it -- only the
    # already-linked VIDEO pad needs an unlink call; the audio release is a
    # bare release_request_pad with no prior link to undo.


def test_release_selector_pad_best_effort_is_a_direct_unit(engine_module) -> None:
    """Direct unit coverage of the shared static helper both tests above
    exercise indirectly: unlinks (when a ``linked_pad`` is given) then
    releases the pad; is a no-op for ``sink_pad=None``; and swallows any
    error from either call (an already-failing path must never raise a
    SECOND exception that would replace the caller's real one)."""
    engine_module_cls = engine_module.GstPlayoutEngine
    selector = _FakeSelector("sel")
    sink_pad = _FakePad("sel.req1")
    linked_pad = _FakePad("leg.video_src")

    engine_module_cls._release_selector_pad_best_effort(selector, None)
    assert selector.released == []  # no-op for None

    engine_module_cls._release_selector_pad_best_effort(selector, sink_pad, linked_pad=linked_pad)
    assert linked_pad.unlinked_with == [sink_pad]
    assert selector.released == [sink_pad]

    class _RaisingSelector(_FakeSelector):
        def release_request_pad(self, pad: _FakePad) -> None:
            raise RuntimeError("simulated GStreamer failure")

    # Must not raise even though release_request_pad blows up.
    engine_module_cls._release_selector_pad_best_effort(_RaisingSelector(), sink_pad)

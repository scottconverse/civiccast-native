# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The worker and the engine must bind ONE copy of the graph dataclasses.

Gate A T4 root cause (2026-09): ``worker.py`` imported its sibling modules BY
PATH (``import graph``) while ``engine.py`` prefers the package form
(``from civiccast.egress.gst.graph import ...``). On the native Windows line the
bundled GStreamer runtime makes the engine's package import succeed, so the two
halves bound two DISTINCT ``PlaylistLeg`` classes compiled from the same file.
``engine._instantiate_source_leg``'s ``isinstance(leg, PlaylistLeg)`` dispatch
then missed on every program leg (``bridge.graph_from_config`` always builds a
``PlaylistLeg``), fell through to the ``SourceLeg`` branch and raised
``AttributeError: 'PlaylistLeg' object has no attribute 'elements'`` inside
``GstPlayoutEngine.__init__`` — before the pipeline ever reached PLAYING, so the
udp-ts sink never emitted a single MPEG-TS packet.

The engine module itself imports ``gi``, which is not installed in this test
environment (it lives only in the shipped GStreamer closure), so the engine is
stubbed in ``sys.modules`` under its PACKAGE name. That stub satisfies the
worker's package import and nothing else: a worker that still imports by path
would try to load the real ``engine`` module and fail on ``gi``.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Iterator

import pytest

import civiccast.egress.gst.graph as pkg_graph

_WORKER = "civiccast.egress.gst.worker"


@pytest.fixture
def imported_worker(monkeypatch: pytest.MonkeyPatch) -> Iterator[types.ModuleType]:
    engine_stub = types.ModuleType("civiccast.egress.gst.engine")
    engine_stub.GstPlayoutEngine = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "civiccast.egress.gst.engine", engine_stub)
    for cached in (_WORKER, "graph", "engine", "control"):
        monkeypatch.delitem(sys.modules, cached, raising=False)
    module = importlib.import_module(_WORKER)
    try:
        yield module
    finally:
        sys.modules.pop(_WORKER, None)


def test_worker_binds_the_package_graph_module(imported_worker: types.ModuleType) -> None:
    """The worker's ``graphmod`` IS ``civiccast.egress.gst.graph`` — not a second
    copy of the same file loaded under the top-level name ``graph``."""
    assert imported_worker.graphmod is pkg_graph
    assert imported_worker.graphmod.PlaylistLeg is pkg_graph.PlaylistLeg


def test_worker_deserialized_program_leg_is_the_engines_playlist_leg(
    imported_worker: types.ModuleType,
) -> None:
    """A graph deserialized by the worker passes the engine's ``isinstance``
    dispatch. This is the exact predicate that missed in Gate A T4."""
    graph = pkg_graph.PlayoutGraph(
        sources=(
            pkg_graph.PlaylistLeg(
                label="program",
                subchains=((pkg_graph.ElementSpec("filesrc", props={"location": "slate.ts"}),),),
            ),
            pkg_graph.SourceLeg(
                label="slate",
                elements=(pkg_graph.ElementSpec("videotestsrc", props={"pattern": 2}),),
            ),
        ),
        encoder=(pkg_graph.ElementSpec("x264enc"),),
        mux=pkg_graph.ElementSpec("mpegtsmux", name="mux"),
        sinks=(
            (
                pkg_graph.ElementSpec("queue"),
                pkg_graph.ElementSpec("udpsink", props={"host": "127.0.0.1", "port": 19003}),
            ),
        ),
    )
    round_tripped = imported_worker.graphmod.graph_from_json(pkg_graph.graph_to_json(graph))
    program_leg = round_tripped.sources[0]
    assert isinstance(program_leg, pkg_graph.PlaylistLeg)

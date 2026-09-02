# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A live SRT source opens through the engine with a resolved passphrase (WP-07).

The constraint that shapes this design: ``graph_from_config`` runs in the
strategy process and its result is written to a JSON file on disk
(``civiccast.egress.gst.strategy._write_graph_file`` /
``graph.graph_to_json``) for the worker to read back. Anything placed in
``ElementSpec.props`` is therefore PERSISTED. A passphrase must not be.

So the handle -- not the secret -- travels through the plan, the durable
takeover audit row, and the graph file, in ``ElementSpec.secret_props``. The
worker resolves it against the station's OS credential store at
element-construction time (``engine.PlayoutPipeline._make``), which is also
what makes a rotated passphrase take effect without rebuilding the graph.

These tests exercise the pure graph/spec layer. They need no GStreamer runtime;
the live engine tests that do are in ``test_gst_engine_wsl.py`` and skip
without it.
"""

from __future__ import annotations

import json

import pytest

from civiccast.egress.gst.bridge import source_first_element
from civiccast.egress.gst.graph import (
    ElementSpec,
    PlayoutGraph,
    SourceLeg,
    graph_from_json,
    graph_to_json,
)
from civiccast.egress.models import EgressSourceSegment

_SECRET = "council-chamber-passphrase"


def _segment(*, path: str = "srt://0.0.0.0:9000?mode=listener", secret_ref: str | None = None):  # type: ignore[no-untyped-def]
    return EgressSourceSegment(
        label="Council Room Encoder",
        path=path,
        duration_seconds=3600.0,
        kind="live",
        source_ref="council-encoder",
        secret_ref=secret_ref,
    )


class TestSourceElement:
    def test_an_srt_segment_without_a_handle_is_unchanged(self) -> None:
        spec = source_first_element(_segment())
        assert spec.factory == "srtsrc"
        assert spec.props == {"uri": "srt://0.0.0.0:9000?mode=listener"}
        assert spec.secret_props == {}

    def test_an_srt_handle_becomes_a_secret_prop_not_a_uri_parameter(self) -> None:
        spec = source_first_element(_segment(secret_ref="council-srt"))
        assert spec.factory == "srtsrc"
        # The URI is untouched: no ?passphrase= appended, which is how the
        # pre-existing SRT *sink* path does it (bridge.sink_element_spec).
        assert spec.props == {"uri": "srt://0.0.0.0:9000?mode=listener"}
        assert spec.secret_props == {"passphrase": "council-srt"}

    @pytest.mark.parametrize(
        "path",
        [
            "rtmp://encoder.local/live/a",
            "rtsp://camera.local/stream1",
            "udp://239.0.0.1:5000",
            "https://cdn.example/live.m3u8",
        ],
    )
    def test_a_handle_on_a_non_srt_scheme_is_refused_not_opened_unauthenticated(
        self, path: str
    ) -> None:
        # Failing the graph is the safe answer. Opening the feed without the
        # credential and calling it live is not.
        with pytest.raises(ValueError, match="cannot carry a stored credential"):
            source_first_element(_segment(path=path, secret_ref="cam-password"))

    def test_a_file_segment_is_untouched(self) -> None:
        spec = source_first_element(
            EgressSourceSegment(label="VOD", path="/srv/a.ts", duration_seconds=10.0)
        )
        assert spec.factory == "filesrc"
        assert spec.secret_props == {}


class TestGraphSerialization:
    def test_secret_props_round_trip_as_handles(self) -> None:
        spec = ElementSpec(
            "srtsrc", props={"uri": "srt://h:9000"}, secret_props={"passphrase": "h1"}
        )
        graph = PlayoutGraph(
            sources=(SourceLeg(label="program", elements=(spec,)),),
            encoder=(ElementSpec("x264enc"),),
            mux=ElementSpec("mpegtsmux", name="mux"),
            sinks=((ElementSpec("queue"), ElementSpec("fakesink")),),
        )
        restored = graph_from_json(graph_to_json(graph))
        assert restored.sources[0].elements[0].secret_props == {"passphrase": "h1"}
        # And the JSON itself holds the handle, never a resolved value.
        assert "h1" in graph_to_json(graph)

    def test_the_serialized_graph_carries_the_handle_and_never_the_secret(self) -> None:
        spec = source_first_element(_segment(secret_ref="council-srt"))
        blob = json.dumps({"factory": spec.factory, "secret_props": spec.secret_props})
        assert "council-srt" in blob
        assert _SECRET not in blob

    def test_a_spec_without_secret_props_serializes_to_the_old_shape(self) -> None:
        # Existing graph files and golden assertions must not change shape.
        from civiccast.egress.gst.graph import _elem_to_dict

        assert _elem_to_dict(ElementSpec("queue")) == {
            "factory": "queue",
            "name": None,
            "props": {},
        }

    def test_an_older_graph_file_without_the_key_still_loads(self) -> None:
        from civiccast.egress.gst.graph import _elem_from_dict

        spec = _elem_from_dict({"factory": "srtsrc", "props": {"uri": "srt://h:9000"}})
        assert spec.secret_props == {}

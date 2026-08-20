# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for the native three-channel caption transport proof."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prove_native_live_caption_transport.py"
_SPEC = importlib.util.spec_from_file_location(
    "prove_native_live_caption_transport",
    _SCRIPT,
)
assert _SPEC is not None and _SPEC.loader is not None
proof = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = proof
_SPEC.loader.exec_module(proof)


def _write_sidecar(root: Path, channel_id: str, text: str) -> None:
    path = root / channel_id / "captions" / "active.vtt"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"WEBVTT\n\n{channel_id}-cue\n00:00:01.000 --> 00:00:03.000\n{text}\n",
        encoding="utf-8",
    )


def test_proof_graph_uses_the_live_appsrc_and_caption_inserter(tmp_path: Path) -> None:
    output = tmp_path / "proof.ts"

    graph = proof.build_live_caption_graph(output)

    assert graph.captions is not None
    assert graph.captions.caption_source[0].factory == "appsrc"
    assert graph.captions.combiner.factory == "cccombiner"
    assert [item.factory for item in graph.captions.inserter_chain] == [
        "h264ccinserter",
        "h264parse",
    ]
    assert graph.sinks[0][-1].props["location"] == str(output.resolve())


def test_required_sidecars_are_exactly_the_three_station_channels(tmp_path: Path) -> None:
    for channel_id in proof.REQUIRED_CHANNELS:
        _write_sidecar(tmp_path, channel_id, f"{channel_id} meeting")

    cues = proof._required_sidecar_cues(tmp_path)

    assert set(cues) == set(proof.REQUIRED_CHANNELS)
    assert all(len(channel_cues) == 1 for channel_cues in cues.values())


def test_required_sidecars_fail_loud_when_one_channel_is_missing(tmp_path: Path) -> None:
    for channel_id in proof.REQUIRED_CHANNELS[:-1]:
        _write_sidecar(tmp_path, channel_id, f"{channel_id} meeting")

    with pytest.raises(RuntimeError, match="required caption sidecar is missing"):
        proof._required_sidecar_cues(tmp_path)


def test_transport_hold_covers_the_last_requested_cue_end() -> None:
    cues = {
        "government": [
            SimpleNamespace(start_seconds=1.0, end_seconds=3.02),
            SimpleNamespace(start_seconds=4.16, end_seconds=4.98),
        ]
    }

    assert proof._caption_transport_hold_seconds(cues) == pytest.approx(5.98)


def test_decode_child_handles_runtime_verifier_typed_dict_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(proof, "_child_init_gst", lambda: object())
    monkeypatch.setattr(
        proof,
        "_child_caption_decode_back",
        lambda *_args, **_kwargs: {
            "ok": True,
            "detail": "decoded HELLO CIVICCAST",
        },
    )

    exit_code = proof._decode_child_main(
        SimpleNamespace(
            transport_stream=tmp_path / "captioned.ts",
            expected_text="HELLO CIVICCAST",
        )
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PASS"
    assert payload["normalized_text_check"] is True


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Win32 token/SID proof")
def test_proof_pipe_acl_contains_system_and_the_running_identity() -> None:
    sddl = proof.current_process_pipe_sddl()

    assert sddl.startswith("D:P(A;;GA;;;SY)(A;;GA;;;S-1-")

#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Prove the live caption worker -> review queue -> HLS WebVTT path.

This is a deterministic Sprint 0.5 integration proof. It does not run the AI
model; the model runtime is separately covered by the Blackwell benchmark. This
proof drives the live worker seam with a fake runtime so the stabilization,
review persistence, HLS manifest rewrite, WebVTT output, latency budget, and
"no retroactive rewrite" contract can be checked without model variance.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

from civiccast.captions.models import AudioChunk, CaptionHypothesis, CustomVocabulary
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.worker import LiveCaptionWorker
from civiccast.stream.packager import pack_slate_fallback


@dataclass(frozen=True)
class LiveCaptionProofResult:
    asset_id: str
    window_count: int
    latency_budget_seconds: float
    max_commit_latency_seconds: float
    mean_commit_latency_seconds: float
    first_pass_committed_count: int
    second_pass_committed_count: int
    review_item_count: int
    duplicate_review_item_count: int
    manifest_path: str
    caption_playlist_path: str
    caption_segment_path: str
    manifest_has_subtitle_track: bool
    caption_segment_has_text: bool
    no_retroactive_rewrite: bool
    committed_text: str
    attempted_rewrite_text: str
    passed: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


class ScriptedLiveRuntime:
    """Deterministic runtime used only by the live path proof."""

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        for chunk in chunks:
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-proof",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=self.text,
                confidence=0.92,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/releases/evidence/live-caption-proof"),
        help="Directory where the proof HLS package is written.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("docs/releases/evidence/v0.5-live-caption-proof.json"),
        help="Path for the machine-readable proof JSON.",
    )
    parser.add_argument(
        "--latency-budget-seconds",
        type=float,
        default=4.0,
        help="Maximum allowed commit-to-HLS-publication latency.",
    )
    parser.add_argument(
        "--window-count",
        type=int,
        default=1,
        help="Number of 4-second live windows to prove. Use 450 for 30 minutes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_proof(
        output_dir=args.output_dir,
        latency_budget_seconds=args.latency_budget_seconds,
        window_count=args.window_count,
    )
    rendered = result.to_json()
    print(rendered)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result.passed else 1


def run_proof(
    *,
    output_dir: Path,
    latency_budget_seconds: float,
    window_count: int = 1,
) -> LiveCaptionProofResult:
    if latency_budget_seconds <= 0:
        raise ValueError("latency_budget_seconds must be positive")
    if window_count < 1:
        raise ValueError("window_count must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    package = pack_slate_fallback(output_dir)
    store = InMemoryCaptionReviewStore()
    runtime = ScriptedLiveRuntime("")
    worker = LiveCaptionWorker(
        runtime,
        store,
        asset_id="live-caption-proof",
        package=package,
        segment_duration=4,
    )
    first_pass_committed_count = 0
    second_pass_committed_count = 0
    duplicate_review_item_count = 0
    commit_latencies: list[float] = []
    hls_output = None
    first_chunk: AudioChunk | None = None

    for window_index in range(window_count):
        start_seconds = window_index * 4.0
        chunk = AudioChunk(
            chunk_id=f"proof-window-{window_index:03d}",
            start_seconds=start_seconds,
            end_seconds=start_seconds + 3.8,
            sample_rate_hz=16_000,
            pcm_s16le=b"\x00\x00" * 16_000,
        )
        if first_chunk is None:
            first_chunk = chunk
        runtime.text = f"Motion carries seven to zero. Window {window_index + 1}."

        first = worker.process_batch([chunk])
        first_pass_committed_count += len(first.committed_review_items)
        commit_started = time.perf_counter()
        second = worker.process_batch([chunk])
        commit_latencies.append(time.perf_counter() - commit_started)
        second_pass_committed_count += len(second.committed_review_items)
        duplicate_review_item_count += len(second.duplicate_review_item_ids)

        if second.hls_result is None or not second.hls_result.hls_outputs:
            raise RuntimeError("live caption worker did not publish HLS captions after stable cue")
        hls_output = second.hls_result.hls_outputs[0]

    if hls_output is None or first_chunk is None:
        raise RuntimeError("live caption proof produced no HLS output")

    caption_segment_path = hls_output.segment_paths[0]
    original_segment_text = caption_segment_path.read_text(encoding="utf-8")
    manifest_text = package.manifest_path.read_text(encoding="utf-8")

    runtime.text = "Motion fails seven to zero."
    rewrite_attempt = worker.process_batch([first_chunk])
    after_rewrite_attempt = caption_segment_path.read_text(encoding="utf-8")

    committed_text = "Motion carries seven to zero. Window 1."
    attempted_rewrite_text = "Motion fails seven to zero."
    manifest_has_subtitle_track = 'TYPE=SUBTITLES,GROUP-ID="subtitles"' in manifest_text
    caption_segment_has_text = committed_text in original_segment_text
    no_retroactive_rewrite = (
        original_segment_text == after_rewrite_attempt
        and attempted_rewrite_text not in after_rewrite_attempt
        and rewrite_attempt.committed_review_items == []
        and (rewrite_attempt.hls_result is None or rewrite_attempt.hls_result.hls_outputs == [])
    )
    review_items = store.list(asset_id="live-caption-proof")
    max_commit_latency = max(commit_latencies)
    passed = (
        first_pass_committed_count == 0
        and second_pass_committed_count == window_count
        and len(review_items) == window_count
        and duplicate_review_item_count == 0
        and manifest_has_subtitle_track
        and caption_segment_has_text
        and no_retroactive_rewrite
        and max_commit_latency <= latency_budget_seconds
    )

    return LiveCaptionProofResult(
        asset_id="live-caption-proof",
        window_count=window_count,
        latency_budget_seconds=latency_budget_seconds,
        max_commit_latency_seconds=round(max_commit_latency, 4),
        mean_commit_latency_seconds=round(mean(commit_latencies), 4),
        first_pass_committed_count=first_pass_committed_count,
        second_pass_committed_count=second_pass_committed_count,
        review_item_count=len(review_items),
        duplicate_review_item_count=duplicate_review_item_count,
        manifest_path=str(package.manifest_path),
        caption_playlist_path=str(hls_output.playlist_path),
        caption_segment_path=str(caption_segment_path),
        manifest_has_subtitle_track=manifest_has_subtitle_track,
        caption_segment_has_text=caption_segment_has_text,
        no_retroactive_rewrite=no_retroactive_rewrite,
        committed_text=committed_text,
        attempted_rewrite_text=attempted_rewrite_text,
        passed=passed,
    )


if __name__ == "__main__":
    sys.exit(main())

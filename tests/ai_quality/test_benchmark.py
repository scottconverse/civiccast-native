# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the v1.0 AI quality benchmark baseline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from civiccast.ai_quality.benchmark import build_default_corpus, run_ai_benchmark_suite


def test_ai_benchmark_suite_records_caption_translation_and_summary_scores() -> None:
    result = run_ai_benchmark_suite()

    assert result.passed is True
    assert len(result.caption_scores) == 2
    assert len(result.translation_scores) == 3
    assert len(result.summary_scores) == 1
    assert all(score.word_error_rate <= score.tolerance for score in result.caption_scores)
    assert all(score.bleu >= score.bleu_floor for score in result.translation_scores)
    assert all(score.comet_adequacy >= score.comet_floor for score in result.translation_scores)
    assert all(score.rouge_l >= score.rouge_l_floor for score in result.summary_scores)
    assert all(
        score.factual_correctness >= score.factual_correctness_floor
        for score in result.summary_scores
    )


def test_default_corpus_is_machine_readable() -> None:
    corpus = build_default_corpus()

    assert corpus.corpus_id == "civiccast-v1.0-ai-baseline-2026-05-15"
    assert corpus.caption_fixtures[0].fixture_id == "caption-motion-001"
    assert corpus.translation_fixtures[0].reference_translation == "la mocion se aprueba"
    assert corpus.summary_fixtures[0].cues[-1].text.endswith("Motion passes 2-1.")


def test_ai_benchmark_script_writes_tracked_evidence_shape(tmp_path: Path) -> None:
    corpus_output = tmp_path / "corpus.json"
    result_output = tmp_path / "result.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_ai_benchmarks.py",
            "--corpus-output",
            str(corpus_output),
            "--result-output",
            str(result_output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "ai-benchmarks: PASS" in completed.stdout
    corpus = json.loads(corpus_output.read_text(encoding="utf-8"))
    result = json.loads(result_output.read_text(encoding="utf-8"))
    assert corpus["corpus_id"] == result["corpus_id"]
    assert result["passed"] is True

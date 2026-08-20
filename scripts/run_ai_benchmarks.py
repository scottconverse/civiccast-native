# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the v1.0 deterministic AI quality benchmark suite."""

from __future__ import annotations

import argparse
from pathlib import Path

from civiccast.ai_quality.benchmark import build_default_corpus, run_ai_benchmark_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-output",
        type=Path,
        default=Path("docs/releases/evidence/v1.0-ai-benchmark-corpus.json"),
    )
    parser.add_argument(
        "--result-output",
        type=Path,
        default=Path("docs/releases/evidence/v1.0-ai-benchmark-baseline.json"),
    )
    args = parser.parse_args()

    corpus = build_default_corpus()
    result = run_ai_benchmark_suite(corpus)
    args.corpus_output.parent.mkdir(parents=True, exist_ok=True)
    args.corpus_output.write_text(corpus.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.result_output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if not result.passed:
        raise SystemExit("ai-benchmarks: FAIL")
    print(
        "ai-benchmarks: PASS "
        f"corpus={corpus.corpus_id} "
        f"caption={len(result.caption_scores)} "
        f"translation={len(result.translation_scores)} "
        f"summary={len(result.summary_scores)}"
    )


if __name__ == "__main__":
    main()

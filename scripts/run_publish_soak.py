# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run the v1.0 nightly three-tier publish soak proof."""

from __future__ import annotations

import argparse
from pathlib import Path

from civiccast.publish.soak import run_publish_soak


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=24,
        help="Number of deterministic publish cycles to run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/v1.0-publish-soak-result.json"),
        help="Path for the machine-readable JSON evidence.",
    )
    args = parser.parse_args()

    result = run_publish_soak(iterations=args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        "publish-soak: PASS "
        f"iterations={result.iterations_completed} "
        f"duration_seconds={result.duration_seconds} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()

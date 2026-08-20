#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run a finite, replayable detect-test-pollution shuffle campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

DEFAULT_RUNS = 3
DEFAULT_SEED = 1_542_676_187


class PollutionDetectorError(RuntimeError):
    """A bounded pollution campaign could not complete cleanly."""


def load_testids(path: Path) -> list[str]:
    testids = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not testids:
        raise PollutionDetectorError("test-id input is empty")
    if len(set(testids)) != len(testids):
        raise PollutionDetectorError("test-id input contains duplicates")
    return testids


def shuffled_orders(
    testids: Sequence[str],
    *,
    runs: int,
    seed: int,
) -> list[list[str]]:
    if runs <= 0:
        raise PollutionDetectorError("run count must be positive")
    randomizer = random.Random(seed)
    working = list(testids)
    orders: list[list[str]] = []
    for _ in range(runs):
        randomizer.shuffle(working)
        orders.append(working.copy())
    return orders


def order_sha256(testids: Sequence[str]) -> str:
    payload = "".join(f"{testid}\n" for testid in testids).encode()
    return hashlib.sha256(payload).hexdigest()


def common_test_path(testids: Sequence[str]) -> str:
    paths = [testid.split("::", 1)[0] for testid in testids]
    return os.path.commonpath(paths) or "."


def validate_result_records(
    expected_testids: Sequence[str],
    results: object,
    *,
    pass_number: int,
) -> int:
    """Require one explicit ``true`` result for every requested test id."""
    if not isinstance(results, dict):
        raise PollutionDetectorError(f"pollution pass {pass_number} results are not a JSON object")

    expected = set(expected_testids)
    actual = set(results)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    failed_or_skipped = sorted(testid for testid, passed in results.items() if passed is not True)

    problems: list[str] = []
    if missing:
        problems.append(f"missing records: {', '.join(missing)}")
    if unexpected:
        problems.append(f"unexpected records: {', '.join(unexpected)}")
    if failed_or_skipped:
        problems.append(f"failed or skipped records: {', '.join(failed_or_skipped)}")
    if problems:
        raise PollutionDetectorError(
            f"pollution pass {pass_number} returned an invalid result set; " + "; ".join(problems)
        )
    return len(results)


def run_campaign(
    testids: Sequence[str],
    *,
    runs: int,
    seed: int,
) -> dict[str, object]:
    orders = shuffled_orders(testids, runs=runs, seed=seed)
    test_path = common_test_path(testids)
    receipts: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="civiccast-pollution-") as temporary:
        root = Path(temporary)
        for number, order in enumerate(orders, start=1):
            input_path = root / f"order-{number}.txt"
            result_path = root / f"results-{number}.json"
            input_path.write_text(
                "".join(f"{testid}\n" for testid in order),
                encoding="utf-8",
                newline="\n",
            )
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "detect_test_pollution",
                "-p",
                "no:randomly",
                "-q",
                "-q",
                test_path,
                f"--dtp-testids-input-file={input_path}",
                f"--dtp-results-output-file={result_path}",
            ]
            print(f"pollution pass {number}/{runs}: {order_sha256(order)}", flush=True)
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if not result_path.is_file():
                if completed.returncode != 0:
                    print(completed.stdout, file=sys.stderr, end="")
                raise PollutionDetectorError(
                    f"pollution pass {number} produced no result file; "
                    f"exit code {completed.returncode}; "
                    f"order SHA-256 {order_sha256(order)}"
                )
            results = json.loads(result_path.read_text(encoding="utf-8"))
            result_count = validate_result_records(
                order,
                results,
                pass_number=number,
            )
            if completed.returncode != 0:
                print(completed.stdout, file=sys.stderr, end="")
                raise PollutionDetectorError(
                    f"pollution pass {number} failed with exit code "
                    f"{completed.returncode}; order SHA-256 {order_sha256(order)}"
                )
            receipts.append(
                {
                    "order_sha256": order_sha256(order),
                    "result_records": result_count,
                    "run": number,
                    "status": "PASS",
                }
            )
    return {
        "runs": receipts,
        "schema_version": 1,
        "seed": seed,
        "status": "PASS",
        "test_count": len(testids),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testids-file", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_campaign(
            load_testids(args.testids_file),
            runs=args.runs,
            seed=args.seed,
        )
        output = args.output.resolve()
        if output.exists():
            raise PollutionDetectorError(f"output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        output.write_text(rendered, encoding="utf-8", newline="\n")
        print(rendered, end="")
    except (OSError, json.JSONDecodeError, PollutionDetectorError) as error:
        raise SystemExit(f"run_bounded_pollution_detector: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

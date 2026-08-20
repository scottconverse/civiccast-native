# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for the finite pollution-detector runner."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_bounded_pollution_detector.py"
    spec = importlib.util.spec_from_file_location("bounded_pollution_detector", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


detector = _load()


def test_shuffle_campaign_is_finite_and_replayable() -> None:
    first = detector.shuffled_orders(["a", "b", "c", "d"], runs=3, seed=42)
    second = detector.shuffled_orders(["a", "b", "c", "d"], runs=3, seed=42)

    assert first == second
    assert len(first) == 3
    assert all(sorted(order) == ["a", "b", "c", "d"] for order in first)
    assert len({detector.order_sha256(order) for order in first}) == 3


def test_shuffle_campaign_rejects_nonpositive_run_count() -> None:
    with pytest.raises(detector.PollutionDetectorError, match="positive"):
        detector.shuffled_orders(["a"], runs=0, seed=42)


def test_testid_loader_rejects_empty_and_duplicate_inputs(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    duplicate = tmp_path / "duplicate.txt"
    duplicate.write_text("tests/a.py::test_a\ntests/a.py::test_a\n", encoding="utf-8")

    with pytest.raises(detector.PollutionDetectorError, match="empty"):
        detector.load_testids(empty)
    with pytest.raises(detector.PollutionDetectorError, match="duplicates"):
        detector.load_testids(duplicate)


def test_common_test_path_uses_the_shared_collection_root() -> None:
    assert (
        detector.common_test_path(
            [
                "tests/captions/test_a.py::test_a",
                "tests/native/test_b.py::test_b",
            ]
        )
        == "tests"
    )


@pytest.mark.parametrize(
    ("result_records", "message"),
    [
        ({"tests/a.py::test_a": True}, "missing"),
        (
            {
                "tests/a.py::test_a": True,
                "tests/b.py::test_b": True,
                "tests/c.py::test_c": True,
            },
            "unexpected",
        ),
        (
            {
                "tests/a.py::test_a": True,
                "tests/b.py::test_b": False,
            },
            "failed or skipped",
        ),
    ],
)
def test_campaign_rejects_incomplete_extra_or_false_result_records(
    monkeypatch: pytest.MonkeyPatch,
    result_records: dict[str, bool],
    message: str,
) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        result_arg = next(
            argument for argument in command if argument.startswith("--dtp-results-output-file=")
        )
        result_path = Path(result_arg.split("=", 1)[1])
        result_path.write_text(json.dumps(result_records), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(detector.PollutionDetectorError, match=message):
        detector.run_campaign(
            ["tests/a.py::test_a", "tests/b.py::test_b"],
            runs=1,
            seed=42,
        )


def test_campaign_receipt_counts_exactly_validated_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = {
        "tests/a.py::test_a": True,
        "tests/b.py::test_b": True,
    }

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        result_arg = next(
            argument for argument in command if argument.startswith("--dtp-results-output-file=")
        )
        Path(result_arg.split("=", 1)[1]).write_text(
            json.dumps(records),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    report = detector.run_campaign(list(records), runs=1, seed=42)

    assert report["runs"] == [
        {
            "order_sha256": detector.order_sha256(
                detector.shuffled_orders(list(records), runs=1, seed=42)[0]
            ),
            "result_records": 2,
            "run": 1,
            "status": "PASS",
        }
    ]

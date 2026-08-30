# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure decision logic for the start-failure marker (Defect B, field evidence
candidate 4eca729, 2026-08-29): a station that cannot start must log its real
reason and, once a crash loop is confirmed, leave an operator-readable
document behind. This module is stdlib-only (house lazy-import rule), so
these tests run on any platform -- no pywin32, no real service."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from civiccast.native.supervisor import start_failure_marker


def _make_logger(name: str) -> tuple[logging.Logger, list[logging.LogRecord]]:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    return logger, records


def test_exception_diagnostic_detail_prefers_str_and_falls_back_to_repr() -> None:
    assert start_failure_marker.exception_diagnostic_detail(ValueError("boom")) == "boom"

    class _Blank(Exception):
        def __str__(self) -> str:
            return ""

    detail = start_failure_marker.exception_diagnostic_detail(_Blank())
    assert detail  # never a blank string
    assert "_Blank" in detail


def test_a_single_failure_logs_but_does_not_write_the_marker(tmp_path: Path) -> None:
    logger, records = _make_logger("test.start-failure.single")

    start_failure_marker.record_start_failure(tmp_path, logger, RuntimeError("first failure"))

    assert not start_failure_marker.marker_path(tmp_path).exists()
    assert any("first failure" in record.getMessage() for record in records)
    state = json.loads((tmp_path / "station-start-failures.json").read_text(encoding="utf-8"))
    assert state["consecutive_failures"] == 1
    assert state["last_error_type"] == "RuntimeError"
    assert state["last_error_detail"] == "first failure"


def test_the_marker_appears_only_once_the_threshold_is_reached(tmp_path: Path) -> None:
    logger, _records = _make_logger("test.start-failure.threshold")
    marker = start_failure_marker.marker_path(tmp_path)

    for attempt in range(1, start_failure_marker.CONSECUTIVE_FAILURE_THRESHOLD + 1):
        start_failure_marker.record_start_failure(
            tmp_path, logger, RuntimeError(f"attempt {attempt}")
        )
        if attempt < start_failure_marker.CONSECUTIVE_FAILURE_THRESHOLD:
            assert not marker.exists(), f"marker must not exist after only {attempt} failures"
        else:
            assert marker.exists(), "marker must exist once the threshold is reached"

    text = marker.read_text(encoding="utf-8")
    assert "CivicCast (Native) -- Station Cannot Start" in text
    assert (
        f"Consecutive failed starts: {start_failure_marker.CONSECUTIVE_FAILURE_THRESHOLD}" in text
    )
    assert "RuntimeError" in text
    assert f"attempt {start_failure_marker.CONSECUTIVE_FAILURE_THRESHOLD}" in text
    assert "restarting it again will not fix this" in text.lower()


def test_record_start_success_clears_the_counter_and_the_marker(tmp_path: Path) -> None:
    logger, _records = _make_logger("test.start-failure.clears")
    for _ in range(start_failure_marker.CONSECUTIVE_FAILURE_THRESHOLD):
        start_failure_marker.record_start_failure(tmp_path, logger, RuntimeError("x"))
    assert start_failure_marker.marker_path(tmp_path).exists()
    assert (tmp_path / "station-start-failures.json").exists()

    start_failure_marker.record_start_success(tmp_path)

    assert not start_failure_marker.marker_path(tmp_path).exists()
    assert not (tmp_path / "station-start-failures.json").exists()


def test_record_start_success_on_an_already_clean_root_is_a_harmless_no_op(
    tmp_path: Path,
) -> None:
    # Never written to before -- must not raise just because there is nothing
    # to clear.
    start_failure_marker.record_start_success(tmp_path)
    assert not start_failure_marker.marker_path(tmp_path).exists()


def test_a_different_error_still_advances_the_same_consecutive_counter(tmp_path: Path) -> None:
    """ "Consecutive" here means consecutive START ATTEMPTS, not an identical
    error message every time -- a station flapping between two related
    misconfigurations is exactly as much a crash loop as one with a single
    unchanging reason, and must be surfaced just as loudly."""

    logger, _records = _make_logger("test.start-failure.mixed-errors")
    marker = start_failure_marker.marker_path(tmp_path)

    start_failure_marker.record_start_failure(tmp_path, logger, RuntimeError("reason A"))
    start_failure_marker.record_start_failure(tmp_path, logger, ValueError("reason B"))
    assert not marker.exists()
    start_failure_marker.record_start_failure(tmp_path, logger, RuntimeError("reason A again"))

    assert marker.exists()
    assert "reason A again" in marker.read_text(encoding="utf-8")


def test_record_start_failure_never_raises_when_the_root_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure being recorded is never allowed to mask the ORIGINAL
    failure with a new, more confusing one -- a write error here must be
    swallowed (with a warning), not propagated."""

    logger, records = _make_logger("test.start-failure.write-error")
    # A root that is actually a FILE (mkdir will fail with NotADirectoryError,
    # a subclass of OSError, on the write attempts beneath it).
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("x", encoding="utf-8")

    start_failure_marker.record_start_failure(blocked_root, logger, RuntimeError("boom"))

    assert any("could not persist" in record.getMessage() for record in records)

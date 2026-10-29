# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retained PDF processing: real subprocess reading and bounded resume behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from reportlab.pdfgen import canvas

from civiccast.agenda_import import pdf_processing as processing


def _pdf(path: Path, pages: int = 1) -> Path:
    document = canvas.Canvas(str(path))
    for number in range(1, pages + 1):
        document.drawString(72, 700, f"Page {number}: Council agenda")
        document.showPage()
    document.save()
    return path


def test_real_subprocess_crosses_batch_boundary_and_resumes(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "agenda.pdf", 13)
    checkpoint = tmp_path / "retained.json"
    partial = processing.process_pdf(path, checkpoint, max_pages=12)
    assert partial.status == "page_limit"
    assert partial.pages_read == 12
    assert all(page.method == "pypdf" for page in partial.pages)
    saved = json.loads(checkpoint.read_text())
    assert len(saved["pages"]) == 12
    # Altering a retained page demonstrates it is reused, rather than re-read.
    saved["pages"][0]["text"] = "Retained first page"
    checkpoint.write_text(json.dumps(saved))
    resumed = processing.process_pdf(path, checkpoint)
    assert resumed.complete
    assert resumed.pages_read == 13
    assert resumed.pages[0].text == "Retained first page"
    assert "Page 13" in resumed.text


def test_checkpoint_identity_mismatch_preserves_original_checkpoint(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "agenda.pdf")
    checkpoint = tmp_path / "retained.json"
    processing.process_pdf(path, checkpoint)
    saved = checkpoint.read_bytes()
    path.write_bytes(path.read_bytes() + b"\nchanged identity")
    with pytest.raises(ValueError, match="does not match"):
        processing.process_pdf(path, checkpoint)
    assert checkpoint.read_bytes() == saved


@pytest.mark.parametrize("pages,budget,read", [(1, 1, 0), (2, 4, 1), (2, 8, 2)])
def test_budget_checked_before_single_or_final_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pages: int,
    budget: int,
    read: int,
) -> None:
    path = _pdf(tmp_path / "agenda.pdf", pages)

    def worker(*args: Any) -> dict[str, Any]:
        if args[1].endswith("metadata"):
            return {"status": "complete", "pages_total": pages}
        return {"status": "complete", "text": "text", "method": "pypdf"}

    monkeypatch.setattr(processing, "_run_worker", worker)
    result = processing.process_pdf(path, tmp_path / "checkpoint.json", max_chars=budget)
    assert result.pages_read == read
    assert result.status == ("complete" if read == pages else "text_limit")


def test_failed_middle_page_retained_successes_and_retry_only_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _pdf(tmp_path / "agenda.pdf", 3)
    checkpoint = tmp_path / "checkpoint.json"
    calls: list[tuple[str, int]] = []
    fail = True

    def worker(*args: Any) -> dict[str, Any]:
        mode, page = args[1], args[2]
        calls.append((mode, page))
        if mode.endswith("metadata"):
            return {"status": "complete", "pages_total": 3}
        if page == 2 and fail:
            return {"status": "unrecoverable", "issue": "Malformed page"}
        return {"status": "complete", "text": f"Page {page}", "method": "pypdf"}

    monkeypatch.setattr(processing, "_run_worker", worker)
    partial = processing.process_pdf(path, checkpoint)
    assert partial.status == "partial"
    assert partial.pages_read == 2
    assert partial.pages[1].status == "unrecoverable"
    assert partial.pages[1].issue
    assert partial.pages[2].text == "Page 3"
    fail = False
    calls.clear()
    assert processing.process_pdf(path, checkpoint).complete
    assert calls == [("native", 2)]


def test_native_timeout_uses_independent_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def worker(*args: Any) -> dict[str, Any]:
        mode = args[1]
        calls.append(mode)
        if mode.endswith("metadata"):
            return {"status": "complete", "pages_total": 1}
        if mode == "native":
            return {"status": "timeout", "issue": "Native timed out"}
        return {"status": "complete", "text": "Independent text", "method": "pdfium"}

    monkeypatch.setattr(processing, "_run_worker", worker)
    result = processing.process_pdf(_pdf(tmp_path / "agenda.pdf"), tmp_path / "checkpoint.json")
    assert result.complete
    assert result.pages[0].method == "pdfium"
    assert calls == ["native_metadata", "native", "pdfium"]


def test_cancel_keeps_atomic_completed_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    stop = False

    def worker(*args: Any) -> dict[str, Any]:
        if args[1].endswith("metadata"):
            return {"status": "complete", "pages_total": 3}
        return {"status": "complete", "text": "Retained", "method": "pypdf"}

    def saved(result: processing.PdfProcessingResult) -> None:
        nonlocal stop
        # The callback is after the completed page is durably replaced.
        assert json.loads(checkpoint.read_text())["sha256"] == result.sha256
        stop = result.pages_read == 1

    monkeypatch.setattr(processing, "_run_worker", worker)
    result = processing.process_pdf(
        _pdf(tmp_path / "agenda.pdf", 3),
        checkpoint,
        cancelled=lambda: stop,
        on_checkpoint=saved,
    )
    assert result.status == "cancelled"
    assert result.pages_read == 1
    assert len(json.loads(checkpoint.read_text())["pages"]) == 1


def test_attempt_deadline_retains_page_and_resume_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    clock = 0.0

    def worker(*args: Any) -> dict[str, Any]:
        if args[1].endswith("metadata"):
            return {"status": "complete", "pages_total": 2}
        return {"status": "complete", "text": f"Page {args[2]}", "method": "pypdf"}

    def saved(result: processing.PdfProcessingResult) -> None:
        nonlocal clock
        if result.pages_read == 1:
            clock = 11.0

    monkeypatch.setattr(processing, "_run_worker", worker)
    monkeypatch.setattr(processing.time, "monotonic", lambda: clock)
    path = _pdf(tmp_path / "agenda.pdf", 2)
    partial = processing.process_pdf(
        path,
        checkpoint,
        time_budget_seconds=10,
        on_checkpoint=saved,
    )
    assert partial.status == "time_limit"
    assert partial.pages_read == 1
    assert processing.process_pdf(path, checkpoint).complete


def test_actual_worker_timeout_terminates_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Substitute only the worker script; exercise production spawning and timeout cleanup.
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(processing, "__file__", str(script))
    result = processing._run_worker(
        tmp_path / "unused.pdf",
        "native",
        1,
        0.1,
        None,
        None,
        100,
    )
    assert result["status"] == "timeout"


def test_blank_page_confirmed_by_renderer(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    path = tmp_path / "blank.pdf"
    document = canvas.Canvas(str(path))
    document.showPage()
    document.save()
    result = processing.process_pdf(path, tmp_path / "checkpoint.json")
    assert result.complete
    assert result.pages[0].status == "blank"
    assert result.pages[0].method == "pdfium_render"


def test_independent_pdfium_text_engine_in_actual_subprocess(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    path = _pdf(tmp_path / "agenda.pdf")
    result = processing._run_worker(path, "pdfium", 1, 15, None, None, 10_000)
    assert result["status"] == "complete"
    assert result["method"] == "pdfium"
    assert "Council agenda" in result["text"]


def test_visual_content_is_not_marked_blank_when_ocr_missing(tmp_path: Path) -> None:
    pytest.importorskip("pypdfium2")
    path = tmp_path / "drawing.pdf"
    document = canvas.Canvas(str(path))
    document.rect(100, 100, 200, 200, fill=1)
    document.showPage()
    document.save()
    # A deliberately invalid executable has the same incomplete semantics as missing OCR.
    result = processing.process_pdf(
        path,
        tmp_path / "checkpoint.json",
        tesseract_cmd=str(tmp_path / "absent-tesseract"),
    )
    assert not result.complete
    assert result.pages_read == 0
    assert result.pages[0].status == "unavailable"
    assert result.pages[0].issue


def test_checkpoint_path_cannot_overwrite_pdf(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "agenda.pdf")
    with pytest.raises(ValueError, match="differ"):
        processing.process_pdf(path, path)


def test_document_page_cap_cannot_be_bypassed_by_resume(tmp_path: Path) -> None:
    path = _pdf(tmp_path / "agenda.pdf", 3)
    checkpoint = tmp_path / "checkpoint.json"
    first = processing.process_pdf(path, checkpoint, max_pages=2)
    assert first.status == "page_limit"
    assert first.pages_read == 2
    resumed = processing.process_pdf(path, checkpoint, max_pages=2)
    assert resumed.status == "page_limit"
    assert resumed.pages_read == 2


def test_corrupted_native_encoding_uses_same_page_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def worker(*args: Any) -> dict[str, Any]:
        mode, page = args[1], args[2]
        calls.append((mode, page))
        if mode.endswith("metadata"):
            return {"status": "complete", "pages_total": 1}
        if mode == "native":
            return {"status": "complete", "text": "PUBLIC\ufffdHEARING", "method": "pypdf"}
        return {"status": "complete", "text": "PUBLIC HEARING", "method": "pdfium"}

    monkeypatch.setattr(processing, "_run_worker", worker)
    result = processing.process_pdf(_pdf(tmp_path / "agenda.pdf"), tmp_path / "checkpoint.json")
    assert result.complete
    assert result.text == "PUBLIC HEARING"
    assert result.pages[0].method == "pdfium"
    assert calls == [("native_metadata", 0), ("native", 1), ("pdfium", 1)]


def test_rejected_checkpoint_text_retained_but_not_counted_then_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _pdf(tmp_path / "agenda.pdf")
    checkpoint = tmp_path / "checkpoint.json"
    processing.process_pdf(path, checkpoint)
    raw = json.loads(checkpoint.read_text())
    old = "Damaged\ufffd" * 100
    raw["pages"][0]["text"] = old
    checkpoint.write_text(json.dumps(raw))
    recovered = False

    def worker(*args: Any) -> dict[str, Any]:
        if not recovered:
            return {"status": "unrecoverable", "issue": "Recovery unavailable"}
        return {"status": "complete", "text": "Clean", "method": "pdfium"}

    monkeypatch.setattr(processing, "_run_worker", worker)
    failed = processing.process_pdf(path, checkpoint, max_chars=5)
    assert not failed.complete
    assert failed.pages_read == 0
    assert failed.text == ""
    assert failed.pages[0].text == old
    assert failed.pages[0].method == "pypdf"
    assert failed.pages[0].status not in {"complete", "blank"}
    recovered = True
    clean = processing.process_pdf(path, checkpoint, max_chars=5)
    assert clean.complete
    assert clean.text == "Clean"
    assert clean.pages[0].method == "pdfium"


def test_pdfium_missing_glyphs_force_render_instead_of_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdfium = pytest.importorskip("pypdfium2")
    monkeypatch.setattr(pdfium.PdfTextPage, "get_text_range", lambda _self: "PUBLIC\ufffdHEARING")
    path = _pdf(tmp_path / "agenda.pdf")
    result = processing._worker_extract(
        str(path),
        "pdfium",
        1,
        tmp_path,
        str(tmp_path / "missing-tesseract"),
        15,
    )
    assert result["status"] == "unavailable"
    assert result["method"] == "pdfium_render"

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retained, resumable local PDF reading, independent of agenda interpretation.

Each engine runs in a disposable subprocess. Checkpoints contain page text and
provenance, bound to the original's SHA256; a failed page never erases successful
pages. The 12-page batching/retained-page approach was informed by TownReporter's
story-documents.server.ts; this implementation does not copy its source.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SUCCESS = {"complete", "blank"}


def _resolve_tesseract(command: str) -> tuple[str | None, Path | None]:
    """Prefer the signed app-local runtime, independent of service PATH/profile."""
    if command:
        return shutil.which(command), None
    bundled = Path(sys.executable).resolve().parent / "OCR"
    if (bundled / "tesseract.exe").is_file() and (bundled / "tessdata/eng.traineddata").is_file():
        return str(bundled / "tesseract.exe"), bundled / "tessdata"
    return shutil.which("tesseract"), None


def _readable_text(text: str) -> bool:
    """Missing glyph substitutions make a text layer unsafe as complete evidence."""
    return bool(text.strip()) and "\ufffd" not in text


@dataclass(frozen=True)
class PdfPageResult:
    page: int
    text: str = ""
    method: str = "none"
    status: str = "unrecoverable"
    issue: str | None = None


@dataclass
class PdfProcessingResult:
    sha256: str
    pages_total: int | None = None
    pages: list[PdfPageResult] = field(default_factory=list)
    status: str = "partial"
    issues: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(
            page.text for page in self.pages if page.status in _SUCCESS and page.text
        )

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def pages_read(self) -> int:
        return sum(page.status in _SUCCESS for page in self.pages)


def _save_checkpoint(path: Path, result: PdfProcessingResult) -> None:
    """Replace atomically on the same filesystem, flushing page text first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, **asdict(result)}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Only publish under the agenda backup gate; OCR remains interruptible
        # and preview polling can continue while a database snapshot is taken.
        from civiccast.agenda_import.documents import checkpoint_snapshot_lock

        with checkpoint_snapshot_lock(path):
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_checkpoint(path: Path, digest: str) -> PdfProcessingResult:
    if not path.exists():
        return PdfProcessingResult(sha256=digest)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw["version"] != 1 or raw["sha256"] != digest:
            raise ValueError("Checkpoint does not match this PDF or checkpoint version")
        total = raw["pages_total"]
        if total is not None and (type(total) is not int or total < 1):
            raise ValueError("Invalid checkpoint page count")
        pages: list[PdfPageResult] = []
        seen: set[int] = set()
        for item in raw["pages"]:
            page = PdfPageResult(**item)
            if (
                type(page.page) is not int
                or page.page < 1
                or (total is not None and page.page > total)
                or page.page in seen
                or not isinstance(page.text, str)
                or not isinstance(page.method, str)
                or not isinstance(page.status, str)
                or (page.status == "complete" and not page.text.strip())
                or (page.status == "blank" and page.text)
            ):
                raise ValueError("Invalid checkpoint page")
            if page.status == "complete" and not _readable_text(page.text):
                page = PdfPageResult(
                    page.page,
                    page.text,
                    page.method,
                    "quality_rejected",
                    "Retained text contains missing-glyph replacements; retry required",
                )
            seen.add(page.page)
            pages.append(page)
        return PdfProcessingResult(digest, total, sorted(pages, key=lambda p: p.page))
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid PDF checkpoint; original checkpoint preserved") from error


def _stop_worker(process: subprocess.Popen[bytes]) -> None:
    """Kill the owned worker tree, including a running local OCR executable."""
    if sys.platform == "win32":
        # The worker is still owned/unreaped, so its PID cannot have been reused.
        try:
            subprocess.run(  # noqa: S603 -- fixed OS executable, owned numeric PID
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def _run_worker(
    path: Path,
    mode: str,
    page: int,
    timeout: float,
    cancelled: Callable[[], bool] | None,
    tesseract_cmd: str | None,
    max_chars: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="civiccast-pdf-") as directory:
        output = Path(directory) / "result.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            mode,
            str(path),
            str(page),
            str(output),
            str(max_chars),
            tesseract_cmd or "",
            str(timeout),
        ]
        process = subprocess.Popen(  # noqa: S603 -- own script, no shell
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    _stop_worker(process)
                    return {"status": "cancelled", "issue": "Reading cancelled"}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_worker(process)
                    return {"status": "timeout", "issue": f"{mode} worker timed out"}
                time.sleep(min(0.05, remaining))
            if process.returncode != 0 or not output.exists():
                return {"status": "unrecoverable", "issue": f"{mode} worker failed"}
            # A worker must never cause an unbounded parent-side JSON read.
            if output.stat().st_size > max(1_000_000, max_chars * 12 + 10_000):
                return {"status": "text_limit", "issue": "Page exceeds retained text budget"}
            return dict(json.loads(output.read_text(encoding="utf-8")))
        finally:
            if process.poll() is None:
                _stop_worker(process)


def process_pdf(
    pdf_path: str | Path,
    checkpoint_path: str | Path,
    *,
    batch_size: int = 12,
    max_pages: int = 500,
    max_chars: int = 2_000_000,
    time_budget_seconds: float = 20 * 60,
    page_timeout_seconds: float = 45,
    cancelled: Callable[[], bool] | None = None,
    on_checkpoint: Callable[[PdfProcessingResult], None] | None = None,
    tesseract_cmd: str | None = None,
) -> PdfProcessingResult:
    """Read consecutive batches in one bounded attempt, retaining every success.

    ``max_pages`` limits the document pages read, across all attempts; ``max_chars``
    limits all retained text. Increase the relevant limit explicitly to read
    beyond a limit. Only successful or visually confirmed blank pages are
    skipped on resume. Callers must serialize attempts for the same checkpoint.
    A corrupt/foreign checkpoint raises ValueError without overwriting it.
    """
    if (
        batch_size < 1
        or max_pages < 1
        or max_chars < 1
        or not math.isfinite(time_budget_seconds)
        or time_budget_seconds <= 0
        or not math.isfinite(page_timeout_seconds)
        or page_timeout_seconds <= 0
    ):
        raise ValueError("PDF reading limits must be positive and finite")
    started = time.monotonic()
    deadline = started + time_budget_seconds
    path, checkpoint = Path(pdf_path).resolve(), Path(checkpoint_path).resolve()
    if path == checkpoint:
        raise ValueError("Checkpoint must differ from the original PDF")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = _load_checkpoint(checkpoint, digest)
    retained = {page.page: page for page in result.pages}
    chars = sum(len(page.text) for page in result.pages if page.status in _SUCCESS)

    def save() -> None:
        result.pages = sorted(retained.values(), key=lambda page: page.page)
        _save_checkpoint(checkpoint, result)
        if on_checkpoint is not None:
            on_checkpoint(result)

    def worker(mode: str, page: int) -> dict[str, Any]:
        if cancelled is not None and cancelled():
            return {"status": "cancelled", "issue": "Reading cancelled"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "time_limit", "issue": "Attempt time limit reached"}
        return _run_worker(
            path,
            mode,
            page,
            min(page_timeout_seconds, remaining),
            cancelled,
            tesseract_cmd,
            max(0, max_chars - chars),
        )

    if chars > max_chars:
        result.status = "text_limit"
        result.issues.append("Retained text already exceeds this attempt's text budget")
        save()
        return result
    if result.pages_total is None:
        metadata = worker("native_metadata", 0)
        if metadata["status"] not in {"complete", "cancelled", "time_limit"}:
            metadata = worker("pdfium_metadata", 0)
        if metadata["status"] != "complete":
            result.status = metadata["status"]
            result.issues.append(metadata.get("issue", "Cannot determine PDF page count"))
            save()
            return result
        result.pages_total = metadata["pages_total"]
        save()
    pending = [
        page
        for page in range(1, min(result.pages_total, max_pages) + 1)
        if page not in retained or retained[page].status not in _SUCCESS
    ]
    stopped: str | None = None
    for offset in range(0, len(pending), batch_size):
        for page in pending[offset : offset + batch_size]:
            extracted = worker("native", page)
            if extracted["status"] == "complete" and not _readable_text(extracted.get("text", "")):
                extracted = {
                    "status": "no_text",
                    "issue": "Native text is empty or has missing glyphs",
                }
            if extracted["status"] not in _SUCCESS | {"cancelled", "time_limit", "text_limit"}:
                native_issue = extracted.get("issue", "Native text unavailable")
                extracted = worker("pdfium", page)
                if extracted["status"] not in _SUCCESS:
                    extracted["issue"] = (
                        f"{native_issue}; {extracted.get('issue', 'Fallback failed')}"
                    )
            status = extracted["status"]
            if status in {"cancelled", "time_limit", "text_limit"}:
                stopped = status
                result.issues.append(f"Page {page}: {extracted.get('issue', status)}")
                break
            text = extracted.get("text", "")
            if status == "complete" and not _readable_text(text):
                status = "quality_rejected"
                extracted["issue"] = "Fallback text is empty or has missing-glyph replacements"
            # Apply before accepting EVERY page, including single/final pages.
            if chars + len(text) > max_chars:
                stopped = "text_limit"
                result.issues.append(f"Page {page}: retained text budget exceeded")
                break
            previous = retained.get(page)
            method = extracted.get("method", "none")
            # Preserve rejected prior evidence if recovery fails, excluded from usable text.
            if status not in _SUCCESS and previous is not None and previous.text:
                text = previous.text
                method = previous.method
            retained[page] = PdfPageResult(
                page,
                text,
                method,
                status,
                extracted.get("issue"),
            )
            if status in _SUCCESS:
                chars += len(text)
            save()
        if stopped is not None:
            break
    success = sum(page.status in _SUCCESS for page in retained.values())
    result.status = (
        "complete"
        if success == result.pages_total
        else stopped
        or ("page_limit" if result.pages_total > max_pages else "partial" if success else "failed")
    )
    result.issues.extend(
        f"Page {page.page}: {page.issue or page.status}"
        for page in retained.values()
        if page.status not in _SUCCESS
    )
    save()
    return result


def _worker_extract(
    path: str,
    mode: str,
    page_number: int,
    directory: Path,
    tesseract_cmd: str,
    timeout: float,
) -> dict[str, Any]:
    """Subprocess-only parsing/rendering. No PDF engine executes in the parent."""
    if mode.startswith("native"):
        from pypdf import PdfReader

        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return {"status": "unrecoverable", "issue": "PDF requires a password"}
        if mode == "native_metadata":
            return {"status": "complete", "pages_total": len(reader.pages)}
        text = reader.pages[page_number - 1].extract_text() or ""
        if _readable_text(text):
            return {"status": "complete", "text": text, "method": "pypdf"}
        return {"status": "no_text", "issue": "Native text is empty or has missing glyphs"}

    try:
        # PDFium's Python wrapper currently ships without a py.typed marker.
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError:
        return {"status": "unavailable", "issue": "Local PDFium fallback is not installed"}
    with pdfium.PdfDocument(path) as document:
        if mode == "pdfium_metadata":
            return {"status": "complete", "pages_total": len(document)}
        with closing(document[page_number - 1]) as page:
            text = ""
            # An invalid text layer can still have a useful rendered page.
            with suppress(Exception), closing(page.get_textpage()) as textpage:
                text = textpage.get_text_range()
            if _readable_text(text):
                return {"status": "complete", "text": text, "method": "pdfium"}
            # Bound render allocation to 20 million pixels and 300 dpi.
            width, height = page.get_size()
            scale = min(300 / 72, math.sqrt(20_000_000 / max(1, width * height)))
            bitmap = page.render(scale=scale)
            try:
                image = bitmap.to_pil().convert("RGB")
                # Only a uniformly white rendered page is confirmed blank.
                if all(low == 255 for low, _high in image.getextrema()):
                    return {"status": "blank", "method": "pdfium_render"}
                executable, tessdata = _resolve_tesseract(tesseract_cmd)
                if not executable:
                    return {
                        "status": "unavailable",
                        "method": "pdfium_render",
                        "issue": "Page has visual content but local Tesseract OCR is unavailable",
                    }
                image_path = directory / "page.bmp"
                image.save(image_path)
            finally:
                bitmap.close()
    output = directory / "ocr"
    subprocess.run(  # noqa: S603 -- configured local executable; no shell
        [
            executable,
            str(image_path),
            str(output),
            *(["--tessdata-dir", str(tessdata)] if tessdata else []),
            "-l",
            "eng",
            "--psm",
            "3",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=max(0.1, timeout - 0.5),
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    text = output.with_suffix(".txt").read_text(encoding="utf-8")
    if _readable_text(text):
        return {"status": "complete", "text": text, "method": "tesseract"}
    return {
        "status": "unrecoverable",
        "method": "tesseract",
        "issue": "Local OCR found no text on a page with visual content",
    }


def _worker_main() -> None:
    mode, path, page, output, limit, tesseract, timeout = sys.argv[2:]
    output_path = Path(output)
    try:
        result = _worker_extract(
            path, mode, int(page), output_path.parent, tesseract, float(timeout)
        )
        if len(result.get("text", "")) > int(limit):
            result = {"status": "text_limit", "issue": "Page exceeds retained text budget"}
        if result.get("pages_total") == 0:
            result = {"status": "unrecoverable", "issue": "PDF contains no pages"}
    except Exception as error:
        result = {"status": "unrecoverable", "issue": f"{type(error).__name__}: {error}"[:1000]}
    output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--worker":
    _worker_main()

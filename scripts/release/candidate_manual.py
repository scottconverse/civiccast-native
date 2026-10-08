#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Create and verify the exact-source manual bundle used by beta candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

MANUAL_SOURCE = "docs/USER-MANUAL.md"
PDF_FILENAME = "USER-MANUAL.pdf"
DOCX_FILENAME = "USER-MANUAL.docx"
MANIFEST_FILENAME = "USER-MANUAL.render.json"
RECEIPT_FILENAME = "candidate-manual-receipt.json"
DOCUMENT_FILENAMES = (PDF_FILENAME, DOCX_FILENAME)
PACKAGE_FILENAMES = (*DOCUMENT_FILENAMES, MANIFEST_FILENAME, RECEIPT_FILENAME)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class CandidateManualError(RuntimeError):
    """Fail-closed refusal for a missing or mismatched candidate manual."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_sha256(path: Path) -> str:
    """Hash canonical UTF-8 text so Windows and Linux checkouts agree."""
    try:
        normalized = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise CandidateManualError(f"cannot read manual source {path}: {exc}") from exc
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateManualError(f"{label} is missing or invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateManualError(f"{label} must contain a JSON object: {path}")
    return value


def _file_record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise CandidateManualError(f"candidate manual file is missing or empty: {path}")
    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _manifest_records(
    *, manual_dir: Path, repo_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = manual_dir / MANIFEST_FILENAME
    manifest = _read_json(manifest_path, label="manual render manifest")
    if manifest.get("source") != MANUAL_SOURCE:
        raise CandidateManualError(f"manual render manifest source must be {MANUAL_SOURCE!r}")

    source_path = repo_root / MANUAL_SOURCE
    current_source_sha = source_sha256(source_path)
    if manifest.get("source_sha256") != current_source_sha:
        raise CandidateManualError(
            "manual render manifest source hash does not match this candidate's USER-MANUAL.md"
        )

    items = manifest.get("artifacts")
    if not isinstance(items, list):
        raise CandidateManualError("manual render manifest artifacts must be a list")
    by_filename: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CandidateManualError("manual render manifest has a malformed artifact entry")
        filename = PurePosixPath(item["path"].replace("\\", "/")).name
        if filename in by_filename:
            raise CandidateManualError(f"manual render manifest repeats {filename!r}")
        by_filename[filename] = item
    if set(by_filename) != set(DOCUMENT_FILENAMES):
        raise CandidateManualError(
            "manual render manifest must identify exactly USER-MANUAL.pdf and USER-MANUAL.docx"
        )

    records: list[dict[str, Any]] = []
    for filename in DOCUMENT_FILENAMES:
        actual = _file_record(manual_dir / filename)
        item = by_filename[filename]
        if item.get("sha256") != actual["sha256"] or item.get("size_bytes") != actual["size_bytes"]:
            raise CandidateManualError(
                f"manual render manifest hash/size does not match {filename}"
            )
        records.append(actual)
    return manifest, records


def _candidate_version() -> str:
    try:
        from civiccast._native_version import __version__
    except (ImportError, SyntaxError) as exc:
        raise CandidateManualError(f"cannot read candidate version: {exc}") from exc
    if not __version__:
        raise CandidateManualError("candidate version is empty")
    return __version__


def create_candidate_manual_receipt(
    *,
    manual_dir: Path,
    source_sha: str,
    workflow_run_id: str,
    repo_root: Path = REPO_ROOT,
) -> Path:
    """Write a receipt only after the rendered files and manifest agree."""
    if not _SOURCE_SHA_RE.fullmatch(source_sha):
        raise CandidateManualError("source_sha must be a lowercase, full 40-character Git SHA")
    if not workflow_run_id.isdecimal() or int(workflow_run_id) <= 0:
        raise CandidateManualError("workflow_run_id must be a positive decimal run ID")
    if not manual_dir.is_dir():
        raise CandidateManualError(f"manual directory does not exist: {manual_dir}")

    manifest, files = _manifest_records(manual_dir=manual_dir, repo_root=repo_root)
    receipt = {
        "schema_version": 1,
        "source_sha": source_sha,
        "candidate_version": _candidate_version(),
        "workflow_run_id": workflow_run_id,
        "manual_source_sha256": manifest["source_sha256"],
        "render_manifest_sha256": sha256_file(manual_dir / MANIFEST_FILENAME),
        "files": files,
    }
    path = manual_dir / RECEIPT_FILENAME
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def verify_candidate_manual(
    *,
    manual_dir: Path,
    source_sha: str,
    candidate_version: str,
    workflow_run_id: str,
    repo_root: Path = REPO_ROOT,
) -> list[Path]:
    """Verify exact candidate provenance, source, manifest, and PDF/DOCX bytes."""
    if not _SOURCE_SHA_RE.fullmatch(source_sha):
        raise CandidateManualError("source_sha must be a lowercase, full 40-character Git SHA")
    if not workflow_run_id.isdecimal() or int(workflow_run_id) <= 0:
        raise CandidateManualError("workflow_run_id must be a positive decimal run ID")
    if not manual_dir.is_dir():
        raise CandidateManualError(f"manual directory does not exist: {manual_dir}")

    manifest, files = _manifest_records(manual_dir=manual_dir, repo_root=repo_root)
    manifest_path = manual_dir / MANIFEST_FILENAME
    receipt = _read_json(manual_dir / RECEIPT_FILENAME, label="candidate manual receipt")
    expected = {
        "schema_version": 1,
        "source_sha": source_sha,
        "candidate_version": candidate_version,
        "workflow_run_id": workflow_run_id,
        "manual_source_sha256": manifest["source_sha256"],
        "render_manifest_sha256": sha256_file(manifest_path),
        "files": files,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise CandidateManualError(
                f"candidate manual receipt {key} does not match the exact build/manual files"
            )

    return [manual_dir / filename for filename in PACKAGE_FILENAMES]


def manual_required_for_version(version: str) -> bool:
    """Beta 11 starts the manual asset contract; later versions keep it."""
    match = re.fullmatch(r"1\.0\.0-beta\.(\d+)", version)
    return match is None or int(match.group(1)) >= 11


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="write an exact-candidate receipt")
    create.add_argument("--manual-dir", required=True, type=Path)
    create.add_argument("--source-sha", required=True)
    create.add_argument("--workflow-run-id", required=True)
    create.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    verify = subparsers.add_parser("verify", help="verify an exact-candidate manual bundle")
    verify.add_argument("--manual-dir", required=True, type=Path)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--candidate-version", required=True)
    verify.add_argument("--workflow-run-id", required=True)
    verify.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            receipt = create_candidate_manual_receipt(
                manual_dir=args.manual_dir,
                source_sha=args.source_sha,
                workflow_run_id=args.workflow_run_id,
                repo_root=args.repo_root,
            )
            print(f"candidate_manual: created receipt {receipt}")
        else:
            files = verify_candidate_manual(
                manual_dir=args.manual_dir,
                source_sha=args.source_sha,
                candidate_version=args.candidate_version,
                workflow_run_id=args.workflow_run_id,
                repo_root=args.repo_root,
            )
            print(f"candidate_manual: verified exact candidate manual ({len(files)} files)")
    except (CandidateManualError, OSError) as exc:
        print(f"candidate_manual: FAIL - {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

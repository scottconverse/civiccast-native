#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Render and verify the CivicCast user manual release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "USER-MANUAL.md"
DEFAULTS = ROOT / "docs" / "assets" / "manual.pandoc.yaml"
DEFAULT_OUT = ROOT / "docs"
MANIFEST_NAME = "USER-MANUAL.render.json"
REQUIRED = (
    "CivicCast User Manual",
    "Admin Guide",
    "Meeting Operator Guide",
    "Records Clerk Guide",
    "Technical Operations Reference",
)

# Matches both a bare version ("v1.0.0-rc18") and one embedded in prose.
_VERSION_TOKEN_RE = re.compile(r"v\d+\.\d+\.\d+(?:-rc\d+)?")


def _source_version_token(text: str) -> str:
    """The single source of truth for the manual's version: the YAML
    frontmatter `subtitle` field in docs/USER-MANUAL.md. TW-A: the rendered
    PDF's running header used to be a hard-coded string in
    docs/assets/manual-style.tex that drifted from this value silently
    (title page rc18, every running header still rc17). Deriving both the
    title page and the running header from this one token is what makes
    that drift structurally impossible now."""
    match = re.search(r"^subtitle:.*$", text, re.M)
    if not match:
        raise RuntimeError(f"{SOURCE} has no `subtitle:` frontmatter field")
    token = _VERSION_TOKEN_RE.search(match.group(0))
    if not token:
        raise RuntimeError(f"{SOURCE}'s subtitle does not contain a vX.Y.Z(-rcN) version token")
    return token.group(0)


def _rendered_header_version_token(pdf_path: Path) -> str:
    """Extract the version token from the rendered PDF's running header.

    The title page (page 1) intentionally carries the full subtitle; the
    running header appears starting on page 2 (\\fancyhead[R]) driven by the
    \\ccmanualversion macro in docs/assets/manual-style.tex. Page 2 is the
    stable page to check: page 1 is the title page and has no running header.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    if len(reader.pages) < 2:
        raise RuntimeError(f"{pdf_path} has fewer than 2 pages; cannot check the running header")
    header_text = reader.pages[1].extract_text() or ""
    token = _VERSION_TOKEN_RE.search(header_text)
    if not token:
        raise RuntimeError(f"Could not find a version token in {pdf_path}'s page-2 running header")
    return token.group(0)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_sha256(path: Path) -> str:
    """Hash canonical text so Windows and Linux checkouts agree."""
    normalized = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def render_manual(out_dir: Path) -> tuple[Path, Path]:
    if not SOURCE.exists():
        raise FileNotFoundError(f"{SOURCE} not found")
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required to render USER-MANUAL artifacts")
    if shutil.which("xelatex") is None:
        raise RuntimeError("xelatex is required to render USER-MANUAL.pdf")

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / "USER-MANUAL.pdf"
    docx = out_dir / "USER-MANUAL.docx"
    plain = out_dir / ".USER-MANUAL.render-check.txt"

    resource_path = str(ROOT / "docs")
    version_token = _source_version_token(SOURCE.read_text(encoding="utf-8"))
    # Layout/fonts/colours come from the shared defaults file so this renderer
    # and scripts/render-user-manual.sh cannot drift apart. _run() already
    # executes with cwd=ROOT, which is what the relative paths inside it need.
    # The version header is written outside the repo tree and passed as an
    # extra --include-in-header on top of the defaults file: pandoc appends
    # command-line -H files after the ones from --defaults, so this
    # \renewcommand runs after manual-style.tex's \providecommand default
    # and the running header always matches SOURCE's subtitle (TW-A).
    with tempfile.TemporaryDirectory() as tmp_dir:
        version_header = Path(tmp_dir) / "manual-version.tex"
        version_header.write_text(
            f"\\renewcommand{{\\ccmanualversion}}{{{version_token}}}\n", encoding="utf-8"
        )
        _run(
            [
                "pandoc",
                str(SOURCE),
                "--defaults",
                str(DEFAULTS),
                "-H",
                str(version_header),
                "-o",
                str(pdf),
            ]
        )
    # DOCX has no LaTeX preamble; render it with the table of contents only.
    _run(
        [
            "pandoc",
            str(SOURCE),
            "--resource-path",
            resource_path,
            "--toc",
            "--toc-depth=2",
            "-o",
            str(docx),
        ]
    )
    _run(["pandoc", str(SOURCE), "-t", "plain", "-o", str(plain)])

    text = plain.read_text(encoding="utf-8")
    plain.unlink(missing_ok=True)
    missing = [fragment for fragment in REQUIRED if fragment not in text]
    if missing:
        raise RuntimeError(f"Rendered manual is missing required fragments: {missing}")
    if pdf.stat().st_size <= 0 or docx.stat().st_size <= 0:
        raise RuntimeError("Rendered manual artifact is empty")
    manifest = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": _source_sha256(SOURCE),
        "artifacts": [
            {
                "path": pdf.resolve().relative_to(ROOT).as_posix(),
                "sha256": _sha256(pdf),
                "size_bytes": pdf.stat().st_size,
            },
            {
                "path": docx.resolve().relative_to(ROOT).as_posix(),
                "sha256": _sha256(docx),
                "size_bytes": docx.stat().st_size,
            },
        ],
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return pdf, docx


def check_manual(out_dir: Path) -> None:
    pdf = out_dir / "USER-MANUAL.pdf"
    docx = out_dir / "USER-MANUAL.docx"
    manifest = out_dir / MANIFEST_NAME
    missing = [
        str(path) for path in (pdf, docx, manifest) if not path.exists() or path.stat().st_size <= 0
    ]
    if missing:
        raise RuntimeError(f"Missing rendered manual artifact(s): {', '.join(missing)}")


def check_current(out_dir: Path) -> None:
    check_manual(out_dir)
    manifest = json.loads((out_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("source_sha256") != _source_sha256(SOURCE):
        raise RuntimeError("Rendered manual manifest source hash is stale")
    for item in manifest.get("artifacts", []):
        path = ROOT / item["path"]
        if not path.exists():
            raise RuntimeError(f"Rendered manual artifact is missing: {path}")
        if item.get("sha256") != _sha256(path):
            raise RuntimeError(f"Rendered manual artifact hash is stale: {path}")

    # TW-A: the source/artifact hashes above prove the PDF bytes match what
    # was last rendered from this exact source text, but they cannot catch a
    # rendered PDF whose title page and running header disagree with each
    # other and with the source -- that requires actually reading the
    # version tokens back out and comparing them.
    source_token = _source_version_token(SOURCE.read_text(encoding="utf-8"))
    pdf_path = out_dir / "USER-MANUAL.pdf"
    header_token = _rendered_header_version_token(pdf_path)
    if header_token != source_token:
        raise RuntimeError(
            f"{pdf_path}'s running header shows {header_token!r} but "
            f"{SOURCE}'s subtitle names {source_token!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="only verify artifacts exist")
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="render to a temporary directory and verify tracked artifacts match",
    )
    args = parser.parse_args()

    try:
        if args.check_current:
            check_current(args.out_dir)
            print("render_user_manual: PASS - tracked PDF and DOCX artifacts are current.")
        elif args.check:
            check_manual(args.out_dir)
            print("render_user_manual: PASS - PDF and DOCX artifacts exist.")
        else:
            pdf, docx = render_manual(args.out_dir)
            print(f"Rendered {pdf.resolve().relative_to(ROOT)}")
            print(f"Rendered {docx.resolve().relative_to(ROOT)}")
    except Exception as exc:
        print(f"render_user_manual: FAIL - {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

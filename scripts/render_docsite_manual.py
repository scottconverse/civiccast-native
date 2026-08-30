#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Render the in-product operator manual artifact from docs/USER-MANUAL.md.

Mirrors scripts/render_user_manual.py's contract exactly (same source file,
same newline-normalized SHA-256 hashing, same --check-current drift gate) so
the in-product manual (civiccast/docsite/manual.json) cannot silently drift
from the PDF/DOCX or from docs/USER-MANUAL.md itself. See docs/docsite-sync.md
for the full staleness-proof explanation.

Unlike the PDF/DOCX renderer, this script's only markdown engine is also
pandoc (kept identical on purpose -- one rendering engine, one set of
markdown-syntax quirks to reason about) but the *output* is a single
sanitized HTML fragment plus an id/level/title table of contents, written as
civiccast/docsite/manual.json -- inside the civiccast/ package tree so the
existing `packages = ["civiccast"]` wheel rule picks it up with no packaging
script changes, the same way civiccast/records/fixtures/*.ttf already does
(see pyproject.toml's [tool.hatch.build.targets.wheel.force-include], which
this file's own manifest entry joins).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "USER-MANUAL.md"
OUT_DIR = ROOT / "civiccast" / "docsite"
MANUAL_JSON = OUT_DIR / "manual.json"
MANIFEST_NAME = "manual.render.json"

sys.path.insert(0, str(ROOT))
from civiccast.docsite.render import embed_local_images, extract_toc, sanitize_html  # noqa: E402


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_sha256(path: Path) -> str:
    """Hash canonical text so Windows and Linux checkouts agree.

    Identical normalization to scripts/render_user_manual.py's
    ``_source_sha256`` -- deliberately not imported from there, so this
    script has no import-order coupling to the PDF/DOCX renderer and can be
    run completely independently.
    """

    normalized = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def render_docsite_manual() -> Path:
    if not SOURCE.exists():
        raise FileNotFoundError(f"{SOURCE} not found")
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required to render the docsite manual artifact")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_html = subprocess.run(
        ["pandoc", str(SOURCE), "-t", "html5", "--wrap=none"],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

    # Embed local images (e.g. the two architecture diagrams) as data: URIs
    # BEFORE sanitizing: sanitize_html's allowlist only ever accepts an
    # already-absolute/data/http(s) src, by design (relative paths don't
    # resolve to anything once this HTML is served from manual.json with no
    # filesystem underneath it) -- see embed_local_images's own docstring.
    raw_html = embed_local_images(raw_html, base_dir=ROOT / "docs")
    html = sanitize_html(raw_html)
    if not html.strip():
        raise RuntimeError("Rendered docsite manual HTML is empty")
    toc = extract_toc(html)
    if not toc:
        raise RuntimeError("Rendered docsite manual has no headings with ids")

    document = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": _source_sha256(SOURCE),
        "generated_at": datetime.now(UTC).isoformat(),
        "toc": toc,
        "html": html,
    }
    # write_bytes (not write_text) deliberately: write_text's universal-newline
    # translation turns every "\n" into "\r\n" on Windows, which would make
    # the file on disk differ from the `payload` string this function hashes
    # for the manifest -- check_current() would then fail on a station that
    # never touched the file at all.
    payload = json.dumps(document, indent=2, sort_keys=False) + "\n"
    payload_bytes = payload.encode("utf-8")
    MANUAL_JSON.write_bytes(payload_bytes)

    manifest = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": document["source_sha256"],
        "artifact": {
            "path": MANUAL_JSON.relative_to(ROOT).as_posix(),
            "sha256": _sha256_bytes(payload_bytes),
        },
    }
    (OUT_DIR / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return MANUAL_JSON


def check_current() -> None:
    manifest_path = OUT_DIR / MANIFEST_NAME
    if not manifest_path.exists() or not MANUAL_JSON.exists():
        raise RuntimeError(
            f"Missing docsite manual artifact(s): {MANUAL_JSON}, {manifest_path}. "
            "Run: uv run python scripts/render_docsite_manual.py"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_sha256") != _source_sha256(SOURCE):
        raise RuntimeError(
            "civiccast/docsite/manual.render.json's source hash is stale against "
            "docs/USER-MANUAL.md. Run: uv run python scripts/render_docsite_manual.py"
        )
    on_disk_sha = _sha256_bytes(MANUAL_JSON.read_bytes())
    if manifest.get("artifact", {}).get("sha256") != on_disk_sha:
        raise RuntimeError(
            "civiccast/docsite/manual.json does not match its own recorded hash -- it "
            "was hand-edited or only partially regenerated. Run: "
            "uv run python scripts/render_docsite_manual.py"
        )
    # Deliberately NOT re-rendering pandoc here and byte-comparing the HTML
    # (an earlier version of this check did): pandoc's HTML output can
    # legitimately differ by patch version (attribute ordering, slug edge
    # cases), and ci-docs.yml's `apt-get install pandoc` pins no version --
    # a CI runner's pandoc need not match a contributor's local one byte for
    # byte. The two hash checks above are the same drift guarantee
    # scripts/render_user_manual.py's own check_current() relies on for the
    # PDF/DOCX artifacts (hash the tracked file, hash the source, done); a
    # genuine pandoc-driven content change is still caught the moment
    # someone runs the render script again and the resulting artifact no
    # longer matches what a reviewer expects to see in the diff.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="verify the tracked artifact is current with docs/USER-MANUAL.md",
    )
    args = parser.parse_args()

    try:
        if args.check_current:
            check_current()
            print("render_docsite_manual: PASS - civiccast/docsite/manual.json is current.")
        else:
            out = render_docsite_manual()
            print(f"Rendered {out.resolve().relative_to(ROOT)}")
    except Exception as exc:
        print(f"render_docsite_manual: FAIL - {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

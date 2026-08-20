#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Render docs/assets/architecture/*.svg to matching PNGs.

The SVGs are the editable source; the PNGs exist because the LaTeX/xelatex
manual pipeline cannot embed SVG. Keeping this script in the repo means the
PNG can always be regenerated from the SVG instead of drifting away from it
(a stale hardcoded version string baked into the PNG is exactly how the rc15
label survived into the rc17 manual).

Usage:
    python scripts/render_architecture_diagrams.py           # regenerate
    python scripts/render_architecture_diagrams.py --check   # verify current
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "docs" / "assets" / "architecture"

_SIZE_RE = re.compile(r'<svg[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"', re.IGNORECASE)


def _intrinsic_size(svg: Path) -> tuple[int, int]:
    m = _SIZE_RE.search(svg.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError(f"{svg.name}: could not read width/height from the <svg> tag")
    return int(m.group(1)), int(m.group(2))


def render(check: bool = False) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "render_architecture_diagrams: FAIL - playwright is required "
            "(pip install playwright && playwright install chromium)",
            file=sys.stderr,
        )
        return 1

    svgs = sorted(ART.glob("*.svg"))
    if not svgs:
        print(f"render_architecture_diagrams: FAIL - no SVGs in {ART}", file=sys.stderr)
        return 1

    stale: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for svg in svgs:
                width, height = _intrinsic_size(svg)
                png = svg.with_suffix(".png")
                page = browser.new_page(viewport={"width": width, "height": height})
                # device_scale_factor=1 keeps the PNG at the SVG's intrinsic
                # size so the manual's \includegraphics sizing does not shift.
                page.goto(svg.resolve().as_uri())
                shot = page.screenshot(omit_background=False)
                page.close()

                if check:
                    if not png.exists() or png.read_bytes() != shot:
                        stale.append(png.name)
                else:
                    png.write_bytes(shot)
                    print(f"Rendered {png.relative_to(ROOT).as_posix()} ({width}x{height})")
        finally:
            browser.close()

    if check:
        if stale:
            print(
                "render_architecture_diagrams: FAIL - PNG(s) do not match their SVG: "
                + ", ".join(stale),
                file=sys.stderr,
            )
            return 1
        print("render_architecture_diagrams: PASS - PNGs match their SVG sources.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify PNGs match their SVGs")
    args = parser.parse_args()
    return render(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

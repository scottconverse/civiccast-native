"""Take full-resolution screenshots of a running CivicCast station for the manual (documentation tool).

  python shoot.py <out-dir> <base-url> <shots.json> [--token-env NAME]

shots.json is a list of objects: {"name": "public-home", "path": "/#/", "wait_ms": 3000, "full_page": false,
"width": 1440, "height": 900, "clicks": ["text=Recordings"], "dark": false}.
Uses the installed Google Chrome through Playwright (no browser download). A staff token, when needed, is read
from the environment variable named by --token-env and placed in sessionStorage before the page loads; it is never printed.
"""

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

out_dir = Path(sys.argv[1])
base = sys.argv[2].rstrip("/")
shots = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
token = None
if "--token-env" in sys.argv:
    token = os.environ.get(sys.argv[sys.argv.index("--token-env") + 1])
out_dir.mkdir(parents=True, exist_ok=True)

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=True)
    for shot in shots:
        ctx = browser.new_context(
            viewport={"width": shot.get("width", 1440), "height": shot.get("height", 900)},
            device_scale_factor=2,
            color_scheme="dark" if shot.get("dark") else "light",
        )
        if token and shot.get("auth", True):
            ctx.add_init_script(
                f"sessionStorage.setItem('civiccast.staffToken', {json.dumps(token)});"
            )
        page = ctx.new_page()
        page.goto(base + shot["path"], wait_until="domcontentloaded")
        page.wait_for_timeout(shot.get("wait_ms", 3000))
        for sel in shot.get("clicks", []):
            page.click(sel)
            page.wait_for_timeout(shot.get("click_wait_ms", 1200))
        target = out_dir / f"{shot['name']}.png"
        page.screenshot(path=str(target), full_page=shot.get("full_page", False))
        print("saved", target.name, target.stat().st_size)
        ctx.close()
    browser.close()

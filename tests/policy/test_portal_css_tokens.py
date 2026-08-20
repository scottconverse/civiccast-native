# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_ROOT = REPO_ROOT / "civiccast" / "apps"
SHARED_TOKENS = APPS_ROOT / "portal-operator" / "src" / "civiccast-tokens.css"
UI_SOURCE_ROOTS = [
    APPS_ROOT / "portal-operator" / "src",
    APPS_ROOT / "portal-public" / "src",
    APPS_ROOT / "installer" / "src",
]
TOKEN_DEF_RE = re.compile(r"(?<![\w-])(--cc-[A-Za-z0-9-]+)\s*:")
TOKEN_USE_RE = re.compile(r"var\(\s*(--cc-[A-Za-z0-9-]+)(\s*,[^)]*)?\)")


def test_ui_surfaces_do_not_use_undefined_css_tokens() -> None:
    """Keep confirmation surfaces from rendering with dropped colors."""

    defined = set(TOKEN_DEF_RE.findall(SHARED_TOKENS.read_text(encoding="utf-8")))
    for root in UI_SOURCE_ROOTS:
        for css_file in root.rglob("*.css"):
            defined.update(TOKEN_DEF_RE.findall(css_file.read_text(encoding="utf-8")))

    undefined: list[str] = []
    for root in UI_SOURCE_ROOTS:
        for source in sorted(root.rglob("*")):
            if source.suffix not in {".css", ".tsx", ".ts"}:
                continue
            text = source.read_text(encoding="utf-8")
            for token, fallback in TOKEN_USE_RE.findall(text):
                if token not in defined and not fallback:
                    undefined.append(f"{source.relative_to(REPO_ROOT)} uses {token}")

    assert undefined == []


def test_ui_surfaces_share_civiccast_design_tokens() -> None:
    """Stop installer, console, portal, and docs CSS from drifting apart."""

    expected_imports = {
        APPS_ROOT / "portal-operator" / "src" / "index.css": "./civiccast-tokens.css",
        APPS_ROOT / "portal-public" / "src" / "index.css": (
            "../../portal-operator/src/civiccast-tokens.css"
        ),
        APPS_ROOT / "installer" / "src" / "styles.css": (
            "../../portal-operator/src/civiccast-tokens.css"
        ),
    }
    missing = []
    for path, expected in expected_imports.items():
        if expected not in path.read_text(encoding="utf-8"):
            missing.append(str(path.relative_to(REPO_ROOT)))
    docs_index = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert missing == []
    assert "--cc-paper" in docs_index
    assert "--cc-brand" in docs_index

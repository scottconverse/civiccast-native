# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: the three readiness labels must read identically everywhere.

The operator console rendered the amber state as "Check first" while
civiccast/installer/service.py and the operator vocabulary guide called it
"Check before meeting". An operator reading the docs looked for a phrase the
screen never showed. Nothing caught it because each surface was internally
consistent -- only the comparison between them was wrong.

This guard pins the vocabulary in one place and fails if any surface drifts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# docs/operator-language-guide.md is the authoritative vocabulary document.
CANONICAL = {
    "green": "Ready",
    "yellow": "Check before meeting",
    "red": "Do not broadcast yet",
}

# Surfaces that render or emit the labels to an operator.
UI_SCREENS = (
    "civiccast/apps/portal-operator/src/screens/SystemHealthScreen.tsx",
    "civiccast/apps/portal-operator/src/screens/LiveRoomScreen.tsx",
)
BACKEND = "civiccast/installer/service.py"
VOCABULARY_DOC = "docs/operator-language-guide.md"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("rel", UI_SCREENS)
def test_console_uses_the_canonical_amber_label(rel: str) -> None:
    text = _read(rel)
    assert CANONICAL["yellow"] in text, (
        f"{rel} does not render the canonical amber readiness label "
        f"{CANONICAL['yellow']!r}. Keep the console, "
        f"{BACKEND}, and {VOCABULARY_DOC} in step."
    )


@pytest.mark.parametrize("rel", UI_SCREENS)
def test_console_does_not_reintroduce_the_drifted_label(rel: str) -> None:
    # "Check first" is the exact string that drifted. Match it as a quoted
    # label so ordinary prose containing those words cannot trip the guard.
    text = _read(rel)
    drifted = re.findall(r"""label:\s*['"]Check first['"]""", text)
    assert not drifted, (
        f"{rel} reintroduced the 'Check first' label. The operator vocabulary "
        f"({VOCABULARY_DOC}) and the installer both say "
        f"{CANONICAL['yellow']!r}."
    )


def test_installer_backend_matches_the_vocabulary() -> None:
    text = _read(BACKEND)
    assert CANONICAL["yellow"] in text, (
        f"{BACKEND} no longer emits {CANONICAL['yellow']!r}; the console and "
        f"{VOCABULARY_DOC} still do."
    )


@pytest.mark.parametrize("label", sorted(CANONICAL.values()))
def test_vocabulary_doc_defines_every_readiness_label(label: str) -> None:
    text = _read(VOCABULARY_DOC)
    assert label in text, (
        f"{VOCABULARY_DOC} is the authoritative operator vocabulary but does "
        f"not define the readiness label {label!r} that the product shows."
    )

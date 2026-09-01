# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from scripts.policy.check_v17_adoption_gate import (
    HISTORICAL_DOCS,
    REQUIRED_DOCS,
    evaluate_v17_adoption_gate,
)


def _write_required_docs(root: Path) -> None:
    for relative, phrases in REQUIRED_DOCS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(phrases) + "\n", encoding="utf-8")
    for relative in HISTORICAL_DOCS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "Historical retired WSL2 guidance, not civiccast-native guidance.\n",
            encoding="utf-8",
        )


def test_v17_adoption_gate_passes_current_repo() -> None:
    root = Path(__file__).resolve().parents[2]

    assert evaluate_v17_adoption_gate(root) == []


def test_native_adoption_gate_requires_support_doc(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    (tmp_path / "SUPPORT.md").unlink()

    violations = evaluate_v17_adoption_gate(tmp_path)

    assert any("SUPPORT.md" in violation for violation in violations)


def test_native_adoption_gate_rejects_overclaims(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    landing = tmp_path / "docs" / "index.html"
    landing.write_text(
        landing.read_text(encoding="utf-8") + "\nRoku Channel Store certified for this release.\n",
        encoding="utf-8",
    )

    violations = evaluate_v17_adoption_gate(tmp_path)

    assert any("overclaim pattern" in violation for violation in violations)

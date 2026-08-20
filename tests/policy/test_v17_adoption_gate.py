# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from scripts.policy.check_v17_adoption_gate import (
    REQUIRED_DOCS,
    evaluate_v17_adoption_gate,
)


def _write_required_docs(root: Path) -> None:
    for relative, phrases in REQUIRED_DOCS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(phrases) + "\n", encoding="utf-8")
    quickstart = root / "docs" / "adoption" / "early-adopter-quickstart.md"
    quickstart.write_text(
        quickstart.read_text(encoding="utf-8") + "unpublished repair candidate\n",
        encoding="utf-8",
    )
    index = root / "docs" / "index.html"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "\n".join(relative.as_posix().removeprefix("docs/") for relative in REQUIRED_DOCS),
        encoding="utf-8",
    )


def test_v17_adoption_gate_passes_current_repo() -> None:
    root = Path(__file__).resolve().parents[2]

    assert evaluate_v17_adoption_gate(root) == []


def test_v17_adoption_gate_requires_support_doc(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    (tmp_path / "docs" / "adoption" / "support-intake.md").unlink()

    violations = evaluate_v17_adoption_gate(tmp_path)

    assert any("support-intake.md" in violation for violation in violations)


def test_v17_adoption_gate_rejects_overclaims(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    proof = tmp_path / "docs" / "releases" / "v1.7-proof-bundle.md"
    proof.write_text(
        proof.read_text(encoding="utf-8") + "\nRoku Channel Store certified for this release.\n",
        encoding="utf-8",
    )

    violations = evaluate_v17_adoption_gate(tmp_path)

    assert any("overclaim pattern" in violation for violation in violations)

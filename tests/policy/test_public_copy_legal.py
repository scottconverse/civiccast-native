# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from scripts.policy.check_public_copy_legal import evaluate_public_copy_legal


def test_public_copy_legal_blocks_high_risk_replacement_framing(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("CivicCast is a Cablecast replacement.\n", encoding="utf-8")

    violations = evaluate_public_copy_legal(tmp_path)

    assert len(violations) == 2
    assert violations[0].path == "README.md"
    assert violations[0].line == 1
    assert violations[0].phrase == "Cablecast"
    assert violations[1].phrase == "Cablecast replacement"


def test_public_copy_legal_blocks_non_allowlisted_spec_sections(tmp_path: Path) -> None:
    section = tmp_path / "docs" / "spec" / "3.0" / "sections"
    section.mkdir(parents=True)
    (section / "S1-reference-station-and-stationboxprofile.md").write_text(
        "# Section\n\nCablecast appears in ordinary section prose.\n",
        encoding="utf-8",
    )

    violations = evaluate_public_copy_legal(tmp_path)

    assert len(violations) == 1
    assert (
        violations[0].path == "docs/spec/3.0/sections/S1-reference-station-and-stationboxprofile.md"
    )
    assert violations[0].phrase == "Cablecast"


def test_public_copy_legal_allows_s18_research_appendix(tmp_path: Path) -> None:
    appendix = tmp_path / "docs" / "spec" / "3.0" / "sections"
    appendix.mkdir(parents=True)
    (appendix / "S18-cablecast-parity-gap-closure.md").write_text(
        "# Comparative research appendix\n\nCablecast parity appears here as historical research.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "CivicCast is open-source PEG broadcast software.\n", encoding="utf-8"
    )

    violations = evaluate_public_copy_legal(tmp_path)

    assert violations == []


def test_public_copy_legal_allows_legal_notices(tmp_path: Path) -> None:
    (tmp_path / "LEGAL-NOTICES.md").write_text(
        "Cablecast and Tightrope names are referenced for legal notice only.\n",
        encoding="utf-8",
    )

    violations = evaluate_public_copy_legal(tmp_path)

    assert violations == []


def test_public_copy_legal_allows_patent_watchlist(tmp_path: Path) -> None:
    legal = tmp_path / "docs" / "legal"
    legal.mkdir(parents=True)
    (legal / "patent-watchlist.md").write_text(
        "Cablecast and Tightrope references remain in a patent-risk watchlist.\n",
        encoding="utf-8",
    )

    violations = evaluate_public_copy_legal(tmp_path)

    assert violations == []


def test_public_copy_legal_blocks_code_comments(tmp_path: Path) -> None:
    package = tmp_path / "civiccast"
    package.mkdir()
    (package / "app.py").write_text("# Cablecast Autopilot parity.\n", encoding="utf-8")

    violations = evaluate_public_copy_legal(tmp_path)

    assert len(violations) == 1
    assert violations[0].path == "civiccast/app.py"
    assert violations[0].phrase == "Cablecast"


def test_allows_factual_vendor_names_in_the_migrate_feature(tmp_path: Path) -> None:
    """civiccast/migrate/ and tests/migrate/ import FROM the incumbents; naming
    them there is factual interop, not positioning -- allowed by prefix."""
    for relative in (
        "civiccast/migrate/adapters.py",
        "tests/migrate/test_service.py",
        "docs/research/competitive-landscape-2026-06.md",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            'source_system = "cablecast"  # import from Cablecast\n', encoding="utf-8"
        )

    assert evaluate_public_copy_legal(tmp_path) == []


def test_high_risk_framing_is_still_blocked_on_a_public_surface(tmp_path: Path) -> None:
    """The allowlist expansion must NOT weaken the real protection: a
    "replaces/beats Cablecast" claim on a non-allowlisted public page still fails."""
    (tmp_path / "README.md").write_text(
        "CivicCast replaces Cablecast and beats Cablecast on every axis.\n", encoding="utf-8"
    )

    violations = evaluate_public_copy_legal(tmp_path)

    assert violations, "high-risk replacement framing on the README must still be flagged"
    assert any("replaces Cablecast" in v.phrase or v.phrase == "Cablecast" for v in violations)


def test_a_plain_vendor_mention_outside_the_allowlist_still_fails(tmp_path: Path) -> None:
    (tmp_path / "docs" / "marketing").mkdir(parents=True)
    (tmp_path / "docs" / "marketing" / "pitch.md").write_text(
        "We integrate with Cablecast systems.\n", encoding="utf-8"
    )

    assert evaluate_public_copy_legal(tmp_path) != []


def test_run_all_invokes_public_copy_legal_guard() -> None:
    from scripts.policy import run_all

    assert any(name == "check_public_copy_legal" for name, _args in run_all.CHECKS)

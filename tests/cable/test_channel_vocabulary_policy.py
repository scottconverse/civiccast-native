# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Channel-vocabulary policy (owner directive, rc5).

The product must speak only the generic PEG channel *types* — public,
education, government — never specific numbered channels (numbers vary city to
city). The First-Setup seed channels must equal the real playout/egress
lineup so schedule -> commit-to-air can never be severed by a divergent
vocabulary again (gauntlet F-RC4-2 root cause).
"""

from __future__ import annotations

import re
from pathlib import Path

from civiccast.cable.channel import default_channel_profiles
from civiccast.installer.station_state import _DEFAULT_CHANNEL_PROFILES

REPO_ROOT = Path(__file__).resolve().parents[2]

PEG_CHANNEL_IDS = {"public", "education", "government"}

# Numbered channel ids/labels that must never appear in live source or active
# docs. Historical snapshots (changelogs, archived audits, pre-reset releases,
# rendered gauntlet HTML) are allowlisted — they record what WAS true.
_FORBIDDEN = ("gov-ch12", "edu-ch13", "community-ch14", "edu-ch14")
_ALLOWLIST_DIRS = (
    "CHANGELOG.md",
    "docs/audits/",
    "docs/releases/archive/",
    "docs/releases/gauntletgate/",
    "docs/releases/evidence/",
    "docs/releases/spec-alignment-ledger",
    "docs/spec/release-plan",
)


def test_real_channel_lineup_is_the_three_peg_types() -> None:
    ids = {p.channel_id for p in default_channel_profiles()}
    assert ids == PEG_CHANNEL_IDS


def test_station_seed_channels_equal_the_real_lineup() -> None:
    """Seed == real playout channels — the F-RC4-2 root cause was a divergent
    numbered seed. This pins them together forever."""
    seed_ids = {p.channel_id for p in _DEFAULT_CHANNEL_PROFILES}
    real_ids = {p.channel_id for p in default_channel_profiles()}
    assert seed_ids == real_ids == PEG_CHANNEL_IDS


def test_no_numbered_channel_ids_in_live_source_or_active_docs() -> None:
    offenders: list[str] = []
    # Every root-level .md is scanned: CAPABILITIES.md carried a stale
    # "Hardcoded gov-ch12 across multiple screens" row that a README-only scan
    # could never see (caught by independent verification of the rc5 fixes).
    scan_globs = (
        list((REPO_ROOT / "civiccast").rglob("*.py"))
        + list((REPO_ROOT / "civiccast").rglob("*.ts"))
        + list((REPO_ROOT / "civiccast").rglob("*.tsx"))
        + list((REPO_ROOT / "docs").rglob("*.md"))
        + list((REPO_ROOT / "docs").rglob("*.html"))
        + sorted(REPO_ROOT.glob("*.md"))
    )
    for path in scan_globs:
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(allow in rel for allow in _ALLOWLIST_DIRS):
            continue
        # Test fixtures may use numbered ids as arbitrary opaque handles
        # unrelated to the PEG vocabulary (category (e) in the trace): unit
        # tests (*.test.*) and Playwright e2e specs (*.spec.* under /e2e/).
        if (
            "/tests/" in f"/{rel}"
            or rel.startswith("tests/")
            or ".test." in rel
            or ".spec." in rel
            or "/e2e/" in f"/{rel}"
        ):
            continue
        if "__pycache__" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in _FORBIDDEN:
            if re.search(rf"\b{re.escape(token)}\b", text):
                offenders.append(f"{rel}: {token}")
    assert not offenders, "numbered channel ids found in live source/active docs:\n" + "\n".join(
        offenders
    )


def test_capabilities_row_matches_which_screens_actually_load_channels() -> None:
    """CAPABILITIES.md's "Operator channel selection" row is a claim about code.
    It has now drifted three times: once naming a retired numbered id, once
    asserting Live Room had no channel picker when it has had one since
    b10de82b, and once (WP-09) asserting Facility Router still hard-coded a
    single default channel after it was wired to the real channel list. Pin
    the claim to the source so wiring a screen (or unwiring one) fails here
    and forces the row to be rewritten."""
    screens = REPO_ROOT / "civiccast/apps/portal-operator/src"
    loads_channels = {
        "components/schedule/ScheduleDrawer.tsx",
        "screens/LiveRoomScreen.tsx",
        "screens/ChannelOpsScreen.tsx",
        "screens/FacilityRouterScreen.tsx",
    }

    for rel in sorted(loads_channels):
        text = (screens / rel).read_text(encoding="utf-8")
        assert "listChannelProfiles" in text, (
            f"{rel} no longer loads the real channel list — update the "
            "'Operator channel selection' row in CAPABILITIES.md"
        )
        assert not re.search(r"const CHANNEL_ID\s*=", text), (
            f"{rel} reintroduced a hard-coded default channel constant — "
            "re-check the 'Operator channel selection' row in CAPABILITIES.md"
        )


def test_a_station_provisioned_with_a_retired_channel_id_is_healed_on_load() -> None:
    """Independent-verification finding: an already-provisioned station persisted
    a numbered default_channel_id. The old fallback only fired when the key was
    ABSENT, so a present-but-retired value stayed stuck forever. Normalize any
    value that is not one of the station's real channels."""
    from civiccast.installer.station_state import _normalized_default_channel_id

    # A retired numbered id heals to a real channel.
    assert _normalized_default_channel_id("gov-ch12") in PEG_CHANNEL_IDS
    assert _normalized_default_channel_id("edu-ch13") in PEG_CHANNEL_IDS
    # Absent / empty heals too (the old behavior, preserved).
    assert _normalized_default_channel_id(None) in PEG_CHANNEL_IDS
    assert _normalized_default_channel_id("") in PEG_CHANNEL_IDS
    # A real channel is preserved exactly.
    for real in sorted(PEG_CHANNEL_IDS):
        assert _normalized_default_channel_id(real) == real

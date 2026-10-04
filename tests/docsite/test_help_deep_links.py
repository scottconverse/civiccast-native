# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Current manual anchors bind real caller literals, not the stale bundled manual."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESTINATIONS = {
    "app-glossary",
    "the-publishing-steps-surfaces",
    "configuration-storage",
    "publishing-providers",
    "cdn-and-provider-options",
    "federation-activitypub",
    "report-a-beta-issue",
    "ch-before-meeting",
    "live-captions-what-the-settings-change",
}


def current_heading_ids() -> set[str]:
    result = subprocess.run(
        ["pandoc", str(ROOT / "docs/USER-MANUAL.md"), "-t", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {b["c"][1][0] for b in json.loads(result.stdout)["blocks"] if b["t"] == "Header"}


def assert_known(anchors: set[str], known: set[str]) -> None:
    assert anchors, "caller inventory unexpectedly empty"
    assert not anchors - known, f"unknown current manual anchors: {sorted(anchors - known)}"


def test_real_frontend_and_backend_literal_inventory() -> None:
    operator = ROOT / "civiccast/apps/portal-operator/src"
    callers = [
        "screens/StationProfileScreen.tsx",
        "screens/SetupScreen.tsx",
        "screens/ActivityPubScreen.tsx",
        "components/setup/SourceUploadWizard.tsx",
        "components/shell/Sidebar.tsx",
    ]
    literals: set[str] = set()
    for path in [
        *(operator / name for name in callers),
        ROOT / "civiccast/apps/portal-public/src/App.tsx",
    ]:
        text = path.read_text(encoding="utf-8")
        literals.update(re.findall(r"manualLink\(['\"]([^'\"]+)['\"]\)", text))
        literals.update(re.findall(r"/help#([a-z0-9-]+)", text))
    backend = (ROOT / "civiccast/installer/service.py").read_text(encoding="utf-8")
    literals.update(re.findall(r'manual_section="([^"]+)"', backend))
    assert_known(literals, current_heading_ids())
    public = (ROOT / "civiccast/apps/portal-public/src/App.tsx").read_text(encoding="utf-8")
    assert "'/operator/#/help#report-a-beta-issue'" in public
    assert 'to="/help#report-a-beta-issue"' in (
        operator / "components/shell/Sidebar.tsx"
    ).read_text(encoding="utf-8")


def test_actual_provider_cards_emit_current_destinations(monkeypatch: pytest.MonkeyPatch) -> None:
    from civiccast.installer import service

    monkeypatch.setattr(
        service,
        "build_backup_status",
        lambda: SimpleNamespace(status="ready", message="ready", next_step="verify"),
    )
    monkeypatch.setattr(
        service, "_activitypub_provider_state", lambda: ("not_set_up", "disabled", "review")
    )
    report = service.build_provider_readiness_report()
    expected = {
        "local-portal": "the-publishing-steps-surfaces",
        "backup": "configuration-storage",
        "internet-archive": "publishing-providers",
        "youtube": "publishing-providers",
        "subscriber-notifications": "publishing-providers",
        "local-nas": "publishing-providers",
        "podcast": "publishing-providers",
        "activitypub": "federation-activitypub",
        "cloudflare-r2": "cdn-and-provider-options",
        "bunny": "cdn-and-provider-options",
        "fastly": "cdn-and-provider-options",
        "akamai": "cdn-and-provider-options",
    }
    assert {row.id: row.manual_section for row in report.items} == expected


def test_absent_anchor_assertion_is_sensitive() -> None:
    with pytest.raises(AssertionError, match="unknown current manual anchors"):
        assert_known({"missing-section-control"}, current_heading_ids())


def test_reverted_real_caller_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    read_text = Path.read_text

    def reverted(path: Path, *args: object, **kwargs: object) -> str:
        text = read_text(path, *args, **kwargs)
        if path.name == "SourceUploadWizard.tsx":
            assert "manualLink('ch-before-meeting')" in text
            return text.replace(
                "manualLink('ch-before-meeting')", "manualLink('your-first-beta-workflow')"
            )
        return text

    monkeypatch.setattr(Path, "read_text", reverted)
    with pytest.raises(AssertionError, match="your-first-beta-workflow"):
        test_real_frontend_and_backend_literal_inventory()


def test_reporting_title_matches_canonical_and_assembled_manual() -> None:
    for name in (
        "docs/manual/src/11-signing-in.md",
        "docs/manual/src/17-something-wrong.md",
        "docs/USER-MANUAL.md",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert 'section "Don\'t Have A GitHub Account?"' not in text, name
        assert 'section "Report a beta issue"' in text, name

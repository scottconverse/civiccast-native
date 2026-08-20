# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The release-truth checker detects every drift class it claims to detect.

All tests run offline against fixtures (documentation-exact GitHub release
shapes). The live path shares check_live with the fixture path; network is
exercised only by the audit-control observer and the evidence run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "policy" / "check_release_truth.py"
REAL_MANIFEST = REPO_ROOT / "docs" / "releases" / "release-truth.yaml"

GOOD_MANIFEST = """\
schema_version: 1
repository: example/repo
current: v2
historical_unlisted_patterns:
  - '^v0\\.'
entries:
  - {tag: v2, status: current}
  - {tag: v1, status: withdrawn, superseded_by: v2}
"""

GOOD_RELEASES = [
    {"tag_name": "v2", "name": "v2 current", "body": "the good one", "draft": False},
    {"tag_name": "v1", "name": "v1 — WITHDRAWN", "body": "do not install", "draft": False},
    {"tag_name": "v0.9", "name": "ancient", "body": "", "draft": False},
]


def run(
    manifest: str,
    releases: list | None = None,
    readme: str | None = None,
    tmp_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(manifest, encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--manifest", str(mpath)]
    if releases is not None:
        rpath = tmp_path / "releases.json"
        rpath.write_text(json.dumps(releases), encoding="utf-8")
        cmd += ["--releases-json", str(rpath)]
    if readme is not None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(readme, encoding="utf-8")
        cmd += ["--readme", str(readme_path)]
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )


def test_clean_manifest_and_releases_pass(tmp_path: Path) -> None:
    result = run(GOOD_MANIFEST, GOOD_RELEASES, "Install v2 today. (v1 was withdrawn.)", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_two_current_entries_is_drift(tmp_path: Path) -> None:
    bad = GOOD_MANIFEST.replace(
        "{tag: v1, status: withdrawn, superseded_by: v2}", "{tag: v1, status: current}"
    )
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "exactly one current" in result.stdout


def test_withdrawn_without_successor_is_drift(tmp_path: Path) -> None:
    bad = GOOD_MANIFEST.replace(", superseded_by: v2", "")
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "superseded_by" in result.stdout


def test_missing_live_release_is_drift(tmp_path: Path) -> None:
    result = run(
        GOOD_MANIFEST, [r for r in GOOD_RELEASES if r["tag_name"] != "v1"], tmp_path=tmp_path
    )
    assert result.returncode == 1
    assert "no live GitHub release" in result.stdout


def test_withdrawn_without_live_marker_is_drift(tmp_path: Path) -> None:
    releases = json.loads(json.dumps(GOOD_RELEASES))
    releases[1]["name"] = "v1"
    releases[1]["body"] = "nothing to see"
    result = run(GOOD_MANIFEST, releases, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "no WITHDRAWN marker" in result.stdout


def test_unknown_live_release_is_drift(tmp_path: Path) -> None:
    releases = [*GOOD_RELEASES, {"tag_name": "v3", "name": "surprise", "body": "", "draft": False}]
    result = run(GOOD_MANIFEST, releases, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "no manifest entry" in result.stdout


def test_current_marked_withdrawn_live_is_drift(tmp_path: Path) -> None:
    releases = json.loads(json.dumps(GOOD_RELEASES))
    releases[0]["name"] = "v2 — WITHDRAWN"
    result = run(GOOD_MANIFEST, releases, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "marked WITHDRAWN live" in result.stdout


def test_lowercase_withdrawn_prose_is_not_a_marker(tmp_path: Path) -> None:
    # First-live-run regression: rc14's body says "supersedes the withdrawn
    # rc13" — healthy prose, not a withdrawal marker.
    releases = json.loads(json.dumps(GOOD_RELEASES))
    releases[0]["body"] = "This release supersedes the withdrawn v1 build."
    result = run(GOOD_MANIFEST, releases, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout


def test_marker_deep_in_body_does_not_mark_withdrawal(tmp_path: Path) -> None:
    releases = json.loads(json.dumps(GOOD_RELEASES))
    releases[1]["name"] = "v1"
    releases[1]["body"] = ("history " * 60) + "WITHDRAWN"  # beyond the head window
    result = run(GOOD_MANIFEST, releases, tmp_path=tmp_path)
    assert result.returncode == 1
    assert "no WITHDRAWN marker" in result.stdout


def test_readme_missing_current_is_drift(tmp_path: Path) -> None:
    result = run(GOOD_MANIFEST, GOOD_RELEASES, "This README mentions nothing relevant.", tmp_path)
    assert result.returncode == 1
    assert "never mentions the current release" in result.stdout


def test_readme_withdrawn_without_context_is_drift(tmp_path: Path) -> None:
    result = run(
        GOOD_MANIFEST,
        GOOD_RELEASES,
        "Install v2. Also historically we shipped v1 which was great.",
        tmp_path,
    )
    assert result.returncode == 1
    assert "without withdrawn/supersede context" in result.stdout


def test_malformed_manifest_exits_2(tmp_path: Path) -> None:
    result = run("current: [unclosed", tmp_path=tmp_path)
    assert result.returncode == 2


def test_superseded_dangling_successor_is_drift(tmp_path: Path) -> None:
    bad = GOOD_MANIFEST.replace(
        "{tag: v1, status: withdrawn, superseded_by: v2}",
        "{tag: v1, status: superseded, superseded_by: v99}",
    )
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "does not name an existing entry tag" in result.stdout


def test_superseded_missing_successor_is_drift(tmp_path: Path) -> None:
    bad = GOOD_MANIFEST.replace(
        "{tag: v1, status: withdrawn, superseded_by: v2}",
        "{tag: v1, status: superseded}",
    )
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "must name a superseded_by entry" in result.stdout


def test_non_mapping_yaml_exits_2(tmp_path: Path) -> None:
    result = run("- just\n- a\n- list\n", tmp_path=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_invalid_regex_pattern_exits_2(tmp_path: Path) -> None:
    bad = GOOD_MANIFEST.replace(r"'^v0\.'", "'['")
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_non_string_pattern_element_exits_2(tmp_path: Path) -> None:
    # CC-WS1-002 round 2: historical_unlisted_patterns: [42] used to reach
    # re.compile and traceback with TypeError at exit 1.
    bad = GOOD_MANIFEST.replace(r"- '^v0\.'", "- 42")
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_list_valued_entry_tag_exits_2(tmp_path: Path) -> None:
    # CC-WS1-002 round 2: a list-valued tag used to traceback with an
    # unhashable TypeError in set(tags) at exit 1.
    bad = GOOD_MANIFEST.replace("{tag: v2, status: current}", "{tag: [v2, oops], status: current}")
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_current_entry_without_tag_exits_2(tmp_path: Path) -> None:
    # CC-WS1-002 round 2: a current entry with no tag used to traceback with
    # KeyError at exit 1.
    bad = GOOD_MANIFEST.replace("{tag: v2, status: current}", "{status: current}")
    result = run(bad, tmp_path=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_releases_fixture_not_a_list_exits_2(tmp_path: Path) -> None:
    mpath = tmp_path / "manifest.yaml"
    mpath.write_text(GOOD_MANIFEST, encoding="utf-8")
    rpath = tmp_path / "releases.json"
    rpath.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--manifest", str(mpath), "--releases-json", str(rpath)]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR")
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_real_manifest_is_internally_consistent() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(REAL_MANIFEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_staging_entry_clears_unknown_tag_drift(tmp_path: Path) -> None:
    # rc15 pattern: a published-but-not-yet-installable release gets a staging
    # entry (no superseded_by required) instead of tripping unknown-tag drift.
    manifest = GOOD_MANIFEST.replace("entries:", "entries:\n  - {tag: v3, status: staging}")
    releases = [
        *GOOD_RELEASES,
        {"tag_name": "v3", "name": "v3 — coming", "body": "", "draft": False},
    ]
    result = run(manifest, releases, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

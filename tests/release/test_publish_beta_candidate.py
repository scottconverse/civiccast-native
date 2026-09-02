# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for scripts/release/publish_beta_candidate.py.

Every `gh`, `git`, and PowerShell subprocess call is faked via
``publish_beta_candidate.run_command`` (the single seam the script shells
out through) -- no real network, no real git remote, no real GitHub. The
script's live (non-dry-run) publish path against a real GitHub remote is
exercised here only through these fakes; it has never run end to end
against a real kit or real ``gh``/GitHub (see the task's final report).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.release.publish_beta_candidate as m

SOURCE_SHA = "a" * 40
TAG = "v1.0.0-beta.2"
VERSION = "1.0.0-beta.2"


def _write_kit(kit_dir: Path, *, with_packs: bool = True, with_station: bool = True) -> Path:
    kit_dir.mkdir(parents=True, exist_ok=True)
    setup = kit_dir / "setup.exe"
    setup.write_bytes(b"fake signed installer bytes")
    if with_packs:
        packs_dir = kit_dir / "packs"
        packs_dir.mkdir(exist_ok=True)
        (packs_dir / "native-app-payload.ccpack").write_bytes(b"pack-a")
        (packs_dir / "native-server-binaries.ccpack").write_bytes(b"pack-b")
    if with_station:
        (kit_dir / "station").mkdir(exist_ok=True)
    return setup


def _gate_a_doc(*, lane: str, verdict: str = "PASS", source_sha: str = SOURCE_SHA) -> dict:
    doc: dict = {"verdict": verdict, "source_sha": source_sha}
    if lane != "clean":
        doc["lane"] = lane
    return doc


def _fake_command_factory(
    *,
    product_version: str = VERSION,
    signature_status: str = "Valid",
    gate_a_docs: dict[str, dict] | None = None,
    missing_lanes: tuple[str, ...] = (),
    gh_release_view_assets: list[dict] | None = None,
    gh_release_create_fails: bool = False,
    git_tag_fails: bool = False,
    git_push_fails: bool = False,
):
    if gate_a_docs is None:
        gate_a_docs = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "powershell":
            script = cmd[-1]
            if "ProductVersion" in script:
                return Result(stdout=product_version)
            if "AuthenticodeSignature" in script:
                return Result(stdout=signature_status)
            return Result(returncode=1, stderr="unexpected powershell script")
        if cmd[0] == "gh":
            if cmd[1:3] == ["run", "download"]:
                name = cmd[cmd.index("-n") + 1]
                dest = Path(cmd[cmd.index("-D") + 1])
                lane = next(
                    (lane for lane in m.GATE_A_LANES if name == m.GATE_A_ARTIFACT_NAMES[lane].format(run_id="222")),
                    None,
                )
                if lane in missing_lanes or lane not in gate_a_docs:
                    return Result(returncode=1, stderr=f"no such artifact {name}")
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "gate-a-verdict.json").write_text(json.dumps(gate_a_docs[lane]))
                return Result()
            if cmd[1] == "release" and cmd[2] == "create":
                if gh_release_create_fails:
                    return Result(returncode=1, stderr="gh release create failed")
                return Result()
            if cmd[1] == "release" and cmd[2] == "view":
                payload = {"assets": gh_release_view_assets or []}
                return Result(stdout=json.dumps(payload))
            return Result(returncode=1, stderr=f"unexpected gh command {cmd}")
        if cmd[0] == "git":
            if cmd[1] == "tag":
                return Result(returncode=1 if git_tag_fails else 0, stderr="tag failed" if git_tag_fails else "")
            if cmd[1] == "push":
                return Result(returncode=1 if git_push_fails else 0, stderr="push failed" if git_push_fails else "")
            return Result(returncode=1, stderr=f"unexpected git command {cmd}")
        return Result(returncode=1, stderr=f"unexpected command {cmd}")

    fake_run.calls = calls
    return fake_run


def _base_repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs" / "releases").mkdir(parents=True)
    (root / "docs" / "releases" / "release-truth.yaml").write_text(
        "schema_version: 1\n"
        "repository: scottconverse/civiccast-native\n"
        "current: v1.0.0-beta.1\n"
        "entries:\n"
        "  - tag: v1.0.0-beta.1\n"
        "    status: current\n"
        "    notes: USB-delivered only.\n",
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- Something new.\n\n## [1.0.0-beta.1] - 2026-08-01\n\nOld.\n",
        encoding="utf-8",
    )
    return root


def _args(
    tmp_path: Path,
    kit_dir: Path,
    *,
    dry_run: bool = True,
    truth_status: str = "staging",
    repo_root: Path | None = None,
) -> list[str]:
    argv = [
        "--kit-dir",
        str(kit_dir),
        "--source-sha",
        SOURCE_SHA,
        "--build-run-id",
        "111",
        "--gate-a-run-id",
        "222",
        "--tag",
        TAG,
        "--truth-status",
        truth_status,
    ]
    if dry_run:
        argv.append("--dry-run")
    if repo_root is not None:
        argv.extend(["--repo-root", str(repo_root)])
    return argv


# ---------------------------------------------------------------------------
# (a) layout
# ---------------------------------------------------------------------------
def test_layout_missing_setup_exe_refuses(tmp_path):
    kit_dir = tmp_path / "kit"
    kit_dir.mkdir()
    (kit_dir / "packs").mkdir()
    (kit_dir / "station").mkdir()
    with pytest.raises(m.PublishError, match=r"missing setup\.exe"):
        m.verify_layout(kit_dir)


def test_layout_missing_packs_refuses(tmp_path):
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir, with_packs=False)
    with pytest.raises(m.PublishError, match="packs"):
        m.verify_layout(kit_dir)


def test_layout_empty_packs_dir_refuses(tmp_path):
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir, with_packs=False)
    (kit_dir / "packs").mkdir()
    with pytest.raises(m.PublishError, match=r"no \*\.ccpack"):
        m.verify_layout(kit_dir)


def test_layout_missing_station_dir_refuses(tmp_path):
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir, with_station=False)
    with pytest.raises(m.PublishError, match="station"):
        m.verify_layout(kit_dir)


def test_layout_missing_kit_dir_refuses(tmp_path):
    with pytest.raises(m.PublishError, match="does not exist"):
        m.verify_layout(tmp_path / "nope")


def test_end_to_end_refuses_on_bad_layout(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    kit_dir.mkdir()  # empty: no setup.exe, no packs, no station
    monkeypatch.setattr(m, "run_command", _fake_command_factory())
    argv = _args(tmp_path, kit_dir, repo_root=repo_root)
    assert m.main(argv) == 1


# ---------------------------------------------------------------------------
# (a) version identity
# ---------------------------------------------------------------------------
def test_version_mismatch_setup_exe_refuses(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(product_version="9.9.9"))
    with pytest.raises(m.PublishError, match="ProductVersion"):
        m.verify_version_identity(Path("setup.exe"), TAG)


def test_version_mismatch_source_tree_refuses(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(product_version=VERSION))
    monkeypatch.setattr(m, "get_native_source_version", lambda: "9.9.9")
    with pytest.raises(m.PublishError, match="_native_version"):
        m.verify_version_identity(Path("setup.exe"), TAG)


def test_tag_without_v_prefix_refuses(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory())
    with pytest.raises(m.PublishError, match="must start with 'v'"):
        m.verify_version_identity(Path("setup.exe"), "1.0.0-beta.2")


def test_end_to_end_refuses_on_version_mismatch(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    monkeypatch.setattr(m, "run_command", _fake_command_factory(product_version="9.9.9"))
    argv = _args(tmp_path, kit_dir, repo_root=repo_root)
    assert m.main(argv) == 1


# ---------------------------------------------------------------------------
# (b) signature
# ---------------------------------------------------------------------------
def test_signature_not_valid_refuses(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(signature_status="NotSigned"))
    with pytest.raises(m.PublishError, match="Valid"):
        m.verify_signature(Path("setup.exe"))


def test_end_to_end_refuses_on_bad_signature(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    monkeypatch.setattr(m, "run_command", _fake_command_factory(signature_status="HashMismatch"))
    argv = _args(tmp_path, kit_dir, repo_root=repo_root)
    assert m.main(argv) == 1


# ---------------------------------------------------------------------------
# (c) Gate A verdicts
# ---------------------------------------------------------------------------
def test_gate_a_missing_lane_refuses(tmp_path, monkeypatch):
    fake = _fake_command_factory(missing_lanes=("dirty",))
    monkeypatch.setattr(m, "run_command", fake)
    with pytest.raises(m.PublishError, match="dirty"):
        m.download_gate_a_verdicts(
            repository="scottconverse/civiccast-native",
            gate_a_run_id="222",
            dest_dir=tmp_path / "gate-a",
        )


def test_gate_a_non_pass_verdict_refuses():
    verdicts = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    verdicts["clean"]["verdict"] = "FAIL"
    with pytest.raises(m.PublishError, match="did not PASS"):
        m.verify_gate_a_verdicts(verdicts, source_sha=SOURCE_SHA)


def test_gate_a_sha_mismatch_refuses():
    verdicts = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    verdicts["dirty"]["source_sha"] = "b" * 40
    with pytest.raises(m.PublishError, match="source_sha"):
        m.verify_gate_a_verdicts(verdicts, source_sha=SOURCE_SHA)


def test_gate_a_missing_lane_key_refuses():
    verdicts = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    del verdicts["download-only"]
    with pytest.raises(m.PublishError, match="download-only"):
        m.verify_gate_a_verdicts(verdicts, source_sha=SOURCE_SHA)


def test_end_to_end_refuses_on_gate_a_failure(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    docs = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    docs["download-only"]["verdict"] = "FAIL"
    monkeypatch.setattr(m, "run_command", _fake_command_factory(gate_a_docs=docs))
    argv = _args(tmp_path, kit_dir, repo_root=repo_root)
    assert m.main(argv) == 1


# ---------------------------------------------------------------------------
# (f) asset upload size mismatch
# ---------------------------------------------------------------------------
def test_asset_size_mismatch_refuses(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")  # 5 bytes locally
    monkeypatch.setattr(
        m,
        "run_command",
        _fake_command_factory(gh_release_view_assets=[{"name": "setup.exe", "size": 999}]),
    )
    with pytest.raises(m.PublishError, match="size mismatch"):
        m.verify_published_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )


def test_asset_missing_from_release_refuses(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")
    monkeypatch.setattr(
        m, "run_command", _fake_command_factory(gh_release_view_assets=[])
    )
    with pytest.raises(m.PublishError, match="missing expected asset"):
        m.verify_published_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )


# ---------------------------------------------------------------------------
# dry-run end-to-end
# ---------------------------------------------------------------------------
def test_dry_run_produces_expected_artifacts(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    setup = _write_kit(kit_dir)
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    argv = _args(tmp_path, kit_dir, repo_root=repo_root)
    rc = m.main(argv)
    assert rc == 0

    out_dir = repo_root / "artifacts" / "release" / TAG
    notes = (out_dir / "RELEASE-NOTES.md").read_text(encoding="utf-8")
    sidecar = json.loads((out_dir / f"{setup.name}.sidecar.json").read_text(encoding="utf-8"))
    sums = (out_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")

    # sidecar shape matches check_sidecar_attestation_integrity.py's contract
    assert sidecar["attestation"] is None
    assert sidecar["install_manifest"]["signed"] is True
    assert sidecar["sha256"] == m.sha256_file(setup)

    # SHA256SUMS.txt lists setup.exe and both packs
    assert f"{m.sha256_file(setup)}  setup.exe" in sums
    assert "native-app-payload.ccpack" in sums
    assert "native-server-binaries.ccpack" in sums

    # notes contain the source sha, all three lane verdicts, and every asset hash
    assert SOURCE_SHA in notes
    assert "| clean | PASS |" in notes
    assert "| dirty | PASS |" in notes
    assert "| download-only | PASS |" in notes
    for path in [setup, kit_dir / "packs" / "native-app-payload.ccpack", kit_dir / "packs" / "native-server-binaries.ccpack"]:
        assert m.sha256_file(path) in notes
    assert "beta candidate, not a production release" in notes.lower()
    assert "download setup.exe" in notes.lower() or "download `setup.exe`" in notes.lower()

    # dry run must not have touched the real release-truth.yaml on disk
    # (only via update_release_truth called on a scratch copy for the summary)
    truth_text = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert TAG not in truth_text

    # no git/gh mutating calls were made
    calls = m.run_command.calls
    assert not any(c[0] == "git" and c[1] in ("tag", "push") for c in calls)
    assert not any(c[0] == "gh" and c[1:3] == ["release", "create"] for c in calls)


def test_dry_run_with_current_status_does_not_touch_real_file(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    argv = _args(tmp_path, kit_dir, truth_status="current", repo_root=repo_root)
    rc = m.main(argv)
    assert rc == 0

    truth_text = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert "current: v1.0.0-beta.1" in truth_text  # unchanged


# ---------------------------------------------------------------------------
# live (non-dry-run) path -- fully faked, exercises the wiring only
# ---------------------------------------------------------------------------
def test_live_publish_updates_release_truth_and_tags(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    setup = _write_kit(kit_dir)

    def gh_assets_for(*_a, **_kw):
        return None  # filled below after we know asset names

    fake = _fake_command_factory(
        gh_release_view_assets=[
            {"name": "setup.exe", "size": setup.stat().st_size},
            {"name": "native-app-payload.ccpack", "size": 6},
            {"name": "native-server-binaries.ccpack", "size": 6},
            {"name": "SHA256SUMS.txt", "size": 999999},  # placeholder, fixed below
            {"name": "setup.exe.sidecar.json", "size": 999999},
        ],
    )
    monkeypatch.setattr(m, "run_command", fake)

    argv = _args(
        tmp_path, kit_dir, dry_run=False, truth_status="current", repo_root=repo_root
    )
    # SHA256SUMS.txt / sidecar sizes are computed after write, so a bogus
    # placeholder size above will legitimately fail the post-upload size
    # check -- assert that failure mode explicitly rather than special-casing
    # it away, since it proves the check is real.
    rc = m.main(argv)
    assert rc == 1

    calls = m.run_command.calls
    assert any(c[0] == "git" and c[1] == "tag" for c in calls)
    assert any(c[0] == "git" and c[1] == "push" for c in calls)
    assert any(c[0] == "gh" and c[1:3] == ["release", "create"] for c in calls)


# ---------------------------------------------------------------------------
# release-truth.yaml update
# ---------------------------------------------------------------------------
def test_update_release_truth_staging_adds_entry_without_flipping_current(tmp_path):
    truth_path = tmp_path / "release-truth.yaml"
    truth_path.write_text(
        "schema_version: 1\nrepository: scottconverse/civiccast-native\ncurrent: v1.0.0-beta.1\nentries:\n"
        "  - tag: v1.0.0-beta.1\n    status: current\n    notes: USB only.\n",
        encoding="utf-8",
    )
    summary = m.update_release_truth(
        truth_path=truth_path, tag=TAG, status="staging", notes="staging candidate"
    )
    text = truth_path.read_text(encoding="utf-8")
    assert f"tag: {TAG}" in text
    assert "status: staging" in text
    assert "current: v1.0.0-beta.1" in text  # unchanged
    assert TAG in summary


def test_update_release_truth_current_flips_previous_entry(tmp_path):
    truth_path = tmp_path / "release-truth.yaml"
    truth_path.write_text(
        "schema_version: 1\nrepository: scottconverse/civiccast-native\ncurrent: v1.0.0-beta.1\nentries:\n"
        "  - tag: v1.0.0-beta.1\n    status: current\n    notes: USB only.\n",
        encoding="utf-8",
    )
    m.update_release_truth(truth_path=truth_path, tag=TAG, status="current", notes="published")
    text = truth_path.read_text(encoding="utf-8")
    assert f"current: {TAG}" in text
    assert "- tag: v1.0.0-beta.1\n    status: superseded" in text
    assert f"superseded_by: {TAG}" in text


def test_update_release_truth_rejects_bad_status(tmp_path):
    truth_path = tmp_path / "release-truth.yaml"
    truth_path.write_text("schema_version: 1\ncurrent: x\nentries:\n", encoding="utf-8")
    with pytest.raises(m.PublishError, match="truth-status"):
        m.update_release_truth(truth_path=truth_path, tag=TAG, status="bogus", notes="x")


# ---------------------------------------------------------------------------
# hashing / sidecar / SHA256SUMS shape
# ---------------------------------------------------------------------------
def test_build_sidecar_shape(tmp_path):
    f = tmp_path / "setup.exe"
    f.write_bytes(b"hello")
    sidecar = m.build_sidecar(f, signed=True)
    assert set(sidecar) == {"sha256", "attestation", "install_manifest"}
    assert sidecar["attestation"] is None
    assert sidecar["install_manifest"] == {"signed": True}
    assert sidecar["sha256"] == m.sha256_file(f)


def test_build_sha256sums_format(tmp_path):
    f1 = tmp_path / "a.ccpack"
    f1.write_bytes(b"aaa")
    f2 = tmp_path / "b.ccpack"
    f2.write_bytes(b"bbb")
    text = m.build_sha256sums([f1, f2])
    lines = text.splitlines()
    assert lines[0] == f"{m.sha256_file(f1)}  a.ccpack"
    assert lines[1] == f"{m.sha256_file(f2)}  b.ccpack"


def test_extract_changelog_unreleased():
    changelog = (
        "# Changelog\n\n## [Unreleased]\n\nSome new stuff.\n\n## [1.0.0-beta.1] - 2026-08-01\n\nOld stuff.\n"
    )
    section = m.extract_changelog_unreleased(changelog)
    assert "Some new stuff." in section
    assert "Old stuff." not in section


def test_extract_changelog_unreleased_missing_section_returns_empty():
    assert m.extract_changelog_unreleased("# Changelog\n\nNo sections here.\n") == ""

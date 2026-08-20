# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3d-ii — remote-contribution commissioning install.

Covers civiccast.installer.contribution_install: the managed dir, the
stage→verify→atomic-swap clone of the pinned VDO.Ninja commit, idempotency, the
drift-rejection (a clone that resolves to the wrong commit never becomes live),
and the status report. A FakeGit stands in for real git (the live clone is an LPM
proof). A gated network test re-confirms the pin upstream with git ls-remote.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.auth.models import OperatorIdentity
from civiccast.installer.contribution_install import (
    VDO_PINNED_COMMIT,
    VDO_REPO,
    VDO_VERSION,
    ContributionInstallError,
    contribution_install_status,
    install_remote_contribution,
    managed_contribution_dir,
)


class _FakeGit:
    """Simulates `git clone` (creates the dir + writes a .head marker) and
    `git rev-parse HEAD` (reads the marker). The marker file survives the
    staging→target rename, so verification reflects the cloned commit."""

    def __init__(self, clone_commit: str) -> None:
        self.clone_commit = clone_commit
        self.clone_calls = 0

    def __call__(self, args: list[str], cwd: Path | None = None) -> str:
        if args and args[0] == "clone":
            dest = Path(args[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / ".head").write_text(self.clone_commit, encoding="utf-8")
            self.clone_calls += 1
            return ""
        if args and args[0] == "rev-parse":
            head = Path(cwd) / ".head"  # type: ignore[arg-type]
            if not head.exists():
                raise subprocess.CalledProcessError(128, ["git", *args])
            return head.read_text(encoding="utf-8").strip()
        return ""


def test_managed_dir_respects_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION_HOME", str(tmp_path / "rc"))
    assert managed_contribution_dir() == tmp_path / "rc"


def test_install_clones_verifies_and_swaps(tmp_path) -> None:
    git = _FakeGit(clone_commit=VDO_PINNED_COMMIT)
    target = tmp_path / "vdo.ninja"
    report = install_remote_contribution(git_runner=git, dest=target)
    assert report.vdo_installed and report.vdo_verified
    assert git.clone_calls == 1
    assert target.is_dir() and (target / ".head").exists()
    assert not (tmp_path / "vdo.ninja.staging").exists()  # staging swapped away
    assert report.coturn_action  # coturn guidance always present
    assert "CIVICCAST_VDO_COMMAND" in report.launch_hint


def test_install_rejects_a_drifted_clone(tmp_path) -> None:
    git = _FakeGit(clone_commit="deadbeef" * 5)  # not the pin
    target = tmp_path / "vdo.ninja"
    with pytest.raises(ContributionInstallError, match="refusing to install"):
        install_remote_contribution(git_runner=git, dest=target)
    # The tampered clone never becomes the live copy, and staging is cleaned.
    assert not target.exists()
    assert not (tmp_path / "vdo.ninja.staging").exists()


def test_install_is_idempotent_when_already_pinned(tmp_path) -> None:
    target = tmp_path / "vdo.ninja"
    target.mkdir()
    (target / ".head").write_text(VDO_PINNED_COMMIT, encoding="utf-8")
    git = _FakeGit(clone_commit=VDO_PINNED_COMMIT)
    report = install_remote_contribution(git_runner=git, dest=target)
    assert report.vdo_verified
    assert git.clone_calls == 0  # already verified — no re-clone


def test_install_reclones_when_commit_drifted(tmp_path) -> None:
    target = tmp_path / "vdo.ninja"
    target.mkdir()
    (target / ".head").write_text("oldcommit", encoding="utf-8")
    git = _FakeGit(clone_commit=VDO_PINNED_COMMIT)
    report = install_remote_contribution(git_runner=git, dest=target)
    assert report.vdo_verified and git.clone_calls == 1
    assert (target / ".head").read_text(encoding="utf-8").strip() == VDO_PINNED_COMMIT


def test_status_reports_presence_and_verification(tmp_path) -> None:
    target = tmp_path / "vdo.ninja"
    git = _FakeGit(clone_commit=VDO_PINNED_COMMIT)
    absent = contribution_install_status(dest=target, git_runner=git)
    assert absent.vdo_installed is False and absent.vdo_verified is False

    target.mkdir()
    (target / ".head").write_text(VDO_PINNED_COMMIT, encoding="utf-8")
    present = contribution_install_status(dest=target, git_runner=git)
    assert present.vdo_installed and present.vdo_verified


def _installer_client(scopes: tuple[str, ...] | None) -> TestClient:
    from civiccast.installer.router import staff_router as installer_staff_router

    app = FastAPI()

    @app.middleware("http")
    async def _ident(request, call_next):
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(installer_staff_router)
    return TestClient(app)


def test_status_endpoint_reads_safely(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION_HOME", str(tmp_path))
    r = _installer_client(("support_admin",)).get("/api/staff/installer/remote-contribution")
    assert r.status_code == 200
    assert r.json()["vdo_installed"] is False  # nothing cloned in the tmp home


def test_install_endpoint_is_role_gated(tmp_path, monkeypatch) -> None:
    # meeting_operator is NOT setup/support_admin -> 403 before any clone runs.
    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION_HOME", str(tmp_path))
    r = _installer_client(("meeting_operator",)).post(
        "/api/staff/installer/remote-contribution/install"
    )
    assert r.status_code == 403


@pytest.mark.skipif(not __import__("shutil").which("git"), reason="git not on PATH")
def test_pinned_commit_matches_upstream_tag() -> None:
    """Network-gated: the pinned commit must still be what v30.2 resolves to
    upstream. Skips offline; fails loudly if the pin drifted from the tag."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        with tempfile.TemporaryDirectory() as git_cwd:
            out = subprocess.run(
                ["git", "ls-remote", VDO_REPO, VDO_VERSION],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                cwd=git_cwd,
                env=env,
            ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        pytest.skip(f"offline or git ls-remote unavailable: {exc}")
    assert out, "no ref returned for the pinned tag"
    resolved = out.split()[0]
    assert resolved == VDO_PINNED_COMMIT, (
        f"VDO.Ninja {VDO_VERSION} now resolves to {resolved}; the pin "
        f"{VDO_PINNED_COMMIT} is stale — review the upgrade before bumping."
    )

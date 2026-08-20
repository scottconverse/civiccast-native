# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S12 (build step 8) slice 2 — OTT build orchestration.

Covers civiccast.app_platform.build_orchestrator.orchestrate_build (snapshot
config -> injected runner -> real SHA-256 -> recorded AppBuildRecord) + sha256_file,
with an offline fake runner. The node-toolchain default runner is the
platform-coupled seam (device/emulator proof = OTT lab lane), not exercised here.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

import civiccast.app_platform.build_orchestrator as build_orchestrator
from civiccast.app_platform.build_orchestrator import (
    BuildOrchestrationError,
    BuildRunner,
    BuiltArtifact,
    default_shell_build_runner,
    orchestrate_build,
    sha256_file,
)
from civiccast.app_platform.build_store import AppBuildStore
from civiccast.app_platform.models import StationAppConfig
from civiccast.app_platform.store import AppPlatformConfigStore

_T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _config() -> StationAppConfig:
    return AppPlatformConfigStore().read_config()  # the default station config


def _fake_runner(written: list[str]) -> BuildRunner:
    def run(app_target: str, work_dir: Path) -> BuiltArtifact:
        path = work_dir / f"{app_target}.zip"
        path.write_bytes(b"artifact-bytes-" + app_target.encode())
        written.append(app_target)
        return BuiltArtifact(
            artifact_path=str(path),
            entry_point="index.html",
            manifest_json={"appTarget": app_target},
        )

    return run


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello world")
    assert sha256_file(path) == hashlib.sha256(b"hello world").hexdigest()


def test_orchestrate_build_records_a_verified_artifact(tmp_path: Path) -> None:
    store = AppBuildStore()
    written: list[str] = []
    record = orchestrate_build(
        config=_config(),
        app_target="roku",
        store=store,
        work_dir=tmp_path,
        build_runner=_fake_runner(written),
        built_by="op_a",
        clock=lambda: _T0,
        id_factory=lambda: "appbld_1",
    )
    assert written == ["roku"]
    assert record.record_id == "appbld_1"
    assert record.app_target == "roku"
    assert record.app_name == _config().build_profile.app_name
    assert record.built_at == _T0
    assert record.proof_boundary == "local-build-artifact-sha256-verified"
    # SHA-256 is computed over the real produced artifact.
    assert record.artifact_sha256 == sha256_file(Path(record.artifact_path))
    assert record.channels  # channel branding snapshot captured
    # Recorded in the append-only store.
    assert store.get_build("appbld_1") is not None


def test_build_tier_override_else_profile_default(tmp_path: Path) -> None:
    store = AppBuildStore()
    branded = orchestrate_build(
        config=_config(),
        app_target="web_pwa",
        store=store,
        work_dir=tmp_path,
        build_runner=_fake_runner([]),
        built_by="op",
        build_tier="branded",
        id_factory=lambda: "b1",
    )
    assert branded.build_tier == "branded"
    default = orchestrate_build(
        config=_config(),
        app_target="tvos",
        store=store,
        work_dir=tmp_path,
        build_runner=_fake_runner([]),
        built_by="op",
        id_factory=lambda: "b2",
    )
    assert default.build_tier == _config().build_profile.tier  # falls back to the profile


def test_non_buildable_target_raises(tmp_path: Path) -> None:
    store = AppBuildStore()
    with pytest.raises(BuildOrchestrationError, match="not a buildable"):
        orchestrate_build(
            config=_config(),
            app_target="cg",
            store=store,
            work_dir=tmp_path,
            build_runner=_fake_runner([]),
            built_by="op",
        )


def test_missing_artifact_raises(tmp_path: Path) -> None:
    store = AppBuildStore()

    def bad_runner(app_target: str, work_dir: Path) -> BuiltArtifact:
        return BuiltArtifact(artifact_path=str(work_dir / "never-written.zip"), entry_point="x")

    with pytest.raises(BuildOrchestrationError, match="did not produce"):
        orchestrate_build(
            config=_config(),
            app_target="roku",
            store=store,
            work_dir=tmp_path,
            build_runner=bad_runner,
            built_by="op",
        )


def test_default_shell_build_runner_wraps_missing_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_node(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("node")

    monkeypatch.setattr(build_orchestrator.subprocess, "run", missing_node)
    runner = default_shell_build_runner(tmp_path)

    with pytest.raises(BuildOrchestrationError, match="node"):
        runner("roku", tmp_path / "work")

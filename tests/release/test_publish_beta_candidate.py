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

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import scripts.release.publish_beta_candidate as m
from scripts.release.candidate_manual import (
    DOCX_FILENAME,
    MANIFEST_FILENAME,
    PDF_FILENAME,
    create_candidate_manual_receipt,
)

SOURCE_SHA = "a" * 40
# publish_beta_candidate.verify_version_identity fail-closed-compares the
# tag against the REAL, live civiccast._native_version.__version__ (see
# get_native_source_version()) -- not a fixture/mock -- so these constants
# must track the repo's actual current source version or every publish-path
# test refuses with a version-identity mismatch that has nothing to do with
# what each test is actually exercising. Derived through the script's own
# seam rather than hardcoded: a release-prep bump (source version moves to
# the next candidate while release-truth.yaml's `current` stays on the
# published tag) must not break these tests, and the publisher publishes
# whatever tag it is handed -- it never assumes a `staging` entry is the tag
# being published. The release-truth.yaml these tests exercise is the
# self-contained fixture in _base_repo_root(), not the repo's real file.
VERSION = m.get_native_source_version()
TAG = f"v{VERSION}"


def test_run_powershell_isolates_only_psmodulepath(monkeypatch: pytest.MonkeyPatch) -> None:
    module_path_key = "PSModulePath"  # Exercise the conventional mixed-case Windows spelling.
    monkeypatch.setenv(module_path_key, "inherited-module-path-must-not-cross-boundary")
    monkeypatch.setenv("CIVICCAST_TEST_CHILD_ENV", "preserved")
    observed: dict[str, object] = {}

    def fake_run_command(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout="Valid\n", stderr="")

    monkeypatch.setattr(m, "run_command", fake_run_command)
    result = m.run_powershell("Get-AuthenticodeSignature")

    child_env = observed["env"]
    assert isinstance(child_env, dict)
    assert not any(name.casefold() == "psmodulepath" for name in child_env)
    assert child_env["CIVICCAST_TEST_CHILD_ENV"] == "preserved"
    assert os.environ[module_path_key] == "inherited-module-path-must-not-cross-boundary"
    assert observed["command"][:3] == ["powershell", "-NoProfile", "-NonInteractive"]
    assert result.stdout == "Valid\n"


def _write_kit(
    kit_dir: Path,
    *,
    with_packs: bool = True,
    with_station: bool = True,
    with_manual: bool = True,
) -> Path:
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
    if with_manual:
        manual_dir = kit_dir / "manual"
        manual_dir.mkdir(exist_ok=True)
        pdf = manual_dir / PDF_FILENAME
        docx = manual_dir / DOCX_FILENAME
        pdf.write_bytes(b"fixture candidate pdf")
        docx.write_bytes(b"fixture candidate docx")
        artifacts = [
            {
                "path": f"artifacts/release-preparation/manual/{path.name}",
                "sha256": m.sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in (pdf, docx)
        ]
        source = m.REPO_ROOT / "docs" / "USER-MANUAL.md"
        source_hash = source.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        manifest = {
            "source": "docs/USER-MANUAL.md",
            "source_sha256": hashlib.sha256(source_hash.encode("utf-8")).hexdigest(),
            "artifacts": artifacts,
        }
        (manual_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
        create_candidate_manual_receipt(
            manual_dir=manual_dir,
            source_sha=SOURCE_SHA,
            workflow_run_id="111",
            repo_root=m.REPO_ROOT,
        )
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
    gh_auth_fails: bool = False,
    gh_release_view_assets: list[dict] | None = None,
    mirror_uploaded_assets: bool = False,
    gh_release_view_is_draft: bool = True,
    gh_release_create_fails: bool = False,
    gh_release_edit_fails: bool = False,
    gh_release_delete_fails: bool = False,
):
    """Fake for every subprocess the publisher shells out through.

    ``mirror_uploaded_assets=True`` makes ``gh release view`` report exactly
    the names/sizes of the files passed to ``gh release create`` (a faithful
    happy path); ``gh_release_view_assets`` overrides that with a fixed list
    (to simulate a mismatch). ``git`` is never expected: the publisher must
    not run it, and any call is reported as unexpected.
    """

    if gate_a_docs is None:
        gate_a_docs = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    calls: list[list[str]] = []
    uploaded: list[Path] = []

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
            if cmd[1:3] == ["auth", "status"]:
                if gh_auth_fails:
                    return Result(
                        returncode=1,
                        stderr="You are not logged into any GitHub hosts. Run gh auth login",
                    )
                return Result()
            if cmd[1:3] == ["run", "download"]:
                name = cmd[cmd.index("-n") + 1]
                dest = Path(cmd[cmd.index("-D") + 1])
                lane = next(
                    (
                        lane
                        for lane in m.GATE_A_LANES
                        if name == m.GATE_A_ARTIFACT_NAMES[lane].format(run_id="111")
                    ),
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
                notes_idx = cmd.index("--notes-file")
                uploaded.extend(Path(p) for p in cmd[notes_idx + 2 :])
                return Result()
            if cmd[1] == "release" and cmd[2] == "view":
                if gh_release_view_assets is not None:
                    assets = gh_release_view_assets
                elif mirror_uploaded_assets:
                    assets = [{"name": p.name, "size": p.stat().st_size} for p in uploaded]
                else:
                    assets = []
                payload = {"assets": assets, "isDraft": gh_release_view_is_draft}
                return Result(stdout=json.dumps(payload))
            if cmd[1] == "release" and cmd[2] == "edit":
                if gh_release_edit_fails:
                    return Result(returncode=1, stderr="edit failed")
                return Result()
            if cmd[1] == "release" and cmd[2] == "delete":
                if gh_release_delete_fails:
                    return Result(returncode=1, stderr="delete failed")
                return Result()
            return Result(returncode=1, stderr=f"unexpected gh command {cmd}")
        return Result(returncode=1, stderr=f"unexpected command {cmd}")

    fake_run.calls = calls
    return fake_run


def _gh_calls(calls: list[list[str]], *prefix: str) -> list[list[str]]:
    return [c for c in calls if c[: len(prefix)] == list(prefix)]


def _assert_no_tag_or_public_release(calls: list[list[str]]) -> None:
    """The no-orphan invariant: nothing ever runs git, and un-draft never ran."""
    assert not any(c[0] == "git" for c in calls)
    assert not any("--draft=false" in c for c in _gh_calls(calls, "gh", "release", "edit"))


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


DIRECT_SOURCE_SHA = "b" * 40


def _write_bound_json(path: Path, value: dict) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "sha256": m.sha256_file(path)}


def _write_bound_text(path: Path, value: str) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return {"path": str(path), "sha256": m.sha256_file(path)}


def _write_direct_kit(
    kit_dir: Path,
    *,
    source_sha: str,
    build_run_id: str,
    consumer_mode: str = "sandbox",
) -> tuple[Path, Path]:
    kit_dir.mkdir(parents=True)
    setup = kit_dir / "CivicCast (Native)_1.0.0-beta.11_x64-setup.exe"
    setup.write_bytes(b"fake signed Beta 11 installer")
    (kit_dir / "QUICKSTART-OPERATOR.md").write_text("Beta 11 quickstart\n", encoding="utf-8")
    packs_dir = kit_dir / "packs"
    packs_dir.mkdir()
    for name in (
        "native-app-payload",
        "native-cuda-runtime",
        "native-ffmpeg-runtime",
        "native-ollama-runtime",
        "native-server-binaries",
    ):
        (packs_dir / f"{name}.ccpack").write_bytes(name.encode())
    station_dir = kit_dir / "station"
    station_dir.mkdir()
    for name in (
        "captions-floor",
        "captions-whistle",
        "core",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    ):
        (station_dir / f"{name}.ccpack").write_bytes(name.encode())
    (station_dir / "station-index.json").write_text("{}\n", encoding="utf-8")
    (station_dir / "SHA256SUMS.txt").write_text("fixture\n", encoding="utf-8")
    manual_dir = kit_dir / "manual"
    manual_dir.mkdir()
    pdf = manual_dir / PDF_FILENAME
    docx = manual_dir / DOCX_FILENAME
    pdf.write_bytes(b"fixture Beta 11 PDF")
    docx.write_bytes(b"fixture Beta 11 DOCX")
    source = m.REPO_ROOT / "docs" / "USER-MANUAL.md"
    source_text = source.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    (manual_dir / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "source": "docs/USER-MANUAL.md",
                "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "artifacts": [
                    {
                        "path": f"artifacts/release-preparation/manual/{path.name}",
                        "sha256": m.sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                    for path in (pdf, docx)
                ],
            }
        ),
        encoding="utf-8",
    )
    create_candidate_manual_receipt(
        manual_dir=manual_dir,
        source_sha=source_sha,
        workflow_run_id=build_run_id,
        repo_root=m.REPO_ROOT,
    )

    members = [
        {
            "path": path.relative_to(kit_dir).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": m.sha256_file(path),
        }
        for path in sorted(kit_dir.rglob("*"))
        if path.is_file()
    ]
    assert len(members) == 19
    assembly = {
        "schema_version": 1,
        "source_sha": source_sha,
        "workflow_run_id": int(build_run_id),
        "installer": {
            "path": setup.name,
            "size_bytes": setup.stat().st_size,
            "sha256": m.sha256_file(setup),
        },
        "membership": {
            "files": 19,
            "installer_pack_count": 5,
            "station_pack_count": 6,
            "station_folder_present": True,
        },
        "station_index": {
            "signature_verification": {
                "consumer_activation_verification": (
                    "pending exact signed host refresh and activation."
                    if consumer_mode == "physical-host"
                    else {
                        "status": "passed",
                        "actual_sandbox_result": {
                            "baseline_install": {"status": "passed", "exit_code": 0},
                            "upgrade_install": {
                                "status": "passed",
                                "exit_code": 0,
                                "payload": "setup.exe plus exactly five runtime packs; no station folder",
                            },
                            "verify_after_upgrade": {"status": "passed", "exit_code": 0},
                        },
                    }
                )
            }
        },
        "kit_members": members,
    }
    assembly_path = kit_dir.parent / "kit-assembly-receipt.json"
    return setup, _write_bound_json(assembly_path, assembly)


def _write_direct_consumer_receipt(
    tmp_path: Path,
    kit_dir: Path,
    *,
    source_sha: str = DIRECT_SOURCE_SHA,
    build_run_id: str = "333",
    runtime_proof_scope: str | None = None,
    consumer_mode: str = "sandbox",
    previous_version: str = "1.0.0-beta.9",
) -> tuple[Path, Path]:
    setup, assembly_ref = _write_direct_kit(
        kit_dir,
        source_sha=source_sha,
        build_run_id=build_run_id,
        consumer_mode=consumer_mode,
    )
    evidence_dir = tmp_path / "consumer-evidence"
    installer_run = {"sha256": m.sha256_file(setup), "exit_code": 0}
    if consumer_mode == "physical-host":
        evidence_dir = tmp_path / "consumer-evidence"
        manifest = {
            "civiccast": {
                "version": "1.0.0b11",
                "source_state": {"head": source_sha, "dirty": False},
            },
            "files": [],
        }
        manifest_ref = _write_bound_json(
            evidence_dir / "installed-app-payload-manifest.json", manifest
        )
        host_install = {
            "kind": "beta11-exact-host-install",
            "stage": "completed",
            "status": "passed",
            "source_sha": source_sha,
            "build_run_id": build_run_id,
            "setup_path": str(setup.resolve()),
            "setup_sha256": m.sha256_file(setup),
            "setup_authenticode": {
                "status": "Valid",
                "signer_subject": "CN=Scott Converse, O=Scott Converse, L=Longmont, S=co, C=US",
                "file_version": VERSION,
            },
            "installer_exit_code": 0,
            "before": {
                "display_version": previous_version,
                "service_state": "Running",
                "schedule_loop_enabled": True,
                "install_location": "C:/Program Files/CivicCast (Native)",
                "health": {
                    "status": "healthy",
                    "version": previous_version,
                    "schema": "current",
                    "schema_db_revision": "0087_retention_terms",
                },
            },
            "after": {
                "display_version": VERSION,
                "service_state": "Running",
                "schedule_loop_enabled": True,
                "install_location": "C:/Program Files/CivicCast (Native)",
                "health": {
                    "status": "healthy",
                    "version": VERSION,
                    "schema": "current",
                    "schema_db_revision": "0087_retention_terms",
                },
                "app_payload_manifest_path": "C:/Program Files/CivicCast (Native)/runtime/app-payload-manifest.json",
                "app_payload_manifest_sha256": manifest_ref["sha256"],
                "app_payload_manifest_verified": True,
            },
        }
        host_install_ref = _write_bound_json(
            evidence_dir / "actual-host-install.json", host_install
        )
        sample_start = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
        snapshots = []
        for sample_index in range(2):
            sample_at = sample_start + timedelta(seconds=45 * sample_index)
            channels = []
            for channel in ("public", "government", "education"):
                channels.append(
                    {
                        "id": channel,
                        "state": {"state": "ON_AIR"},
                        "ffprobe_streams": [
                            {"codec_type": "video", "codec_name": "h264"},
                            {"codec_type": "audio", "codec_name": "aac"},
                        ],
                        "caption_runtime_status": {"state": "within-capacity"},
                        "vtt_cue_count": 1 + sample_index,
                        "vtt_sha256": hashlib.sha256(
                            f"{channel}-{sample_index}".encode()
                        ).hexdigest(),
                        "playlist_age_seconds": 1.0,
                        "playlist_mtime_utc": (sample_at - timedelta(seconds=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "newest_segment": f"{channel}-{sample_index}.ts",
                    }
                )
            snapshots.append(
                _write_bound_json(
                    evidence_dir / f"host-runtime-{sample_index + 1}.json",
                    {
                        "utc": sample_at.isoformat().replace("+00:00", "Z"),
                        "health": {"status": "healthy", "version": VERSION},
                        "pinned_whistle_error_seen": False,
                        "whistle_active_seen": dict.fromkeys(
                            ("public", "government", "education"), True
                        ),
                        "whistle_fallback_seen": dict.fromkeys(
                            ("public", "government", "education"), False
                        ),
                        "channels": channels,
                    },
                )
            )
        host_runtime_result = _write_bound_json(
            evidence_dir / "host-runtime-result.json",
            {"result": "PASS", "channels": ["public", "government", "education"], "samples": 2},
        )
        receipt_path = tmp_path / "direct-consumer-evidence.json"
        receipt_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "civiccast-native-beta-direct-consumer-evidence",
                    "consumer_mode": "physical-host",
                    "artifact": {
                        "source_sha": source_sha,
                        "build_run_id": build_run_id,
                        "assembly_receipt": assembly_ref,
                    },
                    "evidence": {
                        "host_install": {
                            "receipt": host_install_ref,
                            "installed_manifest": manifest_ref,
                        },
                        "host_three_channel_runtime": {
                            "result": host_runtime_result,
                            "snapshots": snapshots,
                        },
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return receipt_path, setup

    beta11_state = {
        "installed_version": VERSION,
        "service_state": "Running",
        "health": {"status": "healthy", "version": VERSION},
        "receipt": {"product_version": VERSION},
    }
    beta11_activation = {
        "product_version": VERSION,
        "distribution_index_sha256": "c" * 64,
        "result": "passed",
    }
    beta10_state = {
        "installed_version": "1.0.0-beta.10",
        "service_state": "Running",
        "health": {"status": "healthy", "version": "1.0.0-beta.10"},
    }
    schedule_ids = ["schedule-1", "schedule-2", "schedule-3"]

    def install_proof(folder: str) -> dict[str, dict[str, str]]:
        root = evidence_dir / folder
        return {
            "installer_run": _write_bound_json(root / "installer-run.json", installer_run),
            "install_state": _write_bound_json(root / "install-state.json", beta11_state),
            "activation_self_test": _write_bound_json(
                root / "activation-self-test.json", beta11_activation
            ),
        }

    fresh = install_proof("FreshInstall")
    repair = install_proof("FailedInstallRepair")
    repair.update(
        {
            "fixture": _write_bound_json(
                evidence_dir / "repair-fixture.json",
                {
                    "previous_installed_version": VERSION,
                    "missing_runtime_key": "whistle_assets_root",
                    "installed_version_marker_removed": True,
                    "upgrade_journal_exists": False,
                    "service_status": "Stopped",
                },
            ),
            "repair_install_log": _write_bound_text(
                evidence_dir / "repair-install-command.log", "PASS: installer exit 0\n"
            ),
            "repair_verify_log": _write_bound_text(
                evidence_dir / "verify-repair-command.log",
                "PASS: preserved account, asset, and schedule IDs\n",
            ),
            "post_repair_result": _write_bound_json(
                evidence_dir / "Beta11" / "VerifyAfterRepair" / "result.json",
                {
                    "result": "PASS",
                    "login": "PASS",
                    "preserve_install_and_database": True,
                    "product_version": VERSION,
                    "health": {"status": "healthy", "version": VERSION},
                    "preserved_asset_id": "asset-repair-1",
                    "preserved_schedule_ids": schedule_ids,
                },
            ),
            "post_repair_marker": _write_bound_json(
                evidence_dir / "Beta11" / "VerifyAfterRepair" / "preserve-marker.json",
                {
                    "preserve_install_and_database": True,
                    "product_version": VERSION,
                    "preserved_baseline_asset_id": "asset-repair-1",
                    "schedule_ids": schedule_ids,
                    "runtime": {"whistle_assets_root": "packs/captions-whistle"},
                },
            ),
        }
    )
    baseline = {
        "installer_run": _write_bound_json(
            evidence_dir / "Beta10-Baseline-Install" / "installer-run.json",
            {
                "installer": "CivicCast (Native)_1.0.0-beta.10_x64-setup.exe",
                "sha256": "d" * 64,
                "exit_code": 0,
            },
        ),
        "install_state": _write_bound_json(
            evidence_dir / "Beta10-Baseline-Install" / "install-state.json", beta10_state
        ),
    }
    upgrade = {
        "installer_run": _write_bound_json(
            evidence_dir / "Beta10ToBeta11Upgrade" / "installer-run.json", installer_run
        ),
        "install_state": _write_bound_json(
            evidence_dir / "Beta10ToBeta11Upgrade" / "install-state.json", beta11_state
        ),
        "activation_self_test": _write_bound_json(
            evidence_dir / "Beta10ToBeta11Upgrade" / "activation-self-test.json", beta11_activation
        ),
        "upgrade_engine_log": _write_bound_text(
            evidence_dir / "Beta10ToBeta11Upgrade" / "upgrade-engine.log.tail.txt",
            "upgrade engine starting: old=1.0.0-beta.10 new=1.0.0-beta.11\nroute: upgrade\n",
        ),
    }
    verified = {
        "result": _write_bound_json(
            evidence_dir / "VerifyAfterUpgrade" / "result.json",
            {
                "result": "PASS",
                "login": "PASS",
                "preserve_install_and_database": True,
                "product_version": VERSION,
                "health": {"status": "healthy", "version": VERSION},
                "preserved_asset_id": "asset-baseline-1",
                "preserved_schedule_ids": schedule_ids,
            },
        ),
        "preserve_marker": _write_bound_json(
            evidence_dir / "VerifyAfterUpgrade" / "preserve-marker.json",
            {
                "preserve_install_and_database": True,
                "product_version": VERSION,
                "preserved_baseline_asset_id": "asset-baseline-1",
                "baseline_schedule_ids": schedule_ids,
                "runtime": {"whistle_assets_root": "packs/captions-whistle"},
            },
        ),
    }
    runtime_channels = (
        ("public",)
        if runtime_proof_scope == "one-channel-install-smoke"
        else ("public", "government", "education")
    )
    runtime_group = (
        "one_channel_install_smoke"
        if runtime_proof_scope == "one-channel-install-smoke"
        else "three_channel_runtime"
    )
    runtime_root = evidence_dir / (
        "OnePublicInstallSmoke"
        if runtime_proof_scope == "one-channel-install-smoke"
        else "AllThreeAfterReporterFix"
    )
    runtime = {
        "result": _write_bound_json(
            runtime_root / "result.json",
            {
                "result": "PASS",
                "channels": list(runtime_channels),
                "observed_minutes": 5,
                "preserve_install_and_database": True,
            },
        ),
        "preserve_marker": _write_bound_json(
            runtime_root / "preserve-marker.json",
            {"preserve_install_and_database": True, "product_version": VERSION},
        ),
        "snapshots": [],
    }
    sample_start = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)
    for minute in range(1, 6):
        sampled_at = sample_start + timedelta(minutes=minute - 1)
        sampled_at_text = sampled_at.isoformat().replace("+00:00", "Z")
        playlist_mtime_text = (sampled_at - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        channels = []
        for channel_index, channel in enumerate(runtime_channels):
            vtt_text = f"WEBVTT\n\n{channel} fellow Americans\n"
            channels.append(
                {
                    "id": channel,
                    "vtt_sha256": hashlib.sha256(f"{channel}-{minute}".encode()).hexdigest(),
                    "vtt_text_snapshot": vtt_text,
                    "vtt_text_snapshot_utf8_bytes": len(vtt_text.encode("utf-8")),
                    "state": {"state": "ON_AIR"},
                    "ffprobe_streams": [
                        {"codec_type": "video", "codec_name": "h264"},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ],
                    "caption_runtime_status": {"state": "within-capacity"},
                    "vtt_cue_count": 1,
                    "playlist_age_seconds": 1.0,
                    "playlist_mtime_utc": playlist_mtime_text,
                    "segment_count": 6,
                    "newest_segment": f"seg{minute:06d}{channel_index}.ts",
                    "expected_jfk_words_seen": {"fellow": True, "americans": True, "country": True},
                }
            )
        runtime["snapshots"].append(
            _write_bound_json(
                runtime_root / f"minute-{minute}.json",
                {
                    "utc": sampled_at_text,
                    "minute": minute,
                    "health": {"status": "healthy", "version": VERSION},
                    "pinned_whistle_error_seen": False,
                    "whistle_active_seen": dict.fromkeys(runtime_channels, True),
                    "whistle_fallback_seen": dict.fromkeys(runtime_channels, False),
                    "channels": channels,
                },
            )
        )

    receipt = {
        "schema_version": 1,
        "kind": "civiccast-native-beta-direct-consumer-evidence",
        "artifact": {
            "source_sha": source_sha,
            "build_run_id": build_run_id,
            "assembly_receipt": assembly_ref,
        },
        "evidence": {
            "fresh_install": fresh,
            "failed_install_repair": repair,
            "beta10_baseline_install": baseline,
            "beta10_to_beta11_upgrade": upgrade,
            "verify_after_upgrade": verified,
            runtime_group: runtime,
        },
    }
    if runtime_proof_scope is not None:
        receipt["runtime_proof_scope"] = runtime_proof_scope
    receipt_path = tmp_path / "direct-consumer-evidence.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt_path, setup


def _direct_args(
    tmp_path: Path,
    kit_dir: Path,
    receipt: Path,
    *,
    dry_run: bool = True,
    repo_root: Path | None = None,
) -> list[str]:
    argv = _args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root)
    receipt_doc = json.loads(receipt.read_text(encoding="utf-8"))
    build_run_id = str(receipt_doc["artifact"]["build_run_id"])
    build_arg = argv.index("--build-run-id")
    argv[build_arg + 1] = build_run_id
    gate_arg = argv.index("--gate-a-run-id")
    del argv[gate_arg : gate_arg + 2]
    argv.extend(
        ["--artifact-source-sha", DIRECT_SOURCE_SHA, "--consumer-evidence-receipt", str(receipt)]
    )
    if dry_run:
        argv.append("--dry-run")
    return argv


# ---------------------------------------------------------------------------
# (a) layout
# ---------------------------------------------------------------------------
def test_direct_consumer_evidence_dry_run_names_producer_and_tag_target(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(tmp_path, kit_dir)
    fake = _fake_command_factory()
    monkeypatch.setattr(m, "run_command", fake)

    rc = m.main(_direct_args(tmp_path, kit_dir, receipt_path, repo_root=repo_root))

    assert rc == 0
    notes = (repo_root / "artifacts" / "release" / TAG / "RELEASE-NOTES.md").read_text(
        encoding="utf-8"
    )
    assert f"Artifact producer commit: {DIRECT_SOURCE_SHA}" in notes
    assert f"Tag target commit: {SOURCE_SHA}" in notes
    assert "fresh beta 11 install" in notes.lower()
    assert "Beta 10 to Beta 11 setup-only upgrade" in notes
    assert "three-channel" in notes.lower() and "five minutes" in notes.lower()
    assert "Gate A workflow lanes: not run" in notes
    assert "download-only network route: not tested" in notes.lower()
    assert not _gh_calls(fake.calls, "gh", "run", "download")
    assert not _gh_calls(fake.calls, "gh", "release")
    assert (repo_root / "artifacts" / "release" / TAG / "assets" / "setup.exe").is_file()


def test_direct_one_channel_install_smoke_is_explicit_and_does_not_claim_capacity(
    tmp_path, monkeypatch
):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(
        tmp_path, kit_dir, runtime_proof_scope="one-channel-install-smoke"
    )
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    assert m.main(_direct_args(tmp_path, kit_dir, receipt_path, repo_root=repo_root)) == 0

    notes = (repo_root / "artifacts" / "release" / TAG / "RELEASE-NOTES.md").read_text(
        encoding="utf-8"
    )
    assert "one-channel install-smoke" in notes.lower()
    assert "three-channel capacity unproven" in notes.lower()


@pytest.mark.parametrize("previous_version", ("1.0.0-beta.9", VERSION))
def test_direct_physical_host_install_uses_host_evidence_without_sandbox_claims(
    tmp_path, monkeypatch, previous_version
):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(
        tmp_path, kit_dir, consumer_mode="physical-host", previous_version=previous_version
    )
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    assert m.main(_direct_args(tmp_path, kit_dir, receipt_path, repo_root=repo_root)) == 0

    notes = (repo_root / "artifacts" / "release" / TAG / "RELEASE-NOTES.md").read_text(
        encoding="utf-8"
    )
    assert "Physical-host consumer verification" in notes
    assert "in-place update on an existing host" in notes.lower()
    assert "three-channel host output" in notes.lower()
    assert "not a three-channel capacity claim" in notes.lower()
    assert "direct sandbox consumer checks passed" not in notes.lower()
    assert "accepted development-station soak is reported separately" in notes.lower()
    assert "Three-channel Whistle/HLS/caption observation" not in notes


def test_direct_physical_host_accepts_runtime_status_without_channel_state(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(
        tmp_path, kit_dir, consumer_mode="physical-host"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for snapshot_ref in receipt["evidence"]["host_three_channel_runtime"]["snapshots"]:
        snapshot_path = Path(snapshot_ref["path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        for channel in snapshot["channels"]:
            channel.pop("state")
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        snapshot_ref["sha256"] = m.sha256_file(snapshot_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    assert m.main(_direct_args(tmp_path, kit_dir, receipt_path, repo_root=repo_root)) == 0


@pytest.mark.parametrize(
    "tamper", ["wrong-source", "wrong-manifest-source", "stale-output", "contradictory-state"]
)
def test_direct_physical_host_refuses_unbound_or_stale_evidence(tmp_path, monkeypatch, tamper):
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(
        tmp_path, kit_dir, consumer_mode="physical-host"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    evidence = receipt["evidence"]
    install_ref = evidence["host_install"]["receipt"]
    install_path = Path(install_ref["path"])
    install = json.loads(install_path.read_text(encoding="utf-8"))
    manifest_ref = evidence["host_install"]["installed_manifest"]
    manifest_path = Path(manifest_ref["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "wrong-source":
        install["source_sha"] = "f" * 40
        install_path.write_text(json.dumps(install, indent=2) + "\n", encoding="utf-8")
        install_ref["sha256"] = m.sha256_file(install_path)
    elif tamper == "wrong-manifest-source":
        manifest["civiccast"]["source_state"]["head"] = "f" * 40
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest_ref["sha256"] = m.sha256_file(manifest_path)
        install["after"]["app_payload_manifest_sha256"] = manifest_ref["sha256"]
        install_path.write_text(json.dumps(install, indent=2) + "\n", encoding="utf-8")
        install_ref["sha256"] = m.sha256_file(install_path)
    elif tamper == "stale-output":
        snapshots = evidence["host_three_channel_runtime"]["snapshots"]
        first_ref, second_ref = snapshots
        first_path = Path(first_ref["path"])
        second_path = Path(second_ref["path"])
        first = json.loads(first_path.read_text(encoding="utf-8"))
        second = json.loads(second_path.read_text(encoding="utf-8"))
        second["channels"][0]["vtt_sha256"] = first["channels"][0]["vtt_sha256"]
        second_path.write_text(json.dumps(second, indent=2) + "\n", encoding="utf-8")
        second_ref["sha256"] = m.sha256_file(second_path)
    else:
        snapshot_ref = evidence["host_three_channel_runtime"]["snapshots"][1]
        snapshot_path = Path(snapshot_ref["path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["channels"][0]["state"] = {"state": "STOPPED"}
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        snapshot_ref["sha256"] = m.sha256_file(snapshot_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    fake = _fake_command_factory()
    monkeypatch.setattr(m, "run_command", fake)

    assert m.main(_direct_args(tmp_path, kit_dir, receipt_path, dry_run=False)) == 1
    _assert_no_tag_or_public_release(fake.calls)


@pytest.mark.parametrize(
    "tamper",
    [
        "unknown-scope",
        "wrong-runtime-group",
        "missing-public-channel",
        "wrong-channel",
        "short-snapshot-list",
        "failed-runtime",
        "whistle-primary-lost",
        "whistle-fallback-seen",
        "degraded-caption-runtime",
    ],
)
def test_direct_one_channel_install_smoke_refuses_incomplete_or_failed_evidence(
    tmp_path, monkeypatch, tamper
):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(
        tmp_path, kit_dir, runtime_proof_scope="one-channel-install-smoke"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if tamper == "unknown-scope":
        receipt["runtime_proof_scope"] = "arbitrary-subset"
    elif tamper == "wrong-runtime-group":
        receipt["evidence"]["three_channel_runtime"] = receipt["evidence"].pop(
            "one_channel_install_smoke"
        )
    elif tamper == "short-snapshot-list":
        receipt["evidence"]["one_channel_install_smoke"]["snapshots"].pop()
    else:
        runtime = receipt["evidence"]["one_channel_install_smoke"]
        if tamper == "failed-runtime":
            ref = runtime["result"]
            result_path = Path(ref["path"])
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["result"] = "FAIL"
            result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            ref["sha256"] = m.sha256_file(result_path)
        else:
            ref = runtime["snapshots"][0]
            snapshot_path = Path(ref["path"])
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if tamper == "missing-public-channel":
                runtime["result"] = _write_bound_json(
                    snapshot_path.parent / "result.json",
                    {
                        "result": "PASS",
                        "channels": [],
                        "observed_minutes": 5,
                        "preserve_install_and_database": True,
                    },
                )
            elif tamper == "wrong-channel":
                result_ref = runtime["result"]
                result_path = Path(result_ref["path"])
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result["channels"] = ["government"]
                result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                result_ref["sha256"] = m.sha256_file(result_path)
            elif tamper == "whistle-primary-lost":
                snapshot["whistle_active_seen"]["public"] = False
                snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
                ref["sha256"] = m.sha256_file(snapshot_path)
            elif tamper == "whistle-fallback-seen":
                snapshot["whistle_fallback_seen"]["public"] = True
                snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
                ref["sha256"] = m.sha256_file(snapshot_path)
            elif tamper == "degraded-caption-runtime":
                snapshot["channels"][0]["caption_runtime_status"]["state"] = "overloaded"
                snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
                ref["sha256"] = m.sha256_file(snapshot_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    fake = _fake_command_factory(mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)

    assert (
        m.main(_direct_args(tmp_path, kit_dir, receipt_path, dry_run=False, repo_root=repo_root))
        == 1
    )
    assert not _gh_calls(fake.calls, "gh", "release")


@pytest.mark.parametrize("tamper", ["source", "hash", "proof"])
def test_direct_evidence_refusals_happen_before_remote_mutation(tmp_path, monkeypatch, tamper):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(tmp_path, kit_dir)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if tamper == "source":
        receipt["artifact"]["source_sha"] = SOURCE_SHA
    elif tamper == "hash":
        evidence_path = Path(receipt["evidence"]["fresh_install"]["install_state"]["path"])
        evidence_path.write_text("{}\n", encoding="utf-8")
    else:
        del receipt["evidence"]["three_channel_runtime"]
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    fake = _fake_command_factory(mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)

    rc = m.main(_direct_args(tmp_path, kit_dir, receipt_path, dry_run=False, repo_root=repo_root))

    assert rc == 1
    assert _gh_calls(fake.calls, "gh", "auth", "status")
    assert not _gh_calls(fake.calls, "gh", "run", "download")
    assert not _gh_calls(fake.calls, "gh", "release")
    assert not (repo_root / "artifacts" / "release" / TAG / "RELEASE-NOTES.md").exists()


def test_direct_runtime_rejects_stale_hls_before_remote_mutation(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(tmp_path, kit_dir)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    snapshot_ref = receipt["evidence"]["three_channel_runtime"]["snapshots"][0]
    snapshot_path = Path(snapshot_ref["path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["channels"][0]["playlist_age_seconds"] = 90.0
    snapshot["channels"][0]["playlist_mtime_utc"] = "2026-10-08T03:58:30Z"
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    snapshot_ref["sha256"] = m.sha256_file(snapshot_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    fake = _fake_command_factory(mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)

    assert (
        m.main(_direct_args(tmp_path, kit_dir, receipt_path, dry_run=False, repo_root=repo_root))
        == 1
    )
    assert not _gh_calls(fake.calls, "gh", "release")


def test_direct_runtime_accepts_two_accumulated_jfk_words_per_channel(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "direct-kit"
    receipt_path, _ = _write_direct_consumer_receipt(tmp_path, kit_dir)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for index, snapshot_ref in enumerate(receipt["evidence"]["three_channel_runtime"]["snapshots"]):
        snapshot_path = Path(snapshot_ref["path"])
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        for channel in snapshot["channels"]:
            channel["expected_jfk_words_seen"] = {
                "fellow": True,
                "americans": index >= 1,
                "country": False,
            }
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        snapshot_ref["sha256"] = m.sha256_file(snapshot_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    assert m.main(_direct_args(tmp_path, kit_dir, receipt_path, repo_root=repo_root)) == 0


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


def test_quoted_kit_path_stays_literal_and_bad_signature_refuses_before_mutation(
    tmp_path, monkeypatch
):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "O'Hare kit"
    _write_kit(kit_dir)
    fake = _fake_command_factory(signature_status="HashMismatch")
    monkeypatch.setattr(m, "run_command", fake)

    assert m.main(_args(tmp_path, kit_dir, repo_root=repo_root)) == 1

    literal_path = str(kit_dir / "setup.exe").replace("'", "''")
    powershell_scripts = [call[-1] for call in fake.calls if call[0] == "powershell"]
    assert powershell_scripts == [
        f"(Get-Item -LiteralPath '{literal_path}').VersionInfo.ProductVersion",
        f"(Get-AuthenticodeSignature -LiteralPath '{literal_path}').Status",
    ]
    assert not _gh_calls(fake.calls, "gh", "run", "download")
    assert not _gh_calls(fake.calls, "gh", "release")


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
            build_run_id="111",
            dest_dir=tmp_path / "gate-a",
        )


def test_gate_a_artifact_name_uses_build_run_id_not_gate_a_run_id(tmp_path, monkeypatch):
    """Regression: gate-a-station-acceptance.yml's uploaded artifact names
    are suffixed with the BUILD run id (github.event.inputs.run_id), not the
    Gate A workflow's own run id -- confirmed live on Gate A run 33713004718
    validating build 33711079441, whose artifacts are named
    gate-a-verdict-33711079441 etc, never *-33713004718. A distinct
    gate_a_run_id must still select which run's artifacts `gh run download`
    fetches from, but must NOT be used to format the artifact name."""

    fake = _fake_command_factory()
    monkeypatch.setattr(m, "run_command", fake)
    verdicts = m.download_gate_a_verdicts(
        repository="scottconverse/civiccast-native",
        gate_a_run_id="222",
        build_run_id="111",
        dest_dir=tmp_path / "gate-a",
    )
    assert set(verdicts) == set(m.GATE_A_LANES)
    download_calls = _gh_calls(fake.calls, "gh", "run", "download")
    assert len(download_calls) == len(m.GATE_A_LANES)
    for call in download_calls:
        # gh run download <run-id> ... selects the Gate A run, not the build run.
        assert call[3] == "222"
        artifact_name = call[call.index("-n") + 1]
        assert artifact_name.endswith("111")


def test_gate_a_repeated_downloads_archive_fresh_attempts(tmp_path, monkeypatch):
    """A repeated dry-run/live preparation must never overwrite old proofs."""
    base_fake = _fake_command_factory()

    def refusing_fake(cmd, **kwargs):
        if cmd[:3] == ["gh", "run", "download"]:
            destination = Path(cmd[cmd.index("-D") + 1])
            assert not (destination / "gate-a-verdict.json").exists()
        return base_fake(cmd, **kwargs)

    monkeypatch.setattr(m, "run_command", refusing_fake)
    destination = tmp_path / "gate-a-verdicts"
    first = m.download_gate_a_verdicts(
        repository="scottconverse/civicast-native",
        gate_a_run_id="222",
        build_run_id="111",
        dest_dir=destination,
    )
    second = m.download_gate_a_verdicts(
        repository="scottconverse/civicast-native",
        gate_a_run_id="222",
        build_run_id="111",
        dest_dir=destination,
    )

    assert set(first) == set(second) == set(m.GATE_A_LANES)
    assert {doc["source_sha"] for doc in first.values()} == {SOURCE_SHA}
    assert {doc["source_sha"] for doc in second.values()} == {SOURCE_SHA}
    download_calls = _gh_calls(base_fake.calls, "gh", "run", "download")
    destinations = [Path(call[call.index("-D") + 1]) for call in download_calls]
    assert len(destinations) == 2 * len(m.GATE_A_LANES)
    assert len({path.parents[0] for path in destinations}) == 2
    assert all(path.name in m.GATE_A_LANES for path in destinations)


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


def test_gate_a_dirty_artifact_reporting_download_only_lane_refuses():
    verdicts = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    verdicts["dirty"]["lane"] = "download-only"
    with pytest.raises(
        m.PublishError, match=r"lane 'dirty' verdict document reports lane 'download-only'"
    ):
        m.verify_gate_a_verdicts(verdicts, source_sha=SOURCE_SHA)


def test_gate_a_download_only_artifact_reporting_dirty_lane_refuses():
    verdicts = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    verdicts["download-only"]["lane"] = "dirty"
    with pytest.raises(
        m.PublishError, match=r"lane 'download-only' verdict document reports lane 'dirty'"
    ):
        m.verify_gate_a_verdicts(verdicts, source_sha=SOURCE_SHA)


def test_end_to_end_lane_mismatch_refuses_with_no_tag_or_release(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    docs = {lane: _gate_a_doc(lane=lane) for lane in m.GATE_A_LANES}
    docs["dirty"]["lane"] = "download-only"
    fake = _fake_command_factory(gate_a_docs=docs, mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    assert not _gh_calls(fake.calls, "gh", "release", "create")
    _assert_no_tag_or_public_release(fake.calls)


# ---------------------------------------------------------------------------
# pre-flight: gh auth, 2 GiB cap
# ---------------------------------------------------------------------------
def test_gh_auth_failure_refuses_before_anything_else(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    fake = _fake_command_factory(gh_auth_fails=True)
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    # The auth probe must be the ONLY thing that ran.
    assert fake.calls == [["gh", "auth", "status"]]


def test_gh_auth_failure_message_is_specific(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(gh_auth_fails=True))
    with pytest.raises(m.PublishError, match=r"gh is not authenticated .*gh auth login"):
        m.verify_gh_auth()


def test_preflight_refuses_asset_at_or_above_limit(tmp_path, monkeypatch):
    big = tmp_path / "native-server-binaries.ccpack"
    big.write_bytes(b"x" * 16)
    small = tmp_path / "setup.exe"
    small.write_bytes(b"x" * 4)
    monkeypatch.setattr(m, "GITHUB_ASSET_LIMIT_BYTES", 16)
    with pytest.raises(
        m.PublishError,
        match=r"2 GiB.*refusing before any remote mutation.*native-server-binaries\.ccpack",
    ):
        m.preflight_asset_limits([small, big])


def test_preflight_limit_is_githubs_documented_2_gib():
    assert m.GITHUB_ASSET_LIMIT_BYTES == 2 * 1024**3


def test_end_to_end_oversize_asset_refuses_before_any_remote_mutation(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    (kit_dir / "packs" / "native-server-binaries.ccpack").write_bytes(b"x" * 64)
    monkeypatch.setattr(m, "GITHUB_ASSET_LIMIT_BYTES", 64)
    fake = _fake_command_factory(mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    assert not _gh_calls(fake.calls, "gh", "release")  # no create/view/edit/delete at all
    _assert_no_tag_or_public_release(fake.calls)


# ---------------------------------------------------------------------------
# (f) draft -> verify -> un-draft; every failure leaves no tag / no release
# ---------------------------------------------------------------------------
def test_draft_asset_size_mismatch_deletes_draft_and_refuses(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")  # 5 bytes locally
    fake = _fake_command_factory(gh_release_view_assets=[{"name": "setup.exe", "size": 999}])
    monkeypatch.setattr(m, "run_command", fake)
    with pytest.raises(m.PublishError, match=r"draft deleted, no tag created.*size mismatch"):
        m.verify_draft_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )
    assert _gh_calls(fake.calls, "gh", "release", "delete") == [
        ["gh", "release", "delete", TAG, "-R", "scottconverse/civiccast-native", "--yes"]
    ]
    _assert_no_tag_or_public_release(fake.calls)


def test_draft_missing_asset_deletes_draft_and_refuses(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")
    fake = _fake_command_factory(gh_release_view_assets=[])
    monkeypatch.setattr(m, "run_command", fake)
    with pytest.raises(m.PublishError, match=r"draft deleted.*missing asset 'setup\.exe'"):
        m.verify_draft_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )
    assert _gh_calls(fake.calls, "gh", "release", "delete")
    _assert_no_tag_or_public_release(fake.calls)


def test_draft_that_is_not_a_draft_refuses(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")
    fake = _fake_command_factory(
        gh_release_view_assets=[{"name": "setup.exe", "size": 5}], gh_release_view_is_draft=False
    )
    monkeypatch.setattr(m, "run_command", fake)
    with pytest.raises(m.PublishError, match=r"not a draft"):
        m.verify_draft_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )


def test_draft_delete_failure_is_reported_loudly(tmp_path, monkeypatch):
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"12345")
    fake = _fake_command_factory(gh_release_view_assets=[], gh_release_delete_fails=True)
    monkeypatch.setattr(m, "run_command", fake)
    with pytest.raises(m.PublishError, match=r"DRAFT DELETE FAILED -- remove it by hand"):
        m.verify_draft_assets(
            repository="scottconverse/civiccast-native", tag=TAG, asset_paths=[asset]
        )


def test_end_to_end_gh_release_create_failure_refuses_and_cleans_up(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    fake = _fake_command_factory(gh_release_create_fails=True)
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    create = _gh_calls(fake.calls, "gh", "release", "create")
    assert len(create) == 1 and "--draft" in create[0] and "--target" in create[0]
    assert _gh_calls(fake.calls, "gh", "release", "delete")  # best-effort cleanup ran
    assert not _gh_calls(fake.calls, "gh", "release", "view")
    _assert_no_tag_or_public_release(fake.calls)
    truth = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert TAG not in truth


def test_gh_release_create_failure_message_is_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(gh_release_create_fails=True))
    notes = tmp_path / "notes.md"
    notes.write_text("x", encoding="utf-8")
    with pytest.raises(
        m.PublishError,
        match=r"gh release create \(draft\) failed .*draft deleted.*no tag was created",
    ):
        m.create_draft_release(
            repository="scottconverse/civiccast-native",
            tag=TAG,
            source_sha=SOURCE_SHA,
            title="t",
            notes_file=notes,
            asset_paths=[],
        )


def test_end_to_end_draft_verify_mismatch_deletes_draft_no_undraft(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    fake = _fake_command_factory(gh_release_view_assets=[{"name": "setup.exe", "size": 1}])
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    assert _gh_calls(fake.calls, "gh", "release", "create")
    assert _gh_calls(fake.calls, "gh", "release", "delete")
    _assert_no_tag_or_public_release(fake.calls)
    truth = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert TAG not in truth


def test_undraft_failure_leaves_draft_and_refuses(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    fake = _fake_command_factory(mirror_uploaded_assets=True, gh_release_edit_fails=True)
    monkeypatch.setattr(m, "run_command", fake)
    rc = m.main(_args(tmp_path, kit_dir, dry_run=False, repo_root=repo_root))
    assert rc == 1
    # Un-draft may have partially applied: the draft is NOT deleted here.
    assert not _gh_calls(fake.calls, "gh", "release", "delete")
    truth = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert TAG not in truth


def test_undraft_failure_message_is_specific(monkeypatch):
    monkeypatch.setattr(m, "run_command", _fake_command_factory(gh_release_edit_fails=True))
    with pytest.raises(m.PublishError, match=r"--draft=false failed .*left in place"):
        m.undraft_release(repository="scottconverse/civiccast-native", tag=TAG)


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
    for path in [
        setup,
        kit_dir / "packs" / "native-app-payload.ccpack",
        kit_dir / "packs" / "native-server-binaries.ccpack",
        *(
            kit_dir / "manual" / name
            for name in (
                PDF_FILENAME,
                DOCX_FILENAME,
                MANIFEST_FILENAME,
                "candidate-manual-receipt.json",
            )
        ),
    ]:
        assert m.sha256_file(path) in notes
        assert f"{m.sha256_file(path)}  {path.name}" in sums
    # The asset table must also list SHA256SUMS.txt and the sidecar, with
    # their real hashes.
    assert (
        f"| SHA256SUMS.txt | {len(sums.encode()):,} bytes | {m.sha256_file(out_dir / 'SHA256SUMS.txt')} |"
        in notes
    )
    assert f"| {setup.name}.sidecar.json |" in notes
    assert m.sha256_file(out_dir / f"{setup.name}.sidecar.json") in notes
    assert "beta candidate, not a production release" in notes.lower()
    assert "download setup.exe" in notes.lower() or "download `setup.exe`" in notes.lower()
    assert "verify the exact sha-256" in notes.lower()
    assert "warning alone proves neither signature failure nor a valid publisher" in notes.lower()
    assert "missing, or the publisher/hash differs, stop" in notes.lower()

    # dry run must not have touched the real release-truth.yaml on disk
    # (only via update_release_truth called on a scratch copy for the summary)
    truth_text = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(
        encoding="utf-8"
    )
    assert TAG not in truth_text


def test_beta11_refuses_to_publish_without_candidate_manual_bundle(tmp_path, monkeypatch, capsys):
    """Beta 11 release assets must include the exact build's rendered manual."""
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir, with_manual=False)
    fake = _fake_command_factory()
    monkeypatch.setattr(m, "run_command", fake)

    rc = m.main(_args(tmp_path, kit_dir, dry_run=True, repo_root=repo_root))

    assert rc == 1
    assert "manual" in capsys.readouterr().err.lower()
    assert not _gh_calls(fake.calls, "gh", "run", "download"), (
        "missing manual must fail before fetching Gate A or attempting publication"
    )
    assert not _gh_calls(fake.calls, "gh", "release", "create")

    # no git/gh mutating calls were made
    calls = m.run_command.calls
    assert not _gh_calls(calls, "gh", "release")
    _assert_no_tag_or_public_release(calls)


def test_beta11_refuses_manual_bytes_that_do_not_match_the_candidate_receipt(
    tmp_path, monkeypatch, capsys
):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    with (kit_dir / "manual" / PDF_FILENAME).open("ab") as handle:
        handle.write(b"tampered")
    fake = _fake_command_factory()
    monkeypatch.setattr(m, "run_command", fake)

    rc = m.main(_args(tmp_path, kit_dir, dry_run=True, repo_root=repo_root))

    assert rc == 1
    assert "manual" in capsys.readouterr().err.lower()
    assert not _gh_calls(fake.calls, "gh", "run", "download")
    assert not _gh_calls(fake.calls, "gh", "release")
    _assert_no_tag_or_public_release(fake.calls)


def test_dry_run_with_current_status_does_not_touch_real_file(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    _write_kit(kit_dir)
    monkeypatch.setattr(m, "run_command", _fake_command_factory())

    argv = _args(tmp_path, kit_dir, truth_status="current", repo_root=repo_root)
    rc = m.main(argv)
    assert rc == 0

    truth_text = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(
        encoding="utf-8"
    )
    assert "current: v1.0.0-beta.1" in truth_text  # unchanged


# ---------------------------------------------------------------------------
# live (non-dry-run) happy path -- fully faked, exercises the wiring only
# ---------------------------------------------------------------------------
def test_live_publish_draft_verify_undraft_order_and_release_truth(tmp_path, monkeypatch):
    repo_root = _base_repo_root(tmp_path)
    kit_dir = tmp_path / "kit"
    setup = _write_kit(kit_dir)
    fake = _fake_command_factory(mirror_uploaded_assets=True)
    monkeypatch.setattr(m, "run_command", fake)

    rc = m.main(
        _args(tmp_path, kit_dir, dry_run=False, truth_status="current", repo_root=repo_root)
    )
    assert rc == 0

    calls = fake.calls
    assert not any(c[0] == "git" for c in calls)  # no manual tag, ever
    create = _gh_calls(calls, "gh", "release", "create")[0]
    assert "--draft" in create and create[create.index("--target") + 1] == SOURCE_SHA
    assert "--prerelease" in create
    uploaded = create[create.index("--notes-file") + 2 :]
    assert [Path(p).name for p in uploaded] == [
        setup.name,
        "native-app-payload.ccpack",
        "native-server-binaries.ccpack",
        PDF_FILENAME,
        DOCX_FILENAME,
        MANIFEST_FILENAME,
        "candidate-manual-receipt.json",
        "SHA256SUMS.txt",
        f"{setup.name}.sidecar.json",
    ]
    view = _gh_calls(calls, "gh", "release", "view")[0]
    assert "assets,isDraft" in view
    edit = _gh_calls(calls, "gh", "release", "edit")[0]
    assert "--draft=false" in edit
    assert not _gh_calls(calls, "gh", "release", "delete")
    # Order: create -> view -> edit
    order = [c[2] for c in _gh_calls(calls, "gh", "release")]
    assert order == ["create", "view", "edit"]

    truth = (repo_root / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
    assert f"current: {TAG}" in truth
    assert f"superseded_by: {TAG}" in truth


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
    changelog = "# Changelog\n\n## [Unreleased]\n\nSome new stuff.\n\n## [1.0.0-beta.1] - 2026-08-01\n\nOld stuff.\n"
    section = m.extract_changelog_unreleased(changelog)
    assert "Some new stuff." in section
    assert "Old stuff." not in section


def test_extract_changelog_unreleased_missing_section_returns_empty():
    assert m.extract_changelog_unreleased("# Changelog\n\nNo sections here.\n") == ""


def test_asset_naming_constants_are_the_contract():
    """The downloader's NativeCandidate mode pins its literals against these."""
    assert m.SETUP_ASSET_NAME == "setup.exe"
    assert m.SHA256SUMS_ASSET_NAME == "SHA256SUMS.txt"
    assert m.SIDECAR_SUFFIX == ".sidecar.json"
    assert m.PACK_SUFFIX == ".ccpack"

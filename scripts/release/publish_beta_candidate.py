#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish a native-Windows beta-candidate release.

Owner decision 2026-09-02: the coordinating agent cuts beta-candidate
releases going forward. Every green build gets tagged and published on the
PUBLIC repo ``scottconverse/civiccast-native`` as a GitHub pre-release,
because the beta tester (Sergio, "LPM") checks GitHub daily for new
versions. The existing ``v1.0.0-beta.1`` release has NO assets (it was
USB-delivered). GitHub release assets are capped at 2 GB/file; the ~21 GB
AI-model bundle (the ``station\\`` directory in the kit) therefore never
goes on a release -- with PRs #127/#126 merged, the installer reuses AI
models already on the machine (upgrade case) or the USB bundle (first-install
case). Runtime packs are each under 2 GB and DO go on the release.

Every step below is fail-closed: any check failure refuses (raises
``PublishError``, printed and exit 1) before doing anything past that point.
Nothing here ever merges, tags, or publishes anything on this agent's own
initiative outside of what this script's caller explicitly invoked it to do
-- see the module docstring boundary at the bottom of this file's ``main``
for the ``--dry-run`` vs live distinction.

Usage::

    python scripts/release/publish_beta_candidate.py \\
        --kit-dir C:\\CivicCastTester\\kit-staging\\<sha> \\
        --source-sha <tag-target-sha> \\
        [--artifact-source-sha <package-producer-sha>] \\
        --build-run-id <id> \\
        (--gate-a-run-id <id> | --consumer-evidence-receipt <file>) \\
        --tag v1.0.0-beta.N \\
        [--dry-run] \\
        --truth-status current|staging

``--dry-run`` writes the rendered notes, sidecar, and SHA256SUMS.txt to
``artifacts/release/<tag>/`` and touches no GitHub or git remote state at
all -- no tag, no push, no mutating ``gh`` call. Without ``--dry-run`` it
publishes in an order that can never leave an orphan tag: pre-flight every
asset under GitHub's 2 GiB cap, create the release as a DRAFT targeting
``--source-sha`` with all assets (a draft has no tag), verify every asset's
name and size on the fetched draft (deleting the draft on any mismatch),
then un-draft it -- the one step that creates the public tag, atomically
with its release -- and finally update ``docs/releases/release-truth.yaml``.
No ``git tag``/``git push`` is ever run by hand.
``--source-sha`` is the release tag target. ``--artifact-source-sha`` binds
the producer commit for the build, manual, and consumer evidence; it defaults
to ``--source-sha`` in workflow mode and is required in direct-evidence mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.release.candidate_manual import (  # noqa: E402
    CandidateManualError,
    manual_required_for_version,
    verify_candidate_manual,
)
from scripts.render_release_notes import render_native_beta_candidate_notes  # noqa: E402

DEFAULT_REPOSITORY = "scottconverse/civiccast-native"
# GitHub's documented per-file release-asset cap is 2 GiB
# (docs.github.com "Managing releases in a repository": "Each file included
# in a release must be under 2 GiB"). Enforced as a pre-flight BEFORE any
# remote mutation so a >= 2 GiB pack can never surface as a half-created
# release.
GITHUB_ASSET_LIMIT_BYTES = 2 * 1024**3
# Release asset naming contract. scripts/download_windows_release_artifacts.ps1's
# NativeCandidate mode and tests/policy/test_windows_release_downloader.py pin
# the downloader's literals against THESE constants so the two cannot drift.
SETUP_ASSET_NAME = "setup.exe"
SHA256SUMS_ASSET_NAME = "SHA256SUMS.txt"
SIDECAR_SUFFIX = ".sidecar.json"
PACK_SUFFIX = ".ccpack"
GATE_A_LANES: tuple[str, ...] = ("clean", "dirty", "download-only")
GATE_A_ARTIFACT_NAMES: dict[str, str] = {
    "clean": "gate-a-verdict-{run_id}",
    "dirty": "gate-a-dirty-verdict-{run_id}",
    "download-only": "gate-a-download-only-verdict-{run_id}",
}

SMARTSCREEN_NOTE = (
    'Before responding to any blue "Windows protected your PC" SmartScreen '
    "warning, verify the exact SHA-256 and that Get-AuthenticodeSignature "
    "reports Status Valid for publisher Scott Converse. A warning alone proves "
    "neither signature failure nor a valid publisher; if the expected More info "
    "or Run anyway options are missing, or the publisher/hash differs, stop. "
    "SmartScreen reputation is separate from Authenticode validity and may vary."
)


class PublishError(RuntimeError):
    """A fail-closed refusal. The caller prints this and exits nonzero."""


# ---------------------------------------------------------------------------
# Injectable process runner. Tests monkeypatch this single seam to fake every
# `gh`, `git`, and PowerShell subprocess call without touching the network or
# a real git remote.
# ---------------------------------------------------------------------------
def run_command(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    child_env = os.environ.copy()
    for name in list(child_env):
        if name.casefold() == "psmodulepath":
            del child_env[name]
    return run_command(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=child_env,
    )


def run_gh(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run_command(["gh", *args], **kwargs)


# ---------------------------------------------------------------------------
# (a) Layout + version verification
# ---------------------------------------------------------------------------
def verify_layout(
    kit_dir: Path, *, setup_filename: str = SETUP_ASSET_NAME
) -> tuple[Path, list[Path]]:
    """Require setup.exe, packs\\*.ccpack (>=1), and a station\\ dir.

    Matches what .github/workflows/native-beta-candidate-artifacts.yml says
    a kit at C:\\CivicCastTester\\kit-staging\\<sha>\\ contains.
    """

    if not kit_dir.is_dir():
        raise PublishError(f"kit-dir does not exist or is not a directory: {kit_dir}")

    setup = kit_dir / setup_filename
    if not setup.is_file():
        raise PublishError(f"kit-dir is missing {setup_filename}: {setup}")

    packs_dir = kit_dir / "packs"
    if not packs_dir.is_dir():
        raise PublishError(f"kit-dir is missing a packs\\ directory: {packs_dir}")
    packs = sorted(packs_dir.glob(f"*{PACK_SUFFIX}"))
    if not packs:
        raise PublishError(f"packs\\ directory has no *.ccpack files: {packs_dir}")

    station_dir = kit_dir / "station"
    if not station_dir.is_dir():
        raise PublishError(f"kit-dir is missing a station\\ directory: {station_dir}")

    return setup, packs


DIRECT_CONSUMER_RECEIPT_KIND = "civiccast-native-beta-direct-consumer-evidence"
DIRECT_CONSUMER_PROOFS = {
    "fresh_install",
    "failed_install_repair",
    "beta10_baseline_install",
    "beta10_to_beta11_upgrade",
    "verify_after_upgrade",
    "three_channel_runtime",
}
DIRECT_CHANNELS = ("public", "government", "education")
DIRECT_RUNTIME_PROOF_SCOPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "three-channel-capacity": ("three_channel_runtime", DIRECT_CHANNELS),
    "one-channel-install-smoke": ("one_channel_install_smoke", ("public",)),
}
DIRECT_JFK_WORDS = ("fellow", "americans", "country")
DIRECT_PLAYLIST_MAX_AGE_SECONDS = 30.0
DIRECT_RUNTIME_MIN_SPAN_SECONDS = 180.0
DIRECT_VTT_SAMPLE_MAX_BYTES = 32 * 1024
DIRECT_HOST_RUNTIME_MIN_SPAN_SECONDS = 30.0
DIRECT_PROOF_FIELDS = {
    "fresh_install": {"installer_run", "install_state", "activation_self_test"},
    "failed_install_repair": {
        "installer_run",
        "install_state",
        "activation_self_test",
        "fixture",
        "repair_install_log",
        "repair_verify_log",
        "post_repair_result",
        "post_repair_marker",
    },
    "beta10_baseline_install": {"installer_run", "install_state"},
    "beta10_to_beta11_upgrade": {
        "installer_run",
        "install_state",
        "activation_self_test",
        "upgrade_engine_log",
    },
    "verify_after_upgrade": {"result", "preserve_marker"},
    "three_channel_runtime": {"result", "preserve_marker", "snapshots"},
}


def _record(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublishError(f"direct consumer evidence {label} must be a JSON object")
    return value


def _record_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise PublishError(
            f"direct consumer evidence {label} fields mismatch (missing={missing}, extra={extra})"
        )


def _bound_path(receipt_dir: Path, reference: object, *, label: str) -> Path:
    ref = _record(reference, label=label)
    _record_keys(ref, {"path", "sha256"}, label=label)
    raw_path, expected_hash = ref.get("path"), ref.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise PublishError(f"direct consumer evidence {label} path is missing")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise PublishError(f"direct consumer evidence {label} sha256 is invalid")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = receipt_dir / candidate
    if candidate.is_symlink() or not candidate.is_file():
        raise PublishError(
            f"direct consumer evidence {label} file is missing or a symlink: {candidate}"
        )
    actual_hash = sha256_file(candidate)
    if actual_hash.casefold() != expected_hash.casefold():
        raise PublishError(
            f"direct consumer evidence {label} sha256 mismatch for {candidate}: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    return candidate.resolve()


def _bound_json(receipt_dir: Path, reference: object, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = _bound_path(receipt_dir, reference, label=label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(
            f"direct consumer evidence {label} is not valid UTF-8 JSON: {exc}"
        ) from exc
    return path, _record(data, label=label)


def _kit_member_path(kit_dir: Path, raw_path: object, *, label: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise PublishError(f"direct consumer evidence {label} path is missing")
    relative = Path(raw_path.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or relative.drive:
        raise PublishError(f"direct consumer evidence {label} path escapes the kit: {raw_path!r}")
    path = kit_dir / relative
    if path.is_symlink() or not path.is_file():
        raise PublishError(
            f"direct consumer evidence {label} kit member is missing or a symlink: {raw_path}"
        )
    resolved_kit = kit_dir.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_kit):
        raise PublishError(f"direct consumer evidence {label} path escapes the kit: {raw_path!r}")
    return relative.as_posix(), resolved_path


def _read_bound_text(receipt_dir: Path, reference: object, *, label: str) -> str:
    path = _bound_path(receipt_dir, reference, label=label)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PublishError(f"direct consumer evidence {label} is not UTF-8 text: {exc}") from exc


def _verify_install_state(state: dict[str, Any], *, version: str, label: str) -> None:
    health = state.get("health")
    if (
        state.get("installed_version") != version
        or state.get("service_state") != "Running"
        or not isinstance(health, dict)
        or health.get("status") != "healthy"
        or health.get("version") != version
    ):
        raise PublishError(
            f"direct consumer evidence {label} is not a running healthy {version} install"
        )


def _verify_physical_host_consumer(
    *,
    receipt_dir: Path,
    evidence: dict[str, Any],
    artifact_source_sha: str,
    build_run_id: str,
    setup: Path,
    installer_sha256: str,
) -> dict[str, str]:
    """Verify this exact installer on the already-running physical host.

    This route records a bounded in-place installation and live-output check.
    It intentionally does not stand in for the Sandbox fresh-install, repair,
    or Beta 10 upgrade scenarios.
    """

    _record_keys(
        evidence, {"host_install", "host_three_channel_runtime"}, label="physical-host proof set"
    )
    install_proof = _record(evidence.get("host_install"), label="host_install")
    _record_keys(install_proof, {"receipt", "installed_manifest"}, label="host_install")
    _, install = _bound_json(
        receipt_dir, install_proof.get("receipt"), label="physical-host install receipt"
    )
    manifest_path, manifest = _bound_json(
        receipt_dir, install_proof.get("installed_manifest"), label="installed app payload manifest"
    )
    if (
        install.get("kind") != "beta11-exact-host-install"
        or install.get("stage") != "completed"
        or install.get("status") != "passed"
        or str(install.get("source_sha", "")).casefold() != artifact_source_sha.casefold()
        or str(install.get("build_run_id")) != str(build_run_id)
        or str(install.get("setup_sha256", "")).casefold() != installer_sha256.casefold()
        or install.get("installer_exit_code") != 0
    ):
        raise PublishError(
            "physical-host receipt does not bind a successful run of this exact installer"
        )
    setup_path = install.get("setup_path")
    if not isinstance(setup_path, str) or Path(setup_path).resolve() != setup.resolve():
        raise PublishError(
            "physical-host receipt setup path does not name this exact kit installer"
        )
    setup_signature = _record(install.get("setup_authenticode"), label="host setup Authenticode")
    if (
        setup_signature.get("status") != "Valid"
        or setup_signature.get("file_version") != "1.0.0-beta.11"
        or "CN=Scott Converse" not in str(setup_signature.get("signer_subject", ""))
    ):
        raise PublishError(
            "physical-host receipt does not record the expected signed Beta 11 setup"
        )

    before = _record(install.get("before"), label="host pre-install state")
    after = _record(install.get("after"), label="host post-install state")
    before_health = _record(before.get("health"), label="host pre-install health")
    after_health = _record(after.get("health"), label="host post-install health")
    if (
        before.get("service_state") != "Running"
        or before_health.get("status") != "healthy"
        or not isinstance(before.get("display_version"), str)
        or not before.get("display_version")
        or before_health.get("version") != before.get("display_version")
        or after.get("service_state") != "Running"
        or after.get("display_version") != "1.0.0-beta.11"
        or after_health.get("status") != "healthy"
        or after_health.get("version") != "1.0.0-beta.11"
        or after_health.get("schema") != "current"
        or before.get("install_location") != after.get("install_location")
        or before.get("schedule_loop_enabled") is not True
        or after.get("schedule_loop_enabled") is not True
    ):
        raise PublishError(
            "physical-host receipt does not prove a healthy in-place Beta 11 install"
        )

    reported_manifest_path = after.get("app_payload_manifest_path")
    expected_manifest_path = (
        Path(str(after.get("install_location", ""))) / "runtime" / ("app-payload-manifest.json")
    )
    if (
        not isinstance(reported_manifest_path, str)
        or Path(reported_manifest_path).resolve() != expected_manifest_path.resolve()
        or str(after.get("app_payload_manifest_sha256", "")).casefold()
        != sha256_file(manifest_path).casefold()
        or after.get("app_payload_manifest_verified") is not True
    ):
        raise PublishError(
            "physical-host receipt does not bind its verified installed app manifest"
        )
    civiccast = _record(manifest.get("civiccast"), label="installed manifest CivicCast identity")
    source_state = _record(
        civiccast.get("source_state"), label="installed manifest source identity"
    )
    if (
        civiccast.get("version") != "1.0.0b11"
        or str(source_state.get("head", "")).casefold() != artifact_source_sha.casefold()
        or source_state.get("dirty") is not False
    ):
        raise PublishError(
            "installed app payload manifest does not identify the exact clean Beta 11 source"
        )

    runtime_proof = _record(
        evidence.get("host_three_channel_runtime"), label="host_three_channel_runtime"
    )
    _record_keys(runtime_proof, {"result", "snapshots"}, label="host_three_channel_runtime")
    _, runtime_result = _bound_json(
        receipt_dir, runtime_proof.get("result"), label="physical-host runtime result"
    )
    snapshots = runtime_proof.get("snapshots")
    if (
        runtime_result.get("result") != "PASS"
        or runtime_result.get("channels") != list(DIRECT_CHANNELS)
        or not isinstance(snapshots, list)
        or len(snapshots) < 2
    ):
        raise PublishError("physical-host runtime result does not cover all three live channels")
    previous_snapshot_at: datetime | None = None
    first_snapshot_at: datetime | None = None
    previous_media: dict[str, tuple[datetime, str, str]] = {}
    for index, snapshot_ref in enumerate(snapshots, start=1):
        _, snapshot = _bound_json(
            receipt_dir, snapshot_ref, label=f"physical-host runtime observation {index}"
        )
        snapshot_at = _utc_timestamp(snapshot.get("utc"), label=f"host runtime observation {index}")
        if previous_snapshot_at is not None and snapshot_at <= previous_snapshot_at:
            raise PublishError("physical-host runtime observation times must increase")
        if first_snapshot_at is None:
            first_snapshot_at = snapshot_at
        previous_snapshot_at = snapshot_at
        health = _record(snapshot.get("health"), label=f"host runtime observation {index} health")
        if health.get("status") != "healthy" or health.get("version") != "1.0.0-beta.11":
            raise PublishError(f"physical-host runtime observation {index} is not healthy Beta 11")
        channels = snapshot.get("channels")
        if (
            not isinstance(channels, list)
            or not all(isinstance(channel, dict) for channel in channels)
            or [channel.get("id") for channel in channels] != list(DIRECT_CHANNELS)
        ):
            raise PublishError(
                f"physical-host runtime observation {index} is missing a live channel"
            )
        for channel in channels:
            channel_id = channel["id"]
            state_value = channel.get("state")
            state_is_on_air = (
                state_value is None
                or _record(state_value, label=f"{channel_id} channel state").get("state")
                == "ON_AIR"
            )
            streams = channel.get("ffprobe_streams")
            codecs = (
                {
                    (stream.get("codec_type"), stream.get("codec_name"))
                    for stream in streams
                    if isinstance(stream, dict)
                }
                if isinstance(streams, list)
                else set()
            )
            playlist_age = channel.get("playlist_age_seconds")
            playlist_mtime = _utc_timestamp(
                channel.get("playlist_mtime_utc"), label=f"{channel_id} HLS playlist mtime"
            )
            newest_segment = channel.get("newest_segment")
            vtt_hash = channel.get("vtt_sha256")
            cue_count = channel.get("vtt_cue_count")
            caption_status = _record(
                channel.get("caption_runtime_status"), label=f"{channel_id} caption status"
            )
            if (
                not state_is_on_air
                or codecs != {("video", "h264"), ("audio", "aac")}
                or caption_status.get("state") != "within-capacity"
                or not isinstance(playlist_age, (int, float))
                or isinstance(playlist_age, bool)
                or not math.isfinite(playlist_age)
                or playlist_age < 0
                or playlist_age > DIRECT_PLAYLIST_MAX_AGE_SECONDS
                or abs((snapshot_at - playlist_mtime).total_seconds())
                > DIRECT_PLAYLIST_MAX_AGE_SECONDS
                or not isinstance(newest_segment, str)
                or not newest_segment
                or not isinstance(vtt_hash, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", vtt_hash)
                or not isinstance(cue_count, int)
                or isinstance(cue_count, bool)
                or cue_count <= 0
            ):
                raise PublishError(
                    f"physical-host runtime observation {index} channel {channel_id!r} has no current audio/video/caption output"
                )
            previous = previous_media.get(channel_id)
            if previous is not None and (
                playlist_mtime <= previous[0]
                or newest_segment == previous[1]
                or vtt_hash == previous[2]
            ):
                raise PublishError(
                    f"physical-host runtime channel {channel_id!r} output did not advance"
                )
            previous_media[channel_id] = (playlist_mtime, newest_segment, vtt_hash)

    if (
        first_snapshot_at is None
        or previous_snapshot_at is None
        or (previous_snapshot_at - first_snapshot_at).total_seconds()
        < DIRECT_HOST_RUNTIME_MIN_SPAN_SECONDS
    ):
        raise PublishError(
            "physical-host runtime observations do not show sustained output progress"
        )

    return {
        "consumer_mode": "physical-host",
        "host_install": (
            "PASS (exact signed Beta 11 installer; existing "
            f"{before['display_version']} host updated in place)"
        ),
        "host_preservation": "PASS (install location and service-loop setting retained; schema current)",
        "host_runtime": (
            f"PASS ({len(snapshots)} observations of live HLS, H.264/AAC and changing captions; "
            "not a three-channel capacity claim)"
        ),
    }


def _utc_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PublishError(f"direct consumer evidence {label} UTC timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishError(
            f"direct consumer evidence {label} has an invalid UTC timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PublishError(f"direct consumer evidence {label} timestamp must be UTC")
    return parsed.astimezone(UTC)


def verify_consumer_evidence_receipt(
    *,
    receipt_path: Path,
    kit_dir: Path,
    artifact_source_sha: str,
    build_run_id: str,
) -> tuple[Path, list[Path], dict[str, str]]:
    """Verify a bounded receipt over the assembled kit and executed Sandbox evidence."""

    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(
            f"could not read direct consumer evidence receipt {receipt_path}: {exc}"
        ) from exc
    doc = _record(receipt, label="receipt")
    receipt_fields = {"schema_version", "kind", "artifact", "evidence"}
    if "runtime_proof_scope" in doc:
        receipt_fields.add("runtime_proof_scope")
    if "consumer_mode" in doc:
        receipt_fields.add("consumer_mode")
    _record_keys(doc, receipt_fields, label="receipt")
    if doc.get("schema_version") != 1 or doc.get("kind") != DIRECT_CONSUMER_RECEIPT_KIND:
        raise PublishError("direct consumer evidence receipt schema or kind is unsupported")
    consumer_mode = doc.get("consumer_mode", "sandbox")
    if consumer_mode not in {"sandbox", "physical-host"}:
        raise PublishError(f"unsupported direct consumer evidence mode: {consumer_mode!r}")
    runtime_proof_scope = doc.get("runtime_proof_scope", "three-channel-capacity")
    if consumer_mode == "sandbox":
        if not isinstance(runtime_proof_scope, str) or runtime_proof_scope not in (
            DIRECT_RUNTIME_PROOF_SCOPES
        ):
            raise PublishError(f"unsupported direct runtime proof scope: {runtime_proof_scope!r}")
        runtime_proof_group, runtime_channels = DIRECT_RUNTIME_PROOF_SCOPES[runtime_proof_scope]
    else:
        if "runtime_proof_scope" in doc:
            raise PublishError("physical-host evidence uses its own three-channel output scope")
        runtime_proof_group, runtime_channels = "host_three_channel_runtime", DIRECT_CHANNELS

    artifact = _record(doc.get("artifact"), label="artifact")
    _record_keys(artifact, {"source_sha", "build_run_id", "assembly_receipt"}, label="artifact")
    if str(artifact.get("source_sha", "")).casefold() != artifact_source_sha.casefold():
        raise PublishError(
            "direct consumer evidence artifact source SHA does not match --artifact-source-sha"
        )
    if str(artifact.get("build_run_id")) != str(build_run_id):
        raise PublishError("direct consumer evidence build run id does not match --build-run-id")

    receipt_dir = receipt_path.resolve().parent
    _, assembly = _bound_json(
        receipt_dir, artifact.get("assembly_receipt"), label="kit assembly receipt"
    )
    if (
        assembly.get("schema_version") != 1
        or str(assembly.get("source_sha", "")).casefold() != artifact_source_sha.casefold()
    ):
        raise PublishError("kit assembly receipt source SHA does not match --artifact-source-sha")
    if str(assembly.get("workflow_run_id")) != str(build_run_id):
        raise PublishError("kit assembly receipt run id does not match --build-run-id")

    try:
        station_index = _record(assembly["station_index"], label="station index record")
        signature_record = _record(
            station_index["signature_verification"], label="station-index signature record"
        )
    except (KeyError, TypeError) as exc:
        raise PublishError("kit assembly receipt is missing its station signature record") from exc
    if consumer_mode == "sandbox":
        try:
            activation = _record(
                signature_record["consumer_activation_verification"],
                label="consumer activation record",
            )
            sandbox = _record(activation["actual_sandbox_result"], label="actual Sandbox result")
            baseline_activation = _record(
                sandbox["baseline_install"], label="Beta 10 baseline result"
            )
            upgrade_activation = _record(sandbox["upgrade_install"], label="Beta 10 upgrade result")
            upgrade_verification = _record(
                sandbox["verify_after_upgrade"], label="upgrade verification result"
            )
            setup_only_payload = str(upgrade_activation["payload"]).casefold()
        except (KeyError, TypeError) as exc:
            raise PublishError(
                "kit assembly receipt is missing its recorded Sandbox upgrade activation result"
            ) from exc
        if (
            activation.get("status") != "passed"
            or baseline_activation.get("status") != "passed"
            or baseline_activation.get("exit_code") != 0
            or upgrade_activation.get("status") != "passed"
            or upgrade_activation.get("exit_code") != 0
            or "exactly five runtime packs" not in setup_only_payload
            or "no station folder" not in setup_only_payload
            or upgrade_verification.get("status") != "passed"
            or upgrade_verification.get("exit_code") != 0
        ):
            raise PublishError(
                "kit assembly receipt does not bind the passed setup-only Beta 10 upgrade"
            )

    membership = _record(assembly.get("membership"), label="kit membership")
    if (
        membership.get("files") != 19
        or membership.get("installer_pack_count") != 5
        or membership.get("station_pack_count") != 6
        or membership.get("station_folder_present") is not True
    ):
        raise PublishError(
            "kit assembly receipt does not describe the complete 19-file Beta 11 kit"
        )

    raw_members = assembly.get("kit_members")
    if not isinstance(raw_members, list) or len(raw_members) != 19:
        raise PublishError("kit assembly receipt must bind exactly 19 kit members")
    members: dict[str, Path] = {}
    for index, raw_member in enumerate(raw_members):
        member = _record(raw_member, label=f"kit member {index + 1}")
        _record_keys(member, {"path", "size_bytes", "sha256"}, label=f"kit member {index + 1}")
        relative, path = _kit_member_path(
            kit_dir, member.get("path"), label=f"kit member {index + 1}"
        )
        canonical = relative.casefold()
        if canonical in members:
            raise PublishError(f"kit assembly receipt has duplicate member path {relative!r}")
        expected_size = member.get("size_bytes")
        expected_hash = member.get("sha256")
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size != path.stat().st_size
        ):
            raise PublishError(f"kit member size mismatch: {relative}")
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", expected_hash
        ):
            raise PublishError(f"kit member SHA-256 is invalid: {relative}")
        actual_hash = sha256_file(path)
        if actual_hash.casefold() != expected_hash.casefold():
            raise PublishError(f"kit member SHA-256 mismatch: {relative}")
        members[canonical] = path

    kit_root = kit_dir.resolve()
    kit_files = list(kit_root.rglob("*"))
    if any(path.is_symlink() for path in kit_files):
        raise PublishError("kit contains a symlink; refusing direct evidence validation")
    actual_members = {
        path.relative_to(kit_root).as_posix().casefold() for path in kit_files if path.is_file()
    }
    if actual_members != set(members):
        raise PublishError("kit file inventory differs from the exact 19-member assembly receipt")

    installer = _record(assembly.get("installer"), label="kit installer")
    installer_sha256 = installer.get("sha256")
    if not isinstance(installer_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", installer_sha256
    ):
        raise PublishError("kit assembly receipt installer SHA-256 is invalid")
    setup_relative, setup = _kit_member_path(kit_dir, installer.get("path"), label="kit installer")
    if Path(setup_relative).parent != Path():
        raise PublishError("kit assembly receipt installer must be at the kit root")
    if setup_relative.casefold() not in members or members[setup_relative.casefold()] != setup:
        raise PublishError("kit installer is not a member of the exact assembly receipt")
    if sha256_file(setup).casefold() != installer_sha256.casefold():
        raise PublishError("kit installer bytes do not match the requested installer SHA-256")
    setup, packs = verify_layout(kit_dir, setup_filename=setup_relative)

    evidence = _record(doc.get("evidence"), label="proof set")
    if consumer_mode == "physical-host":
        verification = _verify_physical_host_consumer(
            receipt_dir=receipt_dir,
            evidence=evidence,
            artifact_source_sha=artifact_source_sha,
            build_run_id=build_run_id,
            setup=setup,
            installer_sha256=installer_sha256,
        )
        return setup, packs, verification

    expected_proofs = (DIRECT_CONSUMER_PROOFS - {"three_channel_runtime"}) | {runtime_proof_group}
    _record_keys(evidence, expected_proofs, label="proof set")
    for proof_name, fields in DIRECT_PROOF_FIELDS.items():
        if proof_name == "three_channel_runtime":
            continue
        _record_keys(_record(evidence.get(proof_name), label=proof_name), fields, label=proof_name)
    _record_keys(
        _record(evidence.get(runtime_proof_group), label=runtime_proof_group),
        {"result", "preserve_marker", "snapshots"},
        label=runtime_proof_group,
    )

    def read_json(proof_name: str, file_name: str) -> dict[str, Any]:
        proof = _record(evidence.get(proof_name), label=proof_name)
        _, value = _bound_json(receipt_dir, proof.get(file_name), label=f"{proof_name}.{file_name}")
        return value

    def require_beta11_install(proof_name: str) -> None:
        run = read_json(proof_name, "installer_run")
        if (
            run.get("exit_code") != 0
            or str(run.get("sha256", "")).casefold() != installer_sha256.casefold()
        ):
            raise PublishError(
                f"direct consumer evidence {proof_name} did not run this Beta 11 installer successfully"
            )
        _verify_install_state(
            read_json(proof_name, "install_state"), version="1.0.0-beta.11", label=proof_name
        )
        activation = read_json(proof_name, "activation_self_test")
        if (
            activation.get("product_version") != "1.0.0-beta.11"
            or activation.get("result") != "passed"
        ):
            raise PublishError(
                f"direct consumer evidence {proof_name} activation self-test did not pass"
            )

    require_beta11_install("fresh_install")

    require_beta11_install("failed_install_repair")
    repair = _record(evidence.get("failed_install_repair"), label="failed_install_repair")
    _, fixture = _bound_json(receipt_dir, repair.get("fixture"), label="failed-install fixture")
    if (
        fixture.get("previous_installed_version") != "1.0.0-beta.11"
        or fixture.get("missing_runtime_key") != "whistle_assets_root"
        or fixture.get("installed_version_marker_removed") is not True
        or fixture.get("upgrade_journal_exists") is not False
        or fixture.get("service_status") != "Stopped"
    ):
        raise PublishError(
            "failed-install repair fixture does not record the known Beta 11 broken state"
        )
    repair_install_log = _read_bound_text(
        receipt_dir, repair.get("repair_install_log"), label="repair install command log"
    )
    repair_verify_log = _read_bound_text(
        receipt_dir, repair.get("repair_verify_log"), label="repair verification command log"
    )
    if "PASS" not in repair_install_log or "PASS" not in repair_verify_log:
        raise PublishError(
            "failed-install repair command and post-repair verification must both PASS"
        )
    repair_result = read_json("failed_install_repair", "post_repair_result")
    repair_marker = read_json("failed_install_repair", "post_repair_marker")
    repaired_schedules = repair_result.get("preserved_schedule_ids")
    repair_health = repair_result.get("health")
    repair_marker_runtime = repair_marker.get("runtime")
    if (
        repair_result.get("result") != "PASS"
        or repair_result.get("login") != "PASS"
        or repair_result.get("preserve_install_and_database") is not True
        or repair_result.get("product_version") != "1.0.0-beta.11"
        or not isinstance(repair_health, dict)
        or repair_health.get("status") != "healthy"
        or not isinstance(repaired_schedules, list)
        or len(repaired_schedules) != 3
        or not all(isinstance(item, str) for item in repaired_schedules)
        or len(set(repaired_schedules)) != 3
        or repair_marker.get("schedule_ids") != repaired_schedules
        or repair_result.get("preserved_asset_id")
        != repair_marker.get("preserved_baseline_asset_id")
        or not isinstance(repair_marker_runtime, dict)
        or repair_marker_runtime.get("whistle_assets_root") != "packs/captions-whistle"
    ):
        raise PublishError(
            "failed-install repair verification does not prove restored account data and Whistle activation"
        )

    baseline_run = read_json("beta10_baseline_install", "installer_run")
    if (
        baseline_run.get("exit_code") != 0
        or "beta.10" not in str(baseline_run.get("installer", "")).casefold()
    ):
        raise PublishError("Beta 10 baseline installer did not complete successfully")
    _verify_install_state(
        read_json("beta10_baseline_install", "install_state"),
        version="1.0.0-beta.10",
        label="Beta 10 baseline",
    )

    require_beta11_install("beta10_to_beta11_upgrade")
    upgrade = _record(evidence.get("beta10_to_beta11_upgrade"), label="beta10_to_beta11_upgrade")
    upgrade_log = _read_bound_text(
        receipt_dir, upgrade.get("upgrade_engine_log"), label="Beta 10 to Beta 11 upgrade log"
    )
    if (
        "old=1.0.0-beta.10 new=1.0.0-beta.11" not in upgrade_log
        or "route: upgrade" not in upgrade_log
    ):
        raise PublishError("upgrade log does not prove the Beta 10 to Beta 11 upgrade path")

    verify_result = read_json("verify_after_upgrade", "result")
    verify_marker = read_json("verify_after_upgrade", "preserve_marker")
    schedule_ids = verify_result.get("preserved_schedule_ids")
    marker_schedules = verify_marker.get("baseline_schedule_ids")
    verify_health = verify_result.get("health")
    verify_marker_runtime = verify_marker.get("runtime")
    if (
        verify_result.get("result") != "PASS"
        or verify_result.get("login") != "PASS"
        or verify_result.get("preserve_install_and_database") is not True
        or verify_result.get("product_version") != "1.0.0-beta.11"
        or not isinstance(verify_health, dict)
        or verify_health.get("status") != "healthy"
        or not isinstance(schedule_ids, list)
        or len(schedule_ids) != 3
        or not all(isinstance(item, str) for item in schedule_ids)
        or len(set(schedule_ids)) != 3
        or marker_schedules != schedule_ids
        or verify_result.get("preserved_asset_id")
        != verify_marker.get("preserved_baseline_asset_id")
        or not isinstance(verify_marker_runtime, dict)
        or verify_marker_runtime.get("whistle_assets_root") != "packs/captions-whistle"
    ):
        raise PublishError(
            "post-upgrade verification does not prove the original account data was preserved"
        )

    runtime_result = read_json(runtime_proof_group, "result")
    runtime_marker = read_json(runtime_proof_group, "preserve_marker")
    if (
        runtime_result.get("result") != "PASS"
        or runtime_result.get("observed_minutes") != 5
        or runtime_result.get("channels") != list(runtime_channels)
        or runtime_result.get("preserve_install_and_database") is not True
        or runtime_marker.get("preserve_install_and_database") is not True
        or runtime_marker.get("product_version") != "1.0.0-beta.11"
    ):
        raise PublishError(
            f"{runtime_proof_scope} runtime receipt does not record the five-minute Beta 11 pass"
        )

    runtime_proof = _record(evidence.get(runtime_proof_group), label=runtime_proof_group)
    snapshots = runtime_proof.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != 5:
        raise PublishError(
            f"{runtime_proof_scope} runtime proof must bind all five minute snapshots"
        )
    vtt_hashes: dict[str, set[str]] = {channel: set() for channel in runtime_channels}
    jfk_words_seen: dict[str, set[str]] = {channel: set() for channel in runtime_channels}
    previous_media: dict[str, tuple[datetime, str]] = {}
    first_snapshot_at: datetime | None = None
    previous_snapshot_at: datetime | None = None
    for expected_minute, snapshot_ref in enumerate(snapshots, start=1):
        _, snapshot = _bound_json(
            receipt_dir, snapshot_ref, label=f"runtime minute {expected_minute}"
        )
        snapshot_at = _utc_timestamp(snapshot.get("utc"), label=f"runtime minute {expected_minute}")
        if previous_snapshot_at is not None and snapshot_at <= previous_snapshot_at:
            raise PublishError("runtime snapshot UTC times must increase")
        if first_snapshot_at is None:
            first_snapshot_at = snapshot_at
        previous_snapshot_at = snapshot_at
        snapshot_health = snapshot.get("health")
        if (
            snapshot.get("minute") != expected_minute
            or not isinstance(snapshot_health, dict)
            or snapshot_health.get("status") != "healthy"
            or snapshot_health.get("version") != "1.0.0-beta.11"
            or snapshot.get("pinned_whistle_error_seen") is not False
            or snapshot.get("whistle_active_seen") != dict.fromkeys(runtime_channels, True)
            or snapshot.get("whistle_fallback_seen") != dict.fromkeys(runtime_channels, False)
        ):
            raise PublishError(
                f"runtime minute {expected_minute} does not show healthy Whistle primary operation"
            )
        channels = snapshot.get("channels")
        if (
            not isinstance(channels, list)
            or not all(isinstance(channel, dict) for channel in channels)
            or [channel.get("id") for channel in channels] != list(runtime_channels)
        ):
            raise PublishError(
                f"runtime minute {expected_minute} is missing one or more expected channels"
            )
        for channel in channels:
            channel_id = channel["id"]
            streams = channel.get("ffprobe_streams")
            codecs = (
                {
                    (stream.get("codec_type"), stream.get("codec_name"))
                    for stream in streams
                    if isinstance(stream, dict)
                }
                if isinstance(streams, list)
                else set()
            )
            expected_codecs = {("video", "h264"), ("audio", "aac")}
            words = channel.get("expected_jfk_words_seen")
            vtt_hash = channel.get("vtt_sha256")
            vtt_text = channel.get("vtt_text_snapshot")
            vtt_text_bytes = channel.get("vtt_text_snapshot_utf8_bytes")
            channel_state = channel.get("state")
            caption_status = channel.get("caption_runtime_status")
            playlist_age = channel.get("playlist_age_seconds")
            if (
                not isinstance(playlist_age, (int, float))
                or isinstance(playlist_age, bool)
                or playlist_age < 0
                or playlist_age > DIRECT_PLAYLIST_MAX_AGE_SECONDS
                or not math.isfinite(playlist_age)
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} HLS playlist is stale"
                )
            playlist_mtime = _utc_timestamp(
                channel.get("playlist_mtime_utc"),
                label=f"runtime minute {expected_minute} channel {channel_id} playlist mtime",
            )
            if (
                abs((snapshot_at - playlist_mtime).total_seconds())
                > DIRECT_PLAYLIST_MAX_AGE_SECONDS
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} playlist mtime is stale"
                )
            timestamp_age = max(0.0, (snapshot_at - playlist_mtime).total_seconds())
            if abs(playlist_age - timestamp_age) > 10.0:
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} playlist age and mtime disagree"
                )
            newest_segment = channel.get("newest_segment")
            if not isinstance(newest_segment, str) or not newest_segment.strip():
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} has no newest HLS segment"
                )
            segment_count = channel.get("segment_count")
            if (
                not isinstance(segment_count, int)
                or isinstance(segment_count, bool)
                or segment_count <= 0
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} has no HLS segments"
                )
            previous = previous_media.get(channel_id)
            if previous is not None and (
                playlist_mtime <= previous[0] or newest_segment == previous[1]
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} HLS media did not advance"
                )
            previous_media[channel_id] = (playlist_mtime, newest_segment)
            if (
                not isinstance(vtt_text, str)
                or not vtt_text
                or not isinstance(vtt_text_bytes, int)
                or isinstance(vtt_text_bytes, bool)
                or vtt_text_bytes != len(vtt_text.encode("utf-8"))
                or vtt_text_bytes > DIRECT_VTT_SAMPLE_MAX_BYTES
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} has no bounded VTT review sample"
                )
            if isinstance(words, dict):
                jfk_words_seen[channel_id].update(
                    word for word in DIRECT_JFK_WORDS if words.get(word) is True
                )
            if (
                not isinstance(channel_state, dict)
                or channel_state.get("state") != "ON_AIR"
                or not isinstance(caption_status, dict)
                or caption_status.get("state") != "within-capacity"
                or not isinstance(channel.get("vtt_cue_count"), int)
                or channel["vtt_cue_count"] <= 0
                or not isinstance(words, dict)
                or codecs != expected_codecs
                or not isinstance(vtt_hash, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", vtt_hash)
            ):
                raise PublishError(
                    f"runtime minute {expected_minute} channel {channel_id!r} failed media/caption checks"
                )
            vtt_hashes[channel_id].add(vtt_hash)

    if (
        first_snapshot_at is None
        or previous_snapshot_at is None
        or (previous_snapshot_at - first_snapshot_at).total_seconds()
        < DIRECT_RUNTIME_MIN_SPAN_SECONDS
    ):
        raise PublishError("five-minute runtime snapshots span less than three minutes")
    for channel in runtime_channels:
        if len(vtt_hashes[channel]) < 3:
            raise PublishError(
                f"runtime channel {channel!r} VTT did not progress in at least three samples"
            )
        if len(jfk_words_seen[channel]) < 2:
            raise PublishError(
                f"runtime channel {channel!r} recognized fewer than two JFK reference words"
            )

    return (
        setup,
        packs,
        {
            "consumer_mode": "sandbox",
            "fresh_install": "PASS",
            "failed_install_repair": "PASS",
            "repair_preservation": "PASS",
            "beta10_to_beta11_upgrade": "PASS",
            "preservation": "PASS",
            "runtime": (
                "PASS (five minutes, three channels)"
                if runtime_proof_scope == "three-channel-capacity"
                else "PASS (five-minute one-channel install-smoke; three-channel capacity "
                "unproven; host soak is separate evidence)"
            ),
        },
    )


def get_product_version(setup: Path) -> str:
    proc = run_powershell(
        f"(Get-Item -LiteralPath {_powershell_literal(setup)}).VersionInfo.ProductVersion"
    )
    if proc.returncode != 0:
        raise PublishError(
            f"could not read setup.exe ProductVersion via PowerShell: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    version = (proc.stdout or "").strip()
    if not version:
        raise PublishError(f"setup.exe ProductVersion came back empty: {setup}")
    return version


def get_native_source_version() -> str:
    from civiccast._native_version import __version__ as native_version

    return native_version


def _powershell_literal(value: str | Path) -> str:
    """Return a single-quoted PowerShell literal with embedded quotes doubled."""

    return "'" + str(value).replace("'", "''") + "'"


def verify_version_identity(setup: Path, tag: str) -> str:
    """Require setup.exe ProductVersion == source-tree version == tag (no 'v').

    Returns the agreed version string. Any mismatch refuses.
    """

    if not tag.startswith("v"):
        raise PublishError(f"--tag must start with 'v': {tag!r}")
    tag_version = tag[1:]

    product_version = get_product_version(setup)
    source_version = get_native_source_version()

    if product_version != tag_version:
        raise PublishError(
            f"setup.exe ProductVersion {product_version!r} does not match "
            f"tag {tag!r} (expected {tag_version!r})."
        )
    if source_version != tag_version:
        raise PublishError(
            f"civiccast._native_version.__version__ {source_version!r} does "
            f"not match tag {tag!r} (expected {tag_version!r})."
        )
    return tag_version


# ---------------------------------------------------------------------------
# (b) Authenticode verification
# ---------------------------------------------------------------------------
def verify_signature(setup: Path) -> None:
    proc = run_powershell(
        f"(Get-AuthenticodeSignature -LiteralPath {_powershell_literal(setup)}).Status"
    )
    if proc.returncode != 0:
        raise PublishError(
            f"could not run Get-AuthenticodeSignature on {setup}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    status = (proc.stdout or "").strip()
    if status != "Valid":
        raise PublishError(
            f"setup.exe Authenticode signature status is {status!r}, expected "
            "'Valid' (see CODE_SIGNING_POLICY.md)."
        )


# ---------------------------------------------------------------------------
# (c) Gate A verdict verification
# ---------------------------------------------------------------------------
def download_gate_a_verdicts(
    *, repository: str, gate_a_run_id: str, build_run_id: str, dest_dir: Path
) -> dict[str, dict[str, Any]]:
    """Download and parse gate-a-verdict.json for all three required lanes.

    ``gate_a_run_id`` selects WHICH workflow run's artifacts to fetch from
    (the positional argument to ``gh run download``); ``build_run_id`` names
    WHICH artifact to fetch, because gate-a-station-acceptance.yml's own
    ``run_id`` step output is the build run being validated
    (``github.event.inputs.run_id``), not the Gate A workflow's own run id --
    so every ``gate-a*-verdict-<id>`` artifact it uploads is suffixed with
    the build run id, even though those artifacts live on the Gate A run.
    Confirmed live: Gate A run 33713004718 (validating build 33711079441)
    uploads artifacts named ``gate-a-verdict-33711079441``,
    ``gate-a-dirty-verdict-33711079441``,
    ``gate-a-download-only-verdict-33711079441`` -- never
    ``*-33713004718``. Formatting the artifact name with ``gate_a_run_id``
    (the original code) looks for an artifact that can never exist whenever
    the two run ids differ, which the existing test suite never caught
    because its fakes never modeled a real Gate A run's artifact names.
    """

    # A dry-run may be followed by live publication using the same destination.
    # Archive every fetch under a fresh directory so an old proof is never
    # overwritten, reused, or mistaken for the current Gate A run.
    attempt_dir = dest_dir / f"attempt-{uuid.uuid4().hex}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    verdicts: dict[str, dict[str, Any]] = {}
    for lane in GATE_A_LANES:
        artifact_name = GATE_A_ARTIFACT_NAMES[lane].format(run_id=build_run_id)
        lane_dir = attempt_dir / lane
        lane_dir.mkdir(parents=True, exist_ok=False)
        proc = run_gh(
            [
                "run",
                "download",
                gate_a_run_id,
                "-R",
                repository,
                "-n",
                artifact_name,
                "-D",
                str(lane_dir),
            ]
        )
        if proc.returncode != 0:
            raise PublishError(
                f"could not download Gate A verdict artifact {artifact_name!r} "
                f"for lane {lane!r} (run {gate_a_run_id}): "
                f"{(proc.stderr or proc.stdout or '').strip()}"
            )
        verdict_path = lane_dir / "gate-a-verdict.json"
        if not verdict_path.is_file():
            raise PublishError(
                f"downloaded Gate A artifact {artifact_name!r} does not contain "
                f"gate-a-verdict.json for lane {lane!r}."
            )
        try:
            verdicts[lane] = json.loads(verdict_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PublishError(
                f"gate-a-verdict.json for lane {lane!r} is not valid JSON: {exc}"
            ) from exc
    return verdicts


def verify_gate_a_verdicts(verdicts: dict[str, dict[str, Any]], *, source_sha: str) -> None:
    """Require all three lanes PASS and share the same source_sha == --source-sha."""

    missing = [lane for lane in GATE_A_LANES if lane not in verdicts]
    if missing:
        raise PublishError(f"missing Gate A verdict(s) for lane(s): {missing}")

    for lane in GATE_A_LANES:
        doc = verdicts[lane]
        verdict = doc.get("verdict")
        if verdict != "PASS":
            raise PublishError(f"Gate A lane {lane!r} did not PASS (verdict: {verdict!r}).")
        doc_sha = doc.get("source_sha")
        if doc_sha != source_sha:
            raise PublishError(
                f"Gate A lane {lane!r} verdict source_sha {doc_sha!r} does not "
                f"match --source-sha {source_sha!r}."
            )
        # The clean-lane document carries no "lane" field at all
        # (gate_a_verdict.py's build_verdict_document only stamps "lane" when
        # lane != "clean"); dirty/download-only must self-report their lane.
        doc_lane = doc.get("lane", "clean")
        if doc_lane != lane:
            raise PublishError(
                f"Gate A lane {lane!r} verdict document reports lane {doc_lane!r} instead."
            )

    shas = {verdicts[lane].get("source_sha") for lane in GATE_A_LANES}
    if len(shas) != 1:
        raise PublishError(f"Gate A lane verdicts do not share the same source_sha: {shas}")


# ---------------------------------------------------------------------------
# (d) Hashing + manifest
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_sha256sums(files: list[Path]) -> str:
    lines = [f"{sha256_file(path)}  {path.name}" for path in files]
    return "\n".join(lines) + "\n"


def build_sidecar(setup: Path, *, signed: bool) -> dict[str, Any]:
    """Match the shape scripts/policy/check_sidecar_attestation_integrity.py
    and scripts/download_windows_release_artifacts.ps1 already read: a real
    sha256, install_manifest.signed (verified against real Authenticode
    evidence, never a bare flag), and attestation always null (this release
    chain carries no cosign/Sigstore step -- CODE_SIGNING_POLICY.md, ADR
    0022).
    """

    return {
        "sha256": sha256_file(setup),
        "attestation": None,
        "install_manifest": {"signed": signed},
    }


# ---------------------------------------------------------------------------
# (e) Release notes
# ---------------------------------------------------------------------------
def extract_changelog_unreleased(changelog_text: str) -> str:
    match = re.search(
        r"^## \[Unreleased\]\s*$(.*?)(?=^## \[|\Z)",
        changelog_text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1).strip()


def build_run_url(repository: str, run_id: str) -> str:
    return f"https://github.com/{repository}/actions/runs/{run_id}"


def render_notes(
    *,
    tag: str,
    source_sha: str,
    repository: str,
    build_run_id: str,
    gate_a_run_id: str | None,
    verdicts: dict[str, dict[str, Any]] | None,
    changelog_text: str,
    assets: list[dict[str, Any]],
    artifact_source_sha: str,
    direct_verification: dict[str, str] | None = None,
) -> str:
    lane_verdicts = (
        {lane: verdicts[lane]["verdict"] for lane in GATE_A_LANES} if verdicts is not None else None
    )
    return render_native_beta_candidate_notes(
        tag=tag,
        source_sha=source_sha,
        build_run_url=build_run_url(repository, build_run_id),
        gate_a_run_url=build_run_url(repository, gate_a_run_id) if gate_a_run_id else None,
        lane_verdicts=lane_verdicts,
        changelog_unreleased=extract_changelog_unreleased(changelog_text),
        assets=assets,
        smartscreen_note=SMARTSCREEN_NOTE,
        artifact_source_sha=artifact_source_sha,
        direct_verification=direct_verification,
    )


# ---------------------------------------------------------------------------
# (f) Publish (or dry-run)
# ---------------------------------------------------------------------------
def verify_gh_auth() -> None:
    """Refuse before anything else if `gh` has no working GitHub login.

    Every later step (Gate A artifact download, draft create, verify,
    un-draft) goes through `gh`; an unauthenticated CLI would otherwise
    surface as a confusing mid-flow failure.
    """

    proc = run_gh(["auth", "status"])
    if proc.returncode != 0:
        raise PublishError(
            "gh is not authenticated (`gh auth status` failed) -- run "
            "`gh auth login` before publishing: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def preflight_asset_limits(asset_paths: list[Path]) -> None:
    """Refuse BEFORE any remote mutation if any asset is >= GitHub's 2 GiB cap.

    Prints the complete asset set (name + bytes) so the operator sees exactly
    what would be uploaded.
    """

    print("publish_beta_candidate: release asset set (pre-flight):")
    oversize: list[str] = []
    for path in asset_paths:
        size = path.stat().st_size
        flag = "  OVERSIZE" if size >= GITHUB_ASSET_LIMIT_BYTES else ""
        print(f"  {path.name}  {size:,} bytes{flag}")
        if size >= GITHUB_ASSET_LIMIT_BYTES:
            oversize.append(f"{path.name} ({size:,} bytes)")
    if oversize:
        raise PublishError(
            "asset(s) at or above GitHub's 2 GiB per-file release-asset cap "
            f"({GITHUB_ASSET_LIMIT_BYTES:,} bytes); refusing before any remote "
            f"mutation: {', '.join(oversize)}"
        )


def _gh_error(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def delete_draft_release(*, repository: str, tag: str) -> bool:
    """Best-effort delete of a draft release. Returns True on success.

    A draft release has no tag, so deleting it leaves nothing behind. Never
    raises: this runs on an already-failing path, and the original failure
    is what must be reported.
    """

    proc = run_gh(["release", "delete", tag, "-R", repository, "--yes"])
    return proc.returncode == 0


def create_draft_release(
    *,
    repository: str,
    tag: str,
    source_sha: str,
    title: str,
    notes_file: Path,
    asset_paths: list[Path],
) -> None:
    """Create the release as a DRAFT targeting source_sha, with every asset.

    A draft creates NO tag. The public tag is created atomically with the
    release only when `undraft_release` flips `--draft=false`, so a failure
    anywhere before that leaves no orphan tag. On failure here the (possibly
    partially created) draft is deleted best-effort and the failure raised.
    """

    proc = run_gh(
        [
            "release",
            "create",
            tag,
            "-R",
            repository,
            "--draft",
            "--target",
            source_sha,
            "--prerelease",
            "--title",
            title,
            "--notes-file",
            str(notes_file),
            *[str(p) for p in asset_paths],
        ]
    )
    if proc.returncode != 0:
        deleted = delete_draft_release(repository=repository, tag=tag)
        cleanup = "draft deleted" if deleted else "no draft to delete / delete failed"
        raise PublishError(
            f"gh release create (draft) failed for {tag}; {cleanup}; no tag was "
            f"created: {_gh_error(proc)}"
        )


def verify_draft_assets(*, repository: str, tag: str, asset_paths: list[Path]) -> None:
    """Fetch the draft and assert it is still a draft and every expected
    asset is present with a matching size. On ANY mismatch the draft is
    deleted (best-effort) and the mismatch raised -- no tag exists yet, so
    nothing is left behind.
    """

    proc = run_gh(["release", "view", tag, "-R", repository, "--json", "assets,isDraft"])
    if proc.returncode != 0:
        delete_draft_release(repository=repository, tag=tag)
        raise PublishError(
            f"could not fetch draft release {tag} to verify assets (draft deleted): "
            f"{_gh_error(proc)}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        delete_draft_release(repository=repository, tag=tag)
        raise PublishError(
            f"gh release view returned non-JSON output (draft deleted): {exc}"
        ) from exc

    problems: list[str] = []
    if payload.get("isDraft") is not True:
        problems.append("release is not a draft (isDraft != true) -- refusing to continue")
    remote_by_name = {a["name"]: a for a in payload.get("assets", [])}
    for local_path in asset_paths:
        remote = remote_by_name.get(local_path.name)
        if remote is None:
            problems.append(f"missing asset {local_path.name!r}")
            continue
        local_size = local_path.stat().st_size
        remote_size = remote.get("size")
        if remote_size != local_size:
            problems.append(
                f"asset {local_path.name!r} size mismatch: local {local_size} bytes, "
                f"GitHub reports {remote_size} bytes"
            )
    if problems:
        deleted = delete_draft_release(repository=repository, tag=tag)
        cleanup = (
            "draft deleted, no tag created"
            if deleted
            else "DRAFT DELETE FAILED -- remove it by hand"
        )
        raise PublishError(
            f"draft release {tag} failed asset verification ({cleanup}): " + "; ".join(problems)
        )


def undraft_release(*, repository: str, tag: str) -> None:
    """Flip the verified draft to a public prerelease. This is the single
    step that creates the public tag, atomically with the release.

    On failure the draft is deliberately NOT deleted: un-draft may have
    partially applied server-side and deleting could remove a now-public
    release. Report loudly instead.
    """

    proc = run_gh(["release", "edit", tag, "-R", repository, "--draft=false"])
    if proc.returncode != 0:
        raise PublishError(
            f"gh release edit --draft=false failed for {tag}; the verified DRAFT "
            "is left in place (not deleted, since un-draft may have partially "
            "applied). Before choosing a recovery, run "
            f"`gh release view {tag} -R {repository} --json isDraft,url` to learn "
            "whether the release actually went public; then either publish or "
            f"delete it by hand: {_gh_error(proc)}"
        )


# ---------------------------------------------------------------------------
# (g) release-truth.yaml update
# ---------------------------------------------------------------------------
def update_release_truth(*, truth_path: Path, tag: str, status: str, notes: str) -> str:
    """Add a new entry for tag with the given status; flip the previous
    `current` entry to `superseded` (naming this tag) if status == current.

    Returns a human-readable diff-like summary of the edit (never mutates
    silently).
    """

    if status not in ("current", "staging"):
        raise PublishError(f"--truth-status must be 'current' or 'staging', got {status!r}")

    text = truth_path.read_text(encoding="utf-8")
    summary_lines = [f"docs/releases/release-truth.yaml edits for {tag} (status={status}):"]

    new_entry_lines = [
        f"  - tag: {tag}",
        f"    status: {status}",
        "    notes: >-",
        f"      {notes}",
    ]
    entries_marker = "\nentries:\n"
    idx = text.index(entries_marker)
    insert_at = idx + len(entries_marker)
    text = text[:insert_at] + "\n".join(new_entry_lines) + "\n" + text[insert_at:]
    summary_lines.append(f"  + added entry: tag={tag} status={status}")

    if status == "current":
        current_match = re.search(r"^current:\s*(\S+)\s*$", text, re.MULTILINE)
        if not current_match:
            raise PublishError("release-truth.yaml has no top-level 'current:' field.")
        previous_current_tag = current_match.group(1)
        if previous_current_tag != tag:
            text = re.sub(
                r"^current:\s*\S+\s*$",
                f"current: {tag}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
            summary_lines.append(f"  ~ current: {previous_current_tag} -> {tag}")

            entry_pattern = re.compile(
                rf"(- tag: {re.escape(previous_current_tag)}\n(?:.*\n)*?    status: )current(\s*\n)"
            )

            def _flip(match: re.Match[str]) -> str:
                return f"{match.group(1)}superseded{match.group(2)}    superseded_by: {tag}\n"

            new_text, count = entry_pattern.subn(_flip, text, count=1)
            if count != 1:
                raise PublishError(
                    f"could not locate the previous current entry {previous_current_tag!r} "
                    "in release-truth.yaml to flip it to superseded."
                )
            text = new_text
            summary_lines.append(
                f"  ~ {previous_current_tag}: status current -> superseded (superseded_by: {tag})"
            )

    truth_path.write_text(text, encoding="utf-8", newline="\n")
    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--artifact-source-sha")
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--gate-a-run-id")
    parser.add_argument("--consumer-evidence-receipt", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--truth-status", required=True, choices=("current", "staging"))
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _run(args)
    except PublishError as exc:
        print(f"publish_beta_candidate: REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


def _run(args: argparse.Namespace) -> None:
    repo_root: Path = args.repo_root
    kit_dir: Path = args.kit_dir
    tag: str = args.tag
    source_sha: str = args.source_sha
    direct_receipt: Path | None = args.consumer_evidence_receipt
    repository: str = args.repository
    direct_mode = direct_receipt is not None

    if direct_mode == (args.gate_a_run_id is not None):
        raise PublishError("provide exactly one of --gate-a-run-id or --consumer-evidence-receipt")
    if direct_mode and not args.artifact_source_sha:
        raise PublishError("--artifact-source-sha is required with --consumer-evidence-receipt")
    artifact_source_sha = args.artifact_source_sha or source_sha
    if direct_mode and (
        not re.fullmatch(r"[0-9a-fA-F]{40}", source_sha)
        or not re.fullmatch(r"[0-9a-fA-F]{40}", artifact_source_sha)
    ):
        raise PublishError("direct consumer evidence requires full 40-character source commit SHAs")

    print("publish_beta_candidate: verifying gh authentication")
    verify_gh_auth()

    print(f"publish_beta_candidate: verifying kit layout at {kit_dir}")
    direct_verification: dict[str, str] | None = None
    if direct_receipt is not None:
        setup, packs, direct_verification = verify_consumer_evidence_receipt(
            receipt_path=direct_receipt,
            kit_dir=kit_dir,
            artifact_source_sha=artifact_source_sha,
            build_run_id=args.build_run_id,
        )
        print(
            "publish_beta_candidate: direct consumer evidence, assembly receipt, and all kit member hashes verified"
        )
    else:
        setup, packs = verify_layout(kit_dir)

    print("publish_beta_candidate: verifying version identity")
    version = verify_version_identity(setup, tag)
    print(f"publish_beta_candidate: version {version} agrees (signed installer, source tree, tag)")

    manual_dir = kit_dir / "manual"
    manual_files: list[Path] = []
    if manual_dir.exists() or manual_required_for_version(version):
        try:
            manual_files = verify_candidate_manual(
                manual_dir=manual_dir,
                source_sha=artifact_source_sha,
                candidate_version=version,
                workflow_run_id=args.build_run_id,
                repo_root=REPO_ROOT,
            )
        except CandidateManualError as exc:
            raise PublishError(f"candidate manual verification failed: {exc}") from exc
        print("publish_beta_candidate: exact-build manual receipt and files verified")

    print("publish_beta_candidate: verifying Authenticode signature")
    verify_signature(setup)
    print("publish_beta_candidate: signature Valid")

    verdicts: dict[str, dict[str, Any]] | None = None
    if args.gate_a_run_id:
        print(f"publish_beta_candidate: downloading Gate A verdicts for run {args.gate_a_run_id}")
        gate_a_dir = repo_root / "artifacts" / "release" / tag / "gate-a-verdicts"
        verdicts = download_gate_a_verdicts(
            repository=repository,
            gate_a_run_id=args.gate_a_run_id,
            build_run_id=args.build_run_id,
            dest_dir=gate_a_dir,
        )
        verify_gate_a_verdicts(verdicts, source_sha=artifact_source_sha)
        print("publish_beta_candidate: Gate A PASS on all three lanes, artifact source SHA agrees")
    else:
        assert direct_verification is not None
        if direct_verification.get("consumer_mode") == "physical-host":
            print(
                "publish_beta_candidate: exact physical-host install/output proof passed; "
                "Sandbox lanes and Gate A were not run"
            )
        else:
            print(
                "publish_beta_candidate: direct Sandbox consumer proof passed; Gate A workflow was not run"
            )

    print("publish_beta_candidate: hashing assets and building manifest")
    out_dir = repo_root / "artifacts" / "release" / tag
    setup_asset = setup
    if direct_mode and setup.name != SETUP_ASSET_NAME:
        setup_asset_dir = out_dir / "assets"
        setup_asset_dir.mkdir(parents=True, exist_ok=True)
        setup_asset = setup_asset_dir / SETUP_ASSET_NAME
        temporary_setup = setup_asset.with_name(f"{SETUP_ASSET_NAME}.{uuid.uuid4().hex}.tmp")
        shutil.copyfile(setup, temporary_setup)
        if sha256_file(temporary_setup).casefold() != sha256_file(setup).casefold():
            temporary_setup.unlink(missing_ok=True)
            raise PublishError("staged setup.exe alias does not match the signed installer bytes")
        temporary_setup.replace(setup_asset)

    all_files = [setup_asset, *packs, *manual_files]
    sha256sums = build_sha256sums(all_files)
    sidecar = build_sidecar(setup_asset, signed=True)
    sidecar_filename = f"{setup_asset.name}{SIDECAR_SUFFIX}"

    # SHA256SUMS.txt and the sidecar are release assets too. Write them to the
    # local out_dir FIRST (local files only -- no remote state) so the asset
    # table below can carry their real bytes/hash, and so the pre-flight size
    # check covers the complete asset set. Same in dry-run and live mode.
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_dir / sidecar_filename
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8", newline="\n")
    sha256sums_path = out_dir / SHA256SUMS_ASSET_NAME
    sha256sums_path.write_text(sha256sums, encoding="utf-8", newline="\n")
    asset_paths = [setup_asset, *packs, *manual_files, sha256sums_path, sidecar_path]

    # Pre-flight: every asset under GitHub's 2 GiB cap, full set listed --
    # BEFORE any remote mutation, in dry-run and live mode alike.
    preflight_asset_limits(asset_paths)

    changelog_path = repo_root / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    asset_table = [
        {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in asset_paths
    ]
    notes = render_notes(
        tag=tag,
        source_sha=source_sha,
        repository=repository,
        build_run_id=args.build_run_id,
        gate_a_run_id=args.gate_a_run_id,
        verdicts=verdicts,
        changelog_text=changelog_text,
        assets=asset_table,
        artifact_source_sha=artifact_source_sha,
        direct_verification=direct_verification,
    )

    notes_file = out_dir / "RELEASE-NOTES.md"
    notes_file.write_text(notes, encoding="utf-8", newline="\n")
    title = f"CivicCast {tag} (Beta Candidate)"
    asset_names = " ".join(p.name for p in asset_paths)

    if args.dry_run:
        print(f"publish_beta_candidate: DRY RUN -- artifacts written to {out_dir}")
        print(
            "publish_beta_candidate: DRY RUN -- would publish, in this order "
            "(no tag is ever pushed by hand; un-draft creates it atomically):"
        )
        print(
            f"  1. gh release create {tag} -R {repository} --draft --target {source_sha} "
            f"--prerelease --title '{title}' --notes-file {notes_file} {asset_names}"
        )
        print(
            f"  2. gh release view {tag} -R {repository} --json assets,isDraft  "
            "(verify every asset name + size; on mismatch: gh release delete "
            f"{tag} --yes, refuse)"
        )
        print(
            f"  3. gh release edit {tag} -R {repository} --draft=false  "
            "(creates the public tag with the release)"
        )
        print("publish_beta_candidate: DRY RUN -- would update release-truth.yaml:")
        truth_summary = _dry_run_truth_summary(
            repo_root=repo_root, tag=tag, status=args.truth_status
        )
        print(truth_summary)
        print("publish_beta_candidate: DRY RUN complete. No GitHub or git remote state touched.")
        return

    # ---- Live path (never exercised by this agent against real GitHub; see
    # the module docstring and the task's Testing boundary). Order is
    # draft -> verify -> un-draft so that no public tag can exist without its
    # verified release: a draft has no tag, and un-draft creates the tag
    # atomically with the release. ----
    print(f"publish_beta_candidate: creating DRAFT release {tag} targeting {source_sha}")
    create_draft_release(
        repository=repository,
        tag=tag,
        source_sha=source_sha,
        title=title,
        notes_file=notes_file,
        asset_paths=asset_paths,
    )

    print("publish_beta_candidate: verifying draft assets (name + size)")
    verify_draft_assets(repository=repository, tag=tag, asset_paths=asset_paths)
    print("publish_beta_candidate: all assets present on the draft with matching sizes")

    print(f"publish_beta_candidate: un-drafting {tag} (creates the public tag + prerelease)")
    undraft_release(repository=repository, tag=tag)

    truth_path = repo_root / "docs" / "releases" / "release-truth.yaml"
    direct_truth = ""
    if direct_verification is not None:
        direct_truth = (
            f"direct physical-host consumer receipt {direct_receipt}; "
            "Sandbox clean-install, repair, and Beta 10 upgrade lanes not run; Gate A not run."
            if direct_verification.get("consumer_mode") == "physical-host"
            else f"direct Sandbox consumer receipt {direct_receipt}; Gate A not run."
        )
    truth_notes = (
        f"Published by publish_beta_candidate.py, artifact source {artifact_source_sha}, "
        f"tag target {source_sha}, build run {args.build_run_id}, "
        + (direct_truth or f"Gate A run {args.gate_a_run_id} (all three lanes PASS).")
    )
    summary = update_release_truth(
        truth_path=truth_path, tag=tag, status=args.truth_status, notes=truth_notes
    )
    print(summary)
    print(f"publish_beta_candidate: DONE. {tag} published as a GitHub prerelease.")


def _dry_run_truth_summary(*, repo_root: Path, tag: str, status: str) -> str:
    """Render what update_release_truth() would do, without writing it.

    Reads the real file, applies the edit in memory only, and reports the
    same summary update_release_truth() would print -- so a dry run shows
    its full intended effect without mutating anything.
    """

    import tempfile

    truth_path = repo_root / "docs" / "releases" / "release-truth.yaml"
    original = truth_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "release-truth.yaml"
        scratch.write_text(original, encoding="utf-8")
        return update_release_truth(
            truth_path=scratch,
            tag=tag,
            status=status,
            notes=f"(dry run) would be published for {tag}.",
        )


if __name__ == "__main__":
    sys.exit(main())

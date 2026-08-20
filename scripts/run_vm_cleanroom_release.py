#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Preflight seams for v1.1 VM cleanroom release proof."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VmCleanroomPlanResult:
    """Release-candidate VM install plan."""

    status: str
    install_source: str
    operator_action: str
    artifact_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class VmTargetPreflightResult:
    """VM target preflight result."""

    status: str
    operator_action: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalise_sha256(value: str) -> str:
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"invalid sha256 digest: {value}")
    return f"sha256:{digest}"


def _artifact_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("artifacts")
    if not isinstance(entries, list):
        raise ValueError("artifact manifest must contain an artifacts list")
    return [entry for entry in entries if isinstance(entry, dict)]


def plan_vm_cleanroom_install(
    *,
    artifact_manifest: Path,
    source_tree: Path,
) -> VmCleanroomPlanResult:
    """Plan a VM install from release-candidate artifacts."""

    _ = source_tree
    if not artifact_manifest.exists():
        return VmCleanroomPlanResult(
            status="failed",
            install_source="release-candidate-artifacts",
            operator_action=(
                "Build dist/release-candidate artifacts and hashes before VM cleanroom proof."
            ),
        )
    try:
        payload = json.loads(artifact_manifest.read_text(encoding="utf-8"))
        entries = _artifact_entries(payload)
        if not entries:
            raise ValueError("artifact manifest does not list any artifacts")
        hashes: list[str] = []
        missing: list[str] = []
        mismatched: list[str] = []
        for entry in entries:
            filename = entry.get("filename") or entry.get("path") or entry.get("name")
            declared_sha = entry.get("sha256") or entry.get("hash")
            if not isinstance(filename, str) or not isinstance(declared_sha, str):
                raise ValueError("artifact entries must include filename and sha256")
            expected = _normalise_sha256(declared_sha)
            artifact_path = artifact_manifest.parent / filename
            if not artifact_path.exists():
                missing.append(filename)
                continue
            actual = "sha256:" + _sha256(artifact_path)
            if actual != expected:
                mismatched.append(filename)
                continue
            hashes.append(actual)
        if missing:
            return VmCleanroomPlanResult(
                status="failed",
                install_source="release-candidate-artifacts",
                operator_action=(
                    "Release artifact manifest references missing files: "
                    + ", ".join(missing)
                    + ". Rebuild the release candidate before VM cleanroom proof."
                ),
            )
        if mismatched:
            return VmCleanroomPlanResult(
                status="failed",
                install_source="release-candidate-artifacts",
                operator_action=(
                    "Release artifact manifest hash mismatch for: "
                    + ", ".join(mismatched)
                    + ". Rebuild the release candidate from the exact artifact files."
                ),
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return VmCleanroomPlanResult(
            status="failed",
            install_source="release-candidate-artifacts",
            operator_action=f"Release artifact manifest is not verifiable: {exc}",
        )
    return VmCleanroomPlanResult(
        status="ok",
        install_source="release-candidate-artifacts",
        operator_action="VM cleanroom install will use the candidate artifact manifest.",
        artifact_hashes=tuple(hashes),
    )


def preflight_vm_target(vm_name: str) -> VmTargetPreflightResult:
    """Check whether the named VM target is available."""

    available = os.environ.get("CIVICCAST_CLEANROOM_VM") == vm_name
    if not available:
        return VmTargetPreflightResult(
            status="hardware_required",
            operator_action=f"VM target {vm_name} is unavailable; start it and rerun proof.",
        )
    return VmTargetPreflightResult(
        status="ok",
        operator_action=f"VM target {vm_name} is available.",
    )

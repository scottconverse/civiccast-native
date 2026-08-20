# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Installer package sidecar and attestation verification."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from civiccast.installer.models import (
    BootstrapMetadata,
    PackageVerificationReason,
    PackageVerificationResult,
    ServiceMetadata,
)


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 from artifact bytes."""

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_package_artifact(artifact: Path, sidecar: Path) -> PackageVerificationResult:
    """Verify an installer artifact against its sidecar and attestation pointer."""

    if not artifact.exists():
        return _blocked(
            "missing_artifact",
            f"{artifact.name} is missing; rebuild the package artifact and rerun verification.",
        )
    if not sidecar.exists():
        return _blocked(
            "missing_sidecar",
            f"{sidecar.name} is missing; rebuild the package artifact with its sidecar and attestation.",
        )

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _blocked("invalid_sidecar", f"Read a valid JSON sidecar before release: {exc}.")

    actual_sha = compute_sha256(artifact)
    expected_sha = payload.get("sha256")
    if expected_sha != actual_sha:
        return _blocked(
            "hash_mismatch",
            f"{artifact.name} SHA-256 does not match its sidecar; rebuild from clean bytes.",
            sha256=actual_sha,
        )

    # Verify the REAL attestation bundle, not the sidecar's self-report. The
    # release pipeline writes sidecars before cosign runs (their signed/
    # attestation fields describe the pre-signing moment), and a self-reported
    # boolean proves nothing. The bundle cosign attest-blob writes next to the
    # artifact carries a DSSE in-toto payload whose subject digest must equal
    # the artifact bytes we just hashed — that binding is the check.
    bundle_path = artifact.with_name(artifact.name + ".sigstore.json")
    if not bundle_path.exists():
        return _blocked(
            "missing_attestation",
            f"{bundle_path.name} is missing; download the artifact's Sigstore "
            "attestation bundle from the same release and keep it next to the package.",
            sha256=actual_sha,
        )
    bundle_defect = _attestation_bundle_defect(bundle_path, actual_sha)
    if bundle_defect is not None:
        defect_reason, defect_message = bundle_defect
        return _blocked(defect_reason, defect_message, sha256=actual_sha)
    attestation = bundle_path.name

    install_manifest = payload.get("install_manifest")
    if not isinstance(install_manifest, dict):
        return _blocked(
            "invalid_sidecar",
            "Install manifest must include service and bootstrap metadata.",
            sha256=actual_sha,
        )

    try:
        service = _service_from_manifest(install_manifest)
        additional_services = _additional_services_from_manifest(install_manifest)
        bootstrap = _bootstrap_from_manifest(install_manifest)
    except (KeyError, TypeError, ValidationError) as exc:
        return _blocked(
            "invalid_sidecar",
            f"Install manifest must include service and bootstrap metadata: {exc}.",
            sha256=actual_sha,
        )

    return PackageVerificationResult(
        status="ok",
        ready=True,
        reason="verified",
        sha256=actual_sha,
        service_metadata=service,
        additional_services=additional_services,
        bootstrap_metadata=bootstrap,
        attestation=attestation,
        next_step=(
            "Package bytes match the sidecar hash and the Sigstore attestation "
            "bundle's subject digest; service metadata is valid."
        ),
    )


def _attestation_bundle_defect(
    bundle_path: Path, artifact_sha256: str
) -> tuple[PackageVerificationReason, str] | None:
    """Check that a Sigstore bundle genuinely describes these artifact bytes.

    cosign attest-blob writes a bundle whose DSSE envelope carries a base64
    in-toto statement; that statement's subject digest names the exact bytes
    that were attested. Requiring it to equal the artifact's computed SHA-256
    binds the attestation to the file on disk. (Full certificate-chain
    verification still belongs to cosign/sigstore tooling; this check proves
    the bundle is present, well-formed, signed, and about THIS artifact —
    which the previous self-reported sidecar boolean never did.)
    """

    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (
            "invalid_attestation",
            f"{bundle_path.name} is not a readable Sigstore bundle: {exc}.",
        )

    envelope = bundle.get("dsseEnvelope") if isinstance(bundle, dict) else None
    if not isinstance(envelope, dict):
        return (
            "invalid_attestation",
            f"{bundle_path.name} has no DSSE envelope; re-download the attestation bundle.",
        )
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        return (
            "invalid_attestation",
            f"{bundle_path.name} carries no signatures; re-download the attestation bundle.",
        )

    raw_payload = envelope.get("payload")
    if not isinstance(raw_payload, str):
        return (
            "invalid_attestation",
            f"{bundle_path.name} DSSE envelope has no base64 payload; re-download the bundle.",
        )
    try:
        statement = json.loads(base64.b64decode(raw_payload, validate=True))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return (
            "invalid_attestation",
            f"{bundle_path.name} DSSE payload does not decode to an in-toto statement: {exc}.",
        )

    subjects = statement.get("subject") if isinstance(statement, dict) else None
    digests = {
        subject["digest"]["sha256"].lower()
        for subject in subjects or []
        if isinstance(subject, dict)
        and isinstance(subject.get("digest"), dict)
        and isinstance(subject["digest"].get("sha256"), str)
    }
    if not digests:
        return (
            "invalid_attestation",
            f"{bundle_path.name} names no SHA-256 subject; re-download the attestation bundle.",
        )
    if artifact_sha256.lower() not in digests:
        return (
            "attestation_mismatch",
            f"{bundle_path.name} attests different bytes (subject digest does not "
            "match this package). Re-download both files from the same release.",
        )
    return None


def _service_from_manifest(install_manifest: dict[str, Any]) -> ServiceMetadata:
    raw = install_manifest["service"]
    return _service_metadata_from_raw(raw)


def _additional_services_from_manifest(install_manifest: dict[str, Any]) -> list[ServiceMetadata]:
    raw_services = install_manifest.get("additional_services", [])
    if not isinstance(raw_services, list):
        raise TypeError("additional_services must be a list when present")
    services: list[ServiceMetadata] = []
    for raw in raw_services:
        if not isinstance(raw, dict):
            raise TypeError("additional_services entries must be objects")
        services.append(_service_metadata_from_raw(raw))
    return services


def _service_metadata_from_raw(raw: dict[str, Any]) -> ServiceMetadata:
    return ServiceMetadata(
        manager=str(raw["manager"]),
        name=str(raw.get("name") or raw.get("service_name") or "civiccast"),
        service_name=str(raw.get("service_name") or raw.get("name") or "civiccast"),
        host_service=bool(raw.get("host_service", False)),
        restart_policy=raw.get("restart_policy"),
        recovery_window_seconds=raw.get("recovery_window_seconds"),
    )


def _bootstrap_from_manifest(install_manifest: dict[str, Any]) -> BootstrapMetadata:
    raw = install_manifest["bootstrap"]
    return BootstrapMetadata(
        package_kind=str(raw["package_kind"]),
        package_manager=raw.get("package_manager"),
    )


def _blocked(
    reason: PackageVerificationReason,
    next_step: str,
    *,
    sha256: str | None = None,
) -> PackageVerificationResult:
    return PackageVerificationResult(
        status="blocked",
        ready=False,
        reason=reason,
        sha256=sha256,
        service_metadata=None,
        bootstrap_metadata=None,
        attestation=None,
        next_step=next_step,
    )

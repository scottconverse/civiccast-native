# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""civiccast CLI entry point.

Spec §8.1 enumerates the eventual subcommand surface. Sprint 0.1 ships
just `civiccast --version` and `civiccast doctor`; later rungs add
`model download`, `backup`, `restore`, `schedule diff`, `soak run`,
`syndicate test`, `archive verify`, and `subscribe send-test`.

Per ADR 0005 the CLI is built on Typer.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Annotated, Any

import typer

from civiccast._version import __version__
from civiccast.auth.store import PostgresStaffTokenStore, StaffTokenMetadata
from civiccast.auth.tokens import generate_configured_staff_token
from civiccast.cable.ndi import NdiOutputError, build_ndi_output_plan, check_ndi_runtime
from civiccast.cable.package import build_cable_file_package
from civiccast.installer.handoff import build_beta_handoff_summary
from civiccast.installer.model_bundle import build_v11_model_bundle_manifest
from civiccast.installer.model_download import download_release_models
from civiccast.installer.model_state import import_offline_model_bundle, mark_model_unavailable
from civiccast.installer.packages import verify_package_artifact
from civiccast.installer.platform import build_bootstrap_plan
from civiccast.installer.service import (
    build_first_run_plan,
    build_installer_summary,
    run_first_health_check,
)
from civiccast.native.runtime_cli import runtime_app
from civiccast.platform.hardware import HardwareProbe, probe

if TYPE_CHECKING:
    from civiccast.egress import EgressServiceReport, ScheduleSourcePlanProvider
    from civiccast.egress.store import EgressStore, SessionFactory
    from civiccast.egress.takeover_service import TakeoverService

type SignalHandler = Callable[[int, FrameType | None], Any]

app = typer.Typer(
    name="civiccast",
    help=(
        "CivicCast — open-source civic broadcast platform. "
        "Operators rarely use this CLI directly; integrators and automation "
        "pipelines use it heavily."
    ),
    no_args_is_help=False,
    add_completion=True,
    rich_markup_mode="rich",
)

installer_app = typer.Typer(
    name="installer",
    help="Installer and first-run proof helpers for CivicCast.",
    no_args_is_help=True,
)
model_app = typer.Typer(
    name="model",
    help="Model bundle helpers for online and air-gapped installs.",
    no_args_is_help=True,
)
cert_app = typer.Typer(
    name="cert",
    help="Local CA and mTLS service certificate helpers.",
    no_args_is_help=True,
)
token_app = typer.Typer(
    name="token",
    help="Staff token lifecycle helpers for operator identity.",
    no_args_is_help=True,
)
cable_app = typer.Typer(
    name="cable",
    help="Cable helpers for PEG/headend handoff.",
    no_args_is_help=True,
)
activitypub_app = typer.Typer(
    name="activitypub",
    help="ActivityPub federation key and configuration helpers.",
    no_args_is_help=True,
)
egress_app = typer.Typer(
    name="egress",
    help="Channel egress worker helpers for local SRT, file, and future headend outputs.",
    no_args_is_help=True,
)
live_takeover_app = typer.Typer(
    name="live-takeover",
    help="Operator live-takeover helpers (S5): cut a channel to a live source and return it.",
    no_args_is_help=True,
)
media_app = typer.Typer(
    name="media",
    help="Media-library maintenance helpers (4.0 scope item 5).",
    no_args_is_help=True,
)
dr_app = typer.Typer(
    name="dr",
    help="Disaster-recovery drills (0.5.0): real backup/restore/crash-recovery proof.",
    no_args_is_help=True,
)
app.add_typer(installer_app)
app.add_typer(model_app)
app.add_typer(cert_app)
app.add_typer(token_app)
app.add_typer(cable_app)
app.add_typer(activitypub_app)
app.add_typer(egress_app)
app.add_typer(live_takeover_app)
app.add_typer(media_app)
app.add_typer(dr_app)
# WS4 dual-runtime exclusion guard (slice:ws4-dual-runtime-guard): runtime_app
# lives in civiccast/native/runtime_cli.py (not defined here like the other
# sub-apps) because it is also registered standalone as the `civiccast-runtime`
# console script -- see that module's docstring for the dual-registration
# rationale.
app.add_typer(runtime_app)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"civiccast {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Print the CivicCast version and exit.",
        ),
    ] = None,
) -> None:
    """CivicCast top-level CLI.

    Without arguments, prints help. Use `--version` to print just the
    version string. Subcommands cover diagnostics, model management,
    backup/restore, and operator automation surfaces.
    """
    if ctx.invoked_subcommand is None and version is None:
        typer.echo(ctx.get_help())


@app.command()
def doctor(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit the probe as JSON (one object, machine-readable).",
        ),
    ] = False,
    disk: Annotated[
        str | None,
        typer.Option(
            "--disk",
            help="Filesystem path to probe for disk space (defaults to home directory).",
        ),
    ] = None,
) -> None:
    """Probe local hardware and report CPU, RAM, disk, GPU, OS, recommended tier.

    The probe data is identical to what the `/api/hardware` endpoint
    serves; this command is the operator-friendly view of it.
    """
    from pathlib import Path

    result = probe(disk_path=Path(disk) if disk else None)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _render_probe_human(result)


@installer_app.command("plan")
def installer_plan(
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            help="Deployment profile to plan. Default: public-meetings.",
        ),
    ] = "public-meetings",
    recommended_tier: Annotated[
        str,
        typer.Option(
            "--recommended-tier",
            help="Tier from civiccast doctor or the installer hardware probe.",
        ),
    ] = "tier-1",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Print the first-run installer plan."""

    from civiccast.ai_models.models import detect_summary_model_default
    from civiccast.installer.service import _probed_summary_ram_gb

    summary_default = detect_summary_model_default(_probed_summary_ram_gb())
    plan = build_first_run_plan(
        profile=profile,  # type: ignore[arg-type]
        recommended_tier=recommended_tier,
        summary_default_key=summary_default,
    )
    if json_output:
        typer.echo(plan.model_dump_json(indent=2))
        return

    typer.echo(f"CivicCast first-run plan: {plan.profile}")
    typer.echo(f"Recommended tier: {plan.recommended_tier}")
    typer.echo(f"Cloud fallback default: {plan.cloud_fallback_default}")
    typer.echo(f"Target time to first broadcast: {plan.time_to_first_broadcast_minutes} minutes")
    for index, step in enumerate(plan.steps, start=1):
        typer.echo(f"{index}. {step.title} [{step.status}]")
        typer.echo(f"   {step.summary}")
        typer.echo(f"   Next: {step.next_step}")


@installer_app.command("health-check")
def installer_health_check(
    profile: Annotated[
        str,
        typer.Option("--profile", help="Deployment profile to verify."),
    ] = "public-meetings",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run fail-closed first-run health checks for publish surfaces."""

    report = run_first_health_check(profile=profile)  # type: ignore[arg-type]
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return

    typer.echo(f"CivicCast first-run health: {'READY' if report.ready else 'NOT READY'}")
    for check in report.checks:
        typer.echo(f"- {check.label}: {check.state}")
        typer.echo(f"  {check.message}")
        typer.echo(f"  Next: {check.next_step}")
    if report.ready:
        typer.echo("You are streaming.")


@installer_app.command("platform-plan")
def installer_platform_plan(
    os_family: Annotated[
        str,
        typer.Option(
            "--os-family",
            help=(
                "Platform family: linux or macos. Windows deployment readiness "
                "is decided separately, by the native station's own activation "
                "state (civiccast.installer.service), not this generic plan."
            ),
        ),
    ] = "linux",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Print the cross-platform installer bootstrap plan."""

    plan = build_bootstrap_plan(os_family=os_family, detected_tools={})  # type: ignore[arg-type]
    if json_output:
        typer.echo(plan.model_dump_json(indent=2))
        return
    typer.echo(f"{plan.os_family}: {plan.status}")
    typer.echo(f"Runtime: {plan.runtime}")
    typer.echo(f"Next: {plan.next_step}")


@installer_app.command("verify-package")
def installer_verify_package(
    artifact: Annotated[Path, typer.Option("--artifact", help="Package artifact path.")],
    sidecar: Annotated[Path, typer.Option("--sidecar", help="Package sidecar JSON path.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Verify package bytes, sidecar hash, signed install manifest, and attestation."""

    result = verify_package_artifact(artifact, sidecar)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"Package verification: {result.status}")
    typer.echo(f"Next: {result.next_step}")


@cable_app.command("package")
def cable_package(
    asset_id: Annotated[
        str,
        typer.Option("--asset-id", help="CivicCast asset id for the recording."),
    ],
    title: Annotated[
        str,
        typer.Option("--title", help="Human-readable meeting or program title."),
    ],
    media: Annotated[
        Path,
        typer.Option("--media", help="Local source media file to include in the package."),
    ],
    captions: Annotated[
        Path,
        typer.Option("--captions", help="Caption sidecar file, usually WebVTT or SRT."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Directory where the cable package is written."),
    ],
    portal_url: Annotated[
        str | None,
        typer.Option("--portal-url", help="Optional CivicCast portal URL for the manifest."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Create a local cable file package from real media and captions."""

    result = build_cable_file_package(
        asset_id=asset_id,
        title=title,
        media_path=media,
        caption_path=captions,
        output_dir=output_dir,
        portal_url=portal_url,
    )
    payload = {
        "status": result.status,
        "package_dir": str(result.package_dir),
        "zip_path": str(result.zip_path),
        "verification_hash": result.verification_hash,
        "manifest_path": str(result.manifest_path),
        "next_step": result.next_step,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"Cable file package: {result.status.upper()}")
    typer.echo(f"ZIP: {result.zip_path}")
    typer.echo(f"Hash: {result.verification_hash}")
    typer.echo(f"Next: {result.next_step}")


@cable_app.command("ndi-check")
def cable_ndi_check(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Check whether this host can output NDI through FFmpeg."""

    result = check_ndi_runtime()
    payload = {
        "status": result.status,
        "supported_muxer": result.supported_muxer,
        "ffmpeg_detected": result.ffmpeg_detected,
        "ndi_runtime_detected": result.ndi_runtime_detected,
        "ndi_sdk_detected": result.ndi_sdk_detected,
        "ndi_sender_detected": result.ndi_sender_detected,
        "ndi_sender_path": str(result.ndi_sender_path) if result.ndi_sender_path else None,
        "next_step": result.next_step,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"NDI output readiness: {result.status}")
    if result.supported_muxer:
        typer.echo(f"FFmpeg NDI muxer: {result.supported_muxer}")
    typer.echo(f"NDI runtime detected: {'yes' if result.ndi_runtime_detected else 'no'}")
    typer.echo(f"NDI SDK build inputs detected: {'yes' if result.ndi_sdk_detected else 'no'}")
    typer.echo(
        f"Local FFmpeg-to-NDI sender detected: {'yes' if result.ndi_sender_detected else 'no'}"
    )
    if result.ndi_sender_path:
        typer.echo(f"Local sender path: {result.ndi_sender_path}")
    typer.echo(f"Next: {result.next_step}")


@cable_app.command("ndi-plan")
def cable_ndi_plan(
    media: Annotated[
        Path,
        typer.Option("--media", help="Local source media file to send to NDI."),
    ],
    ndi_name: Annotated[
        str,
        typer.Option("--ndi-name", help="NDI channel name shown to receivers."),
    ],
    muxer: Annotated[
        str,
        typer.Option(
            "--muxer",
            help="FFmpeg NDI muxer to target after `civiccast cable ndi-check`.",
        ),
    ] = "libndi_newtek",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Build the FFmpeg command plan for local-file-to-NDI output."""

    try:
        plan = build_ndi_output_plan(source_media=media, ndi_name=ndi_name, muxer=muxer)
    except NdiOutputError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "blocked",
                        "error": str(exc),
                        "next_step": "Fix the NDI plan input and rerun `civiccast cable ndi-plan`.",
                    },
                    indent=2,
                )
            )
        else:
            typer.echo("NDI output plan: BLOCKED")
            typer.echo(str(exc))
            typer.echo("Next: Fix the NDI plan input and rerun `civiccast cable ndi-plan`.")
        raise typer.Exit(1) from exc
    payload = {
        "status": plan.status,
        "source_media": str(plan.source_media),
        "ndi_name": plan.ndi_name,
        "ffmpeg_args": plan.ffmpeg_args,
        "proof_boundary": plan.proof_boundary,
        "next_step": plan.next_step,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"NDI output plan: {plan.status.upper()}")
    typer.echo(f"Channel: {plan.ndi_name}")
    typer.echo("FFmpeg args:")
    typer.echo(" ".join(plan.ffmpeg_args))
    typer.echo(f"Next: {plan.next_step}")


@installer_app.command("summary")
def installer_summary(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Print fail-closed cross-platform installer readiness."""

    summary = build_installer_summary()
    if json_output:
        typer.echo(summary.model_dump_json(indent=2))
        return
    if not summary.ready:
        headline = "NOT READY"
    else:
        # Readiness is computed over the required lanes, so any lane that is
        # still not ready here is an optional capability CivicCast runs
        # without. Name it: "running, but cannot process video" and "broken"
        # must not print the same headline.
        unavailable = [lane.label for lane in summary.lanes if not lane.ready]
        headline = (
            "READY"
            if not unavailable
            else f"READY (optional capability unavailable: {', '.join(unavailable)})"
        )
    typer.echo(f"CivicCast installer: {headline}")
    for lane in summary.lanes:
        typer.echo(f"- {lane.label}: {lane.status}")
        typer.echo(f"  Next: {lane.next_step}")


@installer_app.command("beta-handoff")
def installer_beta_handoff(
    release_manifest: Annotated[
        Path | None,
        typer.Option(
            "--release-manifest",
            help="Release artifact manifest to evaluate for tester acquisition.",
        ),
    ] = None,
    clean_windows_evidence: Annotated[
        Path | None,
        typer.Option(
            "--clean-windows-evidence",
            help="Clean Windows install proof JSON to include in the handoff status.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Print fail-closed beta tester handoff readiness."""

    summary = build_beta_handoff_summary(
        release_manifest=release_manifest,
        clean_windows_evidence=clean_windows_evidence,
    )
    if json_output:
        typer.echo(summary.model_dump_json(indent=2))
        return
    typer.echo(f"CivicCast beta handoff: {'READY' if summary.ready else 'NOT READY'}")
    if summary.install_command:
        typer.echo(f"Install command: {summary.install_command}")
    for lane in summary.lanes:
        typer.echo(f"- {lane.label}: {lane.status}")
        typer.echo(f"  {lane.message}")
        typer.echo(f"  Next: {lane.operator_action}")
        typer.echo(f"  Evidence: {lane.evidence_target}")


@model_app.command("download")
def model_download(
    offline_bundle: Annotated[
        bool,
        typer.Option(
            "--offline-bundle",
            help="Emit the air-gapped model bundle manifest instead of downloading.",
        ),
    ] = False,
    profile: Annotated[
        str,
        typer.Option("--profile", help="Deployment profile for the bundle manifest."),
    ] = "public-meetings",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the model download plan without pulling models."),
    ] = False,
    cache_dir: Annotated[
        str | None,
        typer.Option("--cache-dir", help="Directory for the faster-whisper model snapshot."),
    ] = None,
    bundle_dir: Annotated[
        str | None,
        typer.Option(
            "--bundle-dir",
            help=(
                "Directory containing offline model artifacts. Required with "
                "--offline-bundle so the manifest can emit real SHA-256 values."
            ),
        ),
    ] = None,
) -> None:
    """Download the real local AI models or print the offline bundle manifest."""

    if not offline_bundle:
        report = download_release_models(
            cache_dir=Path(cache_dir) if cache_dir else None,
            dry_run=dry_run,
        )
        if json_output:
            payload = {
                "status": report.status,
                "items": [item.__dict__ for item in report.items],
            }
            typer.echo(json.dumps(payload, indent=2))
            return
        typer.echo(f"CivicCast model download: {report.status.upper()}")
        for item in report.items:
            typer.echo(f"- {item.id}: {item.status}")
            typer.echo(f"  {item.operator_action}")
        return

    if bundle_dir is None:
        raise typer.BadParameter(
            "--bundle-dir is required with --offline-bundle so CivicCast can "
            "hash the actual offline model artifacts instead of emitting a plan."
        )
    manifest = build_v11_model_bundle_manifest(Path(bundle_dir))
    missing = [model.name for model in manifest.models if not model.sha256]
    if missing:
        raise typer.BadParameter(
            "Offline bundle directory is missing model artifacts: "
            + ", ".join(missing)
            + ". Copy the model bundle into --bundle-dir and rerun."
        )
    items = [
        {
            "id": model.name,
            "label": model.name,
            "filename": model.filename,
            "sha256": model.sha256,
            "size_bytes": model.size_bytes,
            "required": True,
        }
        for model in manifest.models
    ]
    offline_payload: dict[str, object] = {
        "profile": profile,
        "bundle_name": f"civiccast-models-{profile}-v{__version__}.tar",
        "bundle_dir": str(manifest.output_dir),
        "estimated_size_gb": round(
            sum(model.size_bytes for model in manifest.models) / 1_000_000_000,
            2,
        ),
        "items": items,
    }
    if json_output:
        typer.echo(json.dumps(offline_payload, indent=2))
        return

    typer.echo(f"Offline bundle: {offline_payload['bundle_name']}")
    typer.echo(f"Bundle directory: {offline_payload['bundle_dir']}")
    typer.echo(f"Estimated size: {offline_payload['estimated_size_gb']} GB")
    for bundle_item in items:
        typer.echo(f"- {bundle_item['label']}: {bundle_item['filename']}")
        typer.echo(f"  sha256:{bundle_item['sha256']}")


@model_app.command("state")
def model_state(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Print installer-facing model proof state."""

    item = mark_model_unavailable("gemma4:e4b", reason="provider proof not recorded")
    if json_output:
        typer.echo(json.dumps({"ready": False, "items": [item.model_dump()]}, indent=2))
        return
    typer.echo(f"{item.name}: {item.status}")
    typer.echo(f"Next: {item.next_step}")


@cert_app.command("rotate")
def cert_rotate(
    identity: Annotated[str, typer.Argument(help="Known service identity to rotate.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Rotate one local-CA service certificate without printing private keys."""

    import os

    from civiccast.certs import authority
    from civiccast.certs.readiness import default_cert_root

    configured_root = os.getenv("CIVICCAST_CERT_ROOT")
    root = Path(configured_root) if configured_root is not None else default_cert_root()
    try:
        result = authority.rotate_service_certificate(root, identity)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    if hasattr(result, "model_dump_json"):
        if json_output:
            typer.echo(result.model_dump_json(indent=2))
            return
        payload = result.model_dump()
    else:
        payload = dict(result)
        if json_output:
            typer.echo(json.dumps(payload, indent=2, default=str))
            return
    typer.echo(f"Rotated certificate for {payload['service_identity']}.")
    typer.echo(f"Fingerprint: {payload['fingerprint_sha256']}")


@model_app.command("import-offline")
def model_import_offline(
    bundle_dir: Annotated[Path, typer.Option("--bundle-dir", help="Offline bundle directory.")],
    expected: Annotated[
        list[str],
        typer.Option(
            "--expected",
            help="Expected filename=sha256 pair. Repeat for each model artifact.",
        ),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Verify an offline model bundle from real file hashes."""

    expected_hashes = dict(pair.split("=", 1) for pair in expected)
    result = import_offline_model_bundle(bundle_dir=bundle_dir, expected_hashes=expected_hashes)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"Offline model import: {result.status}")
    typer.echo(f"Next: {result.next_step}")


_PROVIDER_KEY_ENV = "CIVICCAST_PROVIDER_API_KEY"


@model_app.command("set-provider-key")
def model_set_provider_key(
    provider: Annotated[
        str,
        typer.Argument(help="Cloud provider to store a key for: ollama-cloud or openrouter."),
    ],
    key: Annotated[
        str | None,
        typer.Option(
            "--key",
            help=(
                "The provider API key. Omit to read it from the "
                f"{_PROVIDER_KEY_ENV} environment variable (preferred for headless/air-gap "
                "installs so the secret never appears in shell history)."
            ),
        ),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Remove the stored key for the provider instead of saving."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Store (or clear) a cloud-provider API key for the hosted AI tiers (S13 D13).

    Headless/air-gap counterpart to the staff API: maps the provider to its keyring
    handle and writes the key write-only — the key is NEVER printed or logged, only a
    stored/not-stored line. Selecting a hosted tier (with consent) then works offline.
    """

    from civiccast.ai_models.secrets import (
        ProviderSecretStoreError,
        credential_ref_for_provider,
        delete_provider_secret,
        save_provider_secret,
    )

    if provider not in ("ollama-cloud", "openrouter"):
        typer.echo("Unknown provider. Choose ollama-cloud or openrouter.")
        raise typer.Exit(1)
    ref = credential_ref_for_provider(provider)  # type: ignore[arg-type]

    try:
        if clear:
            delete_provider_secret(ref)
            stored = False
        else:
            secret = key if key is not None else os.environ.get(_PROVIDER_KEY_ENV)
            secret = (secret or "").strip()
            if not secret or any(ord(ch) < 32 for ch in secret):
                typer.echo(
                    "Provide the key via --key or the "
                    f"{_PROVIDER_KEY_ENV} environment variable (non-empty, single line)."
                )
                raise typer.Exit(1)
            save_provider_secret(ref, secret)
            stored = True
    except ProviderSecretStoreError as exc:
        typer.echo(f"Could not update the provider key: {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps({"provider": provider, "stored": stored}, indent=2))
        return
    action = "cleared" if clear else "stored"
    typer.echo(f"Provider key for {provider}: {action}.")


def _default_egress_work_dir() -> Path:
    from civiccast.egress.automation import default_egress_work_dir

    return default_egress_work_dir()


def _resolve_egress_database_url() -> str:
    """Return configured or installer-managed storage for egress workers."""

    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url
    from civiccast.installer.storage import ManagedStorageError, load_managed_database_url

    try:
        managed_url = load_managed_database_url()
    except ManagedStorageError as exc:
        raise typer.BadParameter(
            "CivicCast storage is not ready. Open CivicCast Setup and choose "
            "Prepare storage before starting channel egress."
        ) from exc
    if managed_url is None:
        raise typer.BadParameter(
            "CivicCast storage is not ready. Open CivicCast Setup and choose "
            "Prepare storage before starting channel egress."
        )
    os.environ["DATABASE_URL"] = managed_url
    return managed_url


def _bind_egress_database(database_url: str) -> None:
    """Bind the CivicCast DB session factory for a CLI-owned egress worker."""

    from sqlalchemy import create_engine, event

    from civiccast.db import bind_engine, connect_options
    from civiccast.db.url import normalize_database_url

    database_url = normalize_database_url(database_url)

    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 15.0},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=15000")
            finally:
                cursor.close()

        bind_engine(engine.execution_options(schema_translate_map={"civiccast": None}))
        return
    bind_engine(
        create_engine(
            database_url, future=True, pool_pre_ping=True, **connect_options(database_url)
        )
    )


def _build_cli_session_factory() -> SessionFactory:
    """Build a context-managed DB session factory for CLI-owned stores."""
    from sqlalchemy.orm import Session

    from civiccast.db import get_session

    @contextmanager
    def _session_factory() -> Iterator[Session]:
        gen = get_session()
        try:
            session = next(gen)
        except RuntimeError as exc:
            raise typer.BadParameter(
                "CivicCast storage is not ready. Open CivicCast Setup and choose "
                "Prepare storage before starting channel egress."
            ) from exc
        try:
            yield session
        finally:
            with suppress(StopIteration):
                next(gen)

    return _session_factory


def _build_egress_store() -> EgressStore:
    """Build the durable egress store from the process-wide DB session dependency."""

    from civiccast.egress import PostgresEgressStore

    return PostgresEgressStore(_build_cli_session_factory())


def _build_egress_source_plan_provider() -> ScheduleSourcePlanProvider:
    """Build the schedule-to-source adapter for a CLI-owned egress worker."""

    from civiccast.egress import ScheduleSourcePlanProvider
    from civiccast.schedule.models import SCHEDULE_STATE_PUBLISHED
    from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore

    session_factory = _build_cli_session_factory()
    asset_store = PostgresAssetStore(session_factory)
    schedule_store = PostgresScheduleStore(session_factory)
    return ScheduleSourcePlanProvider(
        schedule_items_provider=lambda channel_id: schedule_store.list(
            channel_id=channel_id,
            states=(SCHEDULE_STATE_PUBLISHED,),
        ),
        asset_resolver=asset_store.get_staff_row,
    )


@contextmanager
def _egress_stop_signal_context(*, enabled: bool) -> Iterator[Callable[[], bool]]:
    """Expose SIGTERM/SIGINT as a service-loop stop predicate."""

    stop_requested = False

    def _request_stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop_requested
        stop_requested = True

    def _should_stop() -> bool:
        return stop_requested

    if not enabled:
        yield _should_stop
        return

    previous_handlers: dict[int, signal.Handlers | SignalHandler | int | None] = {}
    for signal_name in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signal_name, None)
        if signum is None:
            continue
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, _request_stop)
    try:
        yield _should_stop
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _run_egress_service(
    *,
    channel_ids: tuple[str, ...],
    work_dir: Path,
    poll_seconds: float,
    once: bool,
) -> EgressServiceReport:
    from civiccast.egress import EgressDaemon, EgressService, SourcePreparer
    from civiccast.egress.bulletin_filler import (
        build_board_overlay_provider,
        build_filler_source_provider,
    )
    from civiccast.egress.engine_select import build_encoder_strategy

    _bind_egress_database(_resolve_egress_database_url())
    store = _build_egress_store()
    source_plan_provider = _build_egress_source_plan_provider()
    daemon = EgressDaemon(
        store,
        work_dir=work_dir,
        source_plan_provider=source_plan_provider,
        # CA-3: same per-channel fill policy as the in-app automation driver.
        fallback_source_provider=build_filler_source_provider(
            _build_cli_session_factory(), work_dir=work_dir
        ),
        # S15 §5 CG-lite: active-board raster composited by the engine overlay leg.
        cg_overlay_provider=build_board_overlay_provider(
            _build_cli_session_factory(), work_dir=work_dir
        ),
        source_preparer=SourcePreparer(work_dir=work_dir).prepare,
        resolve_secret=lambda ref: os.environ.get(ref),
        # S15: the GStreamer engine (default) or ffmpeg-concat (legacy), per
        # CIVICCAST_EGRESS_ENGINE.
        encoder_strategy=build_encoder_strategy(),
    )
    with _egress_stop_signal_context(enabled=not once) as should_stop:
        service = EgressService(
            daemon,
            channel_ids=channel_ids,
            poll_seconds=poll_seconds,
            should_stop=should_stop if not once else None,
        )
        return service.run(max_iterations=1 if once else None)


def _trim_egress_health(*, cutoff: datetime) -> int:
    _bind_egress_database(_resolve_egress_database_url())
    store = _build_egress_store()
    return store.trim_health_before(cutoff)


@egress_app.command("run")
def egress_run(
    channel_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--channel-id",
            help="Channel id to poll. Repeat this option for more than one channel.",
        ),
    ] = None,
    work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir",
            help="Directory for temporary egress plans and generated slate files.",
        ),
    ] = None,
    poll_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", help="Seconds to wait between polling passes."),
    ] = 2.0,
    once: Annotated[
        bool,
        typer.Option("--once", help="Poll once, print a report, and exit."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run the channel egress worker loop."""

    normalized_channels = tuple(
        channel_id.strip() for channel_id in (channel_ids or []) if channel_id.strip()
    )
    if not normalized_channels:
        raise typer.BadParameter("At least one --channel-id value is required.")
    if poll_seconds < 0:
        raise typer.BadParameter("--poll-seconds must be zero or greater.")
    resolved_work_dir = (work_dir or _default_egress_work_dir()).expanduser().resolve()
    report = _run_egress_service(
        channel_ids=normalized_channels,
        work_dir=resolved_work_dir,
        poll_seconds=poll_seconds,
        once=once,
    )
    payload = {
        "channel_ids": list(report.channel_ids),
        "iterations": report.iterations,
        "commands_processed": report.commands_processed,
        "stopped_by": report.stopped_by,
        "last_iteration_at": (
            report.last_iteration_at.isoformat() if report.last_iteration_at else None
        ),
        "work_dir": str(resolved_work_dir),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo("CivicCast egress worker ran.")
    typer.echo(f"Channels: {', '.join(report.channel_ids)}")
    typer.echo(f"Polling passes: {report.iterations}")
    typer.echo(f"Commands processed: {report.commands_processed}")
    typer.echo(f"Stopped by: {report.stopped_by}")
    typer.echo(f"Work directory: {resolved_work_dir}")


@egress_app.command("verify")
def egress_verify(
    channel_id: Annotated[
        str,
        typer.Option("--channel-id", help="Channel whose headend stream to verify."),
    ],
    seconds: Annotated[
        int,
        typer.Option("--seconds", help="How long to capture the live stream."),
    ] = 10,
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Directory for probe artifacts."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run a bounded TSDuck verification of the channel's headend stream (CA-7).

    Exits 1 on a failing verdict so the 24-hour acceptance run can loop it.
    """

    from civiccast.egress.compliance import run_compliance_probe
    from civiccast.egress.store import PostgresEgressStore

    if seconds <= 0:
        raise typer.BadParameter("--seconds must be greater than zero.")
    store = PostgresEgressStore(_build_cli_session_factory())
    config = store.get_config(channel_id)
    if config is None:
        raise typer.BadParameter(f"No egress config for channel {channel_id!r}.")
    resolved_work_dir = (work_dir or _default_egress_work_dir()).expanduser().resolve()
    try:
        result = run_compliance_probe(config, seconds=seconds, work_dir=resolved_work_dir)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Channel {channel_id} -> {result.destination}")
        typer.echo(f"Verdict: {result.verdict}")
        if result.detail:
            typer.echo(f"Detail: {result.detail}")
        for check in result.checks:
            typer.echo(f"  {check.check}: {check.status} - {check.detail}")
        for line in result.not_claimed:
            typer.echo(f"  (boundary) {line}")
    if result.verdict != "pass":
        raise typer.Exit(1)


@egress_app.command("trim-health")
def egress_trim_health(
    older_than_days: Annotated[
        int,
        typer.Option(
            "--older-than-days",
            help="Delete egress health telemetry older than this many days.",
        ),
    ] = 30,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the cutoff without deleting health telemetry."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Trim old egress health telemetry."""

    if older_than_days <= 0:
        raise typer.BadParameter("--older-than-days must be greater than zero.")
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    deleted_count = None if dry_run else _trim_egress_health(cutoff=cutoff)
    payload = {
        "older_than_days": older_than_days,
        "cutoff": cutoff.isoformat(),
        "deleted_count": deleted_count,
        "dry_run": dry_run,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    if dry_run:
        typer.echo(f"Would trim egress health telemetry before {cutoff.isoformat()}.")
        return
    typer.echo(f"Trimmed {deleted_count} egress health telemetry samples.")


@egress_app.command("continuity-proof")
def egress_continuity_proof(
    source_plan_json: Annotated[
        Path,
        typer.Option(
            "--source-plan-json",
            help="JSON file containing the ordered egress source plan to prove.",
        ),
    ],
    config_json: Annotated[
        Path,
        typer.Option("--config-json", help="JSON file containing the egress channel config."),
    ],
    output_path: Annotated[
        Path,
        typer.Option("--output-path", help="MPEG-TS FileSink output path for this proof run."),
    ],
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Directory for temporary continuity proof files."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run a FileSink continuity and loudness proof for one egress source plan."""

    from civiccast.egress import EgressConfig, EgressSourcePlan, run_filesink_continuity_proof

    try:
        source_plan = EgressSourcePlan.model_validate_json(
            source_plan_json.read_text(encoding="utf-8")
        )
        config = EgressConfig.model_validate_json(config_json.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(f"Could not read proof input file: {exc}") from exc
    resolved_work_dir = (work_dir or _default_egress_work_dir()).expanduser().resolve()
    proof = run_filesink_continuity_proof(
        source_plan=source_plan,
        config=config,
        output_path=output_path.expanduser().resolve(),
        work_dir=resolved_work_dir,
    )
    if json_output:
        typer.echo(proof.model_dump_json(indent=2))
        raise typer.Exit(0 if proof.status == "PASS" else 1)
    typer.echo(f"Egress continuity proof: {proof.status}")
    typer.echo(f"Channel: {proof.channel_id}")
    typer.echo(f"Boundaries crossed: {proof.boundary_count}")
    typer.echo(
        "Duration: "
        f"{proof.measured_duration_seconds}s measured / "
        f"{proof.expected_duration_seconds}s expected"
    )
    typer.echo(
        "Loudness: "
        f"{proof.loudness_status} "
        f"({proof.measured_lufs} LUFS, target {proof.loudness_target_lufs:g})"
    )
    if proof.blocker:
        typer.echo(f"Blocker: {proof.blocker}")
    typer.echo(f"Next: {proof.next_step}")
    raise typer.Exit(0 if proof.status == "PASS" else 1)


@egress_app.command("srt-continuity-proof")
def egress_srt_continuity_proof(
    source_plan_json: Annotated[
        Path,
        typer.Option(
            "--source-plan-json",
            help="JSON file containing the ordered egress source plan to prove.",
        ),
    ],
    config_json: Annotated[
        Path,
        typer.Option("--config-json", help="JSON file containing the egress channel config."),
    ],
    sender_url: Annotated[
        str,
        typer.Option("--sender-url", help="Secret-free SRT caller URL for the sender."),
    ],
    receiver_url: Annotated[
        str,
        typer.Option("--receiver-url", help="Secret-free SRT listener URL for the receiver."),
    ],
    receiver_output_path: Annotated[
        Path,
        typer.Option("--receiver-output-path", help="MPEG-TS file written by the receiver."),
    ],
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Directory for temporary continuity proof files."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run a representative SRT receiver continuity and loudness proof."""

    from civiccast.egress import (
        EgressConfig,
        EgressSourcePlan,
        run_srt_receiver_continuity_proof,
    )

    try:
        source_plan = EgressSourcePlan.model_validate_json(
            source_plan_json.read_text(encoding="utf-8")
        )
        config = EgressConfig.model_validate_json(config_json.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(f"Could not read proof input file: {exc}") from exc
    resolved_work_dir = (work_dir or _default_egress_work_dir()).expanduser().resolve()
    proof = run_srt_receiver_continuity_proof(
        source_plan=source_plan,
        config=config,
        sender_url=sender_url,
        receiver_url=receiver_url,
        receiver_output_path=receiver_output_path.expanduser().resolve(),
        work_dir=resolved_work_dir,
    )
    if json_output:
        typer.echo(proof.model_dump_json(indent=2))
        raise typer.Exit(0 if proof.status == "PASS" else 1)
    typer.echo(f"Egress SRT continuity proof: {proof.status}")
    typer.echo(f"Channel: {proof.channel_id}")
    typer.echo(f"Boundaries crossed: {proof.boundary_count}")
    typer.echo(f"Receiver return code: {proof.receiver_returncode}")
    typer.echo(
        "Duration: "
        f"{proof.measured_duration_seconds}s measured / "
        f"{proof.expected_duration_seconds}s expected"
    )
    typer.echo(
        "Loudness: "
        f"{proof.loudness_status} "
        f"({proof.measured_lufs} LUFS, target {proof.loudness_target_lufs:g})"
    )
    if proof.blocker:
        typer.echo(f"Blocker: {proof.blocker}")
    typer.echo(f"Next: {proof.next_step}")
    raise typer.Exit(0 if proof.status == "PASS" else 1)


@egress_app.command("caption-decode-proof")
def egress_caption_decode_proof(
    channel_id: Annotated[
        str,
        typer.Option("--channel-id", help="Channel id measured during the caption proof."),
    ],
    emitted_stream_path: Annotated[
        Path,
        typer.Option("--emitted-stream", help="Emitted stream file that was decoded."),
    ],
    expected_captions_path: Annotated[
        Path,
        typer.Option("--expected-captions", help="Expected WebVTT or SRT caption file."),
    ],
    decoded_captions_path: Annotated[
        Path,
        typer.Option(
            "--decoded-captions", help="Decoded WebVTT or SRT file from the emitted stream."
        ),
    ],
    decoder_name: Annotated[
        str,
        typer.Option("--decoder-name", help="Name of the decoder used to read the emitted stream."),
    ] = "ffmpeg-cc-decode",
    timing_tolerance_seconds: Annotated[
        float,
        typer.Option(
            "--timing-tolerance-seconds",
            help="Allowed start/end timing difference for each decoded caption cue.",
        ),
    ] = 0.75,
    output_path: Annotated[
        Path | None,
        typer.Option("--output-path", help="Optional JSON evidence file to write."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Compare decoded emitted-stream captions with expected captions."""

    from civiccast.egress import evaluate_caption_decode_back, load_caption_cues_from_timed_text

    try:
        resolved_emitted_stream_path = emitted_stream_path.expanduser().resolve()
        if not resolved_emitted_stream_path.exists():
            raise typer.BadParameter(
                f"Emitted stream file does not exist: {resolved_emitted_stream_path}"
            )
        expected_cues = load_caption_cues_from_timed_text(
            expected_captions_path.expanduser().resolve(),
            source_id="expected",
        )
        decoded_cues = load_caption_cues_from_timed_text(
            decoded_captions_path.expanduser().resolve(),
            source_id="decoded",
        )
        proof = evaluate_caption_decode_back(
            channel_id=channel_id,
            emitted_stream_path=resolved_emitted_stream_path,
            expected_cues=expected_cues,
            decoded_cues=decoded_cues,
            decoder_name=decoder_name,
            timing_tolerance_seconds=timing_tolerance_seconds,
        )
    except OSError as exc:
        raise typer.BadParameter(f"Could not read caption proof input file: {exc}") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output_path is not None:
        resolved_output_path = output_path.expanduser().resolve()
        resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_output_path.write_text(proof.model_dump_json(indent=2), encoding="utf-8")
    if json_output:
        typer.echo(proof.model_dump_json(indent=2))
        raise typer.Exit(0 if proof.status == "PASS" else 1)
    typer.echo(f"Egress caption decode-back proof: {proof.status}")
    typer.echo(f"Channel: {proof.channel_id}")
    typer.echo(f"Caption status: {proof.caption_status}")
    typer.echo(f"Expected cues: {proof.expected_cue_count}")
    typer.echo(f"Decoded cues: {proof.decoded_cue_count}")
    typer.echo(f"Matched cues: {proof.matched_cue_count}")
    typer.echo(f"Max timing delta: {proof.max_timing_delta_seconds:g}s")
    if output_path is not None:
        typer.echo(f"Evidence: {output_path.expanduser().resolve()}")
    if proof.blocker:
        typer.echo(f"Blocker: {proof.blocker}")
    raise typer.Exit(0 if proof.status == "PASS" else 1)


def _build_takeover_service() -> TakeoverService:
    """Build a live-takeover service for a CLI-owned session (binds the DB).

    Mirrors ``app._resolve_takeover_service``: the audit store + the egress
    command queue + a live ingest-plan provider built from the channel's enabled
    relay configs.
    """
    from civiccast.egress import PostgresEgressStore
    from civiccast.egress.takeover_service import TakeoverService
    from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
    from civiccast.live.relay import build_ingest_plan
    from civiccast.live.store import LiveRelayConfigStore

    _bind_egress_database(_resolve_egress_database_url())
    session_factory = _build_cli_session_factory()
    relay_store = LiveRelayConfigStore(session_factory)

    def _ingest_plan(channel_id: str):  # type: ignore[no-untyped-def]
        return build_ingest_plan(channel_id, relay_store.list(channel_id=channel_id, enabled=True))

    return TakeoverService(
        PostgresTakeoverAuditStore(session_factory),
        PostgresEgressStore(session_factory),
        _ingest_plan,
    )


@live_takeover_app.command("take")
def live_takeover_take(
    channel_id: Annotated[
        str, typer.Option("--channel-id", help="Channel to cut to a live source.")
    ],
    operator_id: Annotated[
        str, typer.Option("--operator-id", help="Operator id recorded in the takeover audit.")
    ],
    operator_name: Annotated[
        str | None, typer.Option("--operator-name", help="Operator display name for the audit.")
    ] = None,
    reason: Annotated[
        str | None, typer.Option("--reason", help="Why the channel is being taken live.")
    ] = None,
    path_id: Annotated[
        str | None,
        typer.Option("--path-id", help="Specific live ingest path id (default: recommended path)."),
    ] = None,
    duration_seconds: Annotated[
        float,
        typer.Option("--duration-seconds", help="Planned live duration before automatic handback."),
    ] = 3600.0,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Begin a live takeover for one channel (queues the engine cut + records audit)."""

    from civiccast.egress.takeover_service import AlreadyLiveError, TakeoverNotReadyError

    service = _build_takeover_service()
    try:
        session = service.take(
            channel_id=channel_id,
            operator_id=operator_id,
            operator_name=operator_name,
            reason=reason,
            path_id=path_id,
            duration_seconds=duration_seconds,
        )
    except AlreadyLiveError as exc:
        typer.echo(f"Channel {channel_id} is already under live takeover.")
        raise typer.Exit(1) from exc
    except TakeoverNotReadyError as exc:
        typer.echo(f"No ready live source for {channel_id}: {exc}")
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(session.model_dump_json(indent=2))
        return
    typer.echo(f"Live takeover started on {channel_id}.")
    typer.echo(f"Session: {session.session_id}")
    typer.echo(f"Source: {session.source_label or session.source_ref}")


@live_takeover_app.command("return")
def live_takeover_return(
    channel_id: Annotated[
        str, typer.Option("--channel-id", help="Channel to return to its scheduled source.")
    ],
    operator_id: Annotated[
        str, typer.Option("--operator-id", help="Operator id recorded in the takeover audit.")
    ],
    notes: Annotated[
        str | None, typer.Option("--notes", help="Optional handback notes for the audit.")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Return one channel from a live takeover to its scheduled playout."""

    from civiccast.egress.takeover_service import NotInTakeoverError

    service = _build_takeover_service()
    try:
        session = service.handback(channel_id=channel_id, operator_id=operator_id, notes=notes)
    except NotInTakeoverError as exc:
        typer.echo(f"Channel {channel_id} is not under live takeover.")
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(session.model_dump_json(indent=2))
        return
    typer.echo(f"Returned {channel_id} to scheduled playout.")
    typer.echo(f"Closed session: {session.session_id}")


@live_takeover_app.command("state")
def live_takeover_state(
    channel_id: Annotated[
        str, typer.Option("--channel-id", help="Channel whose takeover state to read.")
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Show whether a channel is under live takeover and whether it can take/return."""

    service = _build_takeover_service()
    state = service.state(channel_id)
    if json_output:
        typer.echo(state.model_dump_json(indent=2))
        return
    live = state.active_session is not None
    typer.echo(f"Channel {channel_id}: {'LIVE (takeover active)' if live else 'scheduled playout'}")
    typer.echo(f"Can take live: {'yes' if state.can_takeover else 'no'}")
    typer.echo(f"Can return: {'yes' if state.can_return else 'no'}")


def _get_staff_token_store() -> PostgresStaffTokenStore:
    """Build the DB-backed staff token store for CLI lifecycle commands."""

    from sqlalchemy.orm import Session

    from civiccast.db import get_session

    @contextmanager
    def _session_factory() -> Iterator[Session]:
        gen = get_session()
        try:
            session = next(gen)
        except RuntimeError as exc:
            raise typer.BadParameter(
                "DATABASE_URL must point at the CivicCast database before running "
                "staff token lifecycle commands."
            ) from exc
        try:
            yield session
        finally:
            with suppress(StopIteration):
                next(gen)

    return PostgresStaffTokenStore(_session_factory)


def _parse_scopes(scopes: str) -> tuple[str, ...]:
    return tuple(scope.strip() for scope in scopes.split(",") if scope.strip()) or ("operator",)


def _token_metadata_payload(metadata: StaffTokenMetadata) -> dict[str, object]:
    return {
        "token_id": metadata.token_id,
        "operator_id": metadata.operator_id,
        "operator_display_name": metadata.operator_display_name,
        "scopes": list(metadata.scopes),
        "issued_at": metadata.issued_at.isoformat(),
        "last_used_at": metadata.last_used_at.isoformat() if metadata.last_used_at else None,
        "revoked_at": metadata.revoked_at.isoformat() if metadata.revoked_at else None,
        "revocation_reason": metadata.revocation_reason,
        "rotated_from_token_id": metadata.rotated_from_token_id,
    }


@token_app.command("generate-env")
def token_generate_env() -> None:
    """Generate a random secret for one CIVICCAST_STAFF_TOKENS entry."""

    typer.echo(generate_configured_staff_token())


@token_app.command("issue")
def token_issue(
    operator_id: Annotated[str, typer.Option("--operator-id", help="Stable operator id.")],
    display_name: Annotated[
        str,
        typer.Option("--display-name", help="Human-readable operator display name."),
    ],
    scopes: Annotated[
        str,
        typer.Option("--scopes", help="Comma-separated token scopes."),
    ] = "operator",
    save_keyring: Annotated[
        bool,
        typer.Option("--save-keyring", help="Save the issued token in the OS keyring."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Issue a staff bearer token and print the secret once."""

    issued = _get_staff_token_store().issue_token(
        operator_id=operator_id,
        operator_display_name=display_name,
        scopes=_parse_scopes(scopes),
    )
    if save_keyring:
        from civiccast.auth.keyring_store import save_staff_token

        save_staff_token(operator_id, issued.secret)
    payload = _token_metadata_payload(issued.metadata)
    payload["secret"] = issued.secret
    payload["secret_shown_once"] = True
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"Issued staff token {issued.metadata.token_id} for {display_name}.")
    typer.echo("Store this token now; CivicCast will not show it again:")
    typer.echo(issued.secret)
    if save_keyring:
        typer.echo(f"Saved active token for {operator_id} in the OS keyring.")


@token_app.command("list")
def token_list(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """List staff token metadata without bearer secrets."""

    tokens = [_token_metadata_payload(token) for token in _get_staff_token_store().list_tokens()]
    if json_output:
        typer.echo(json.dumps({"tokens": tokens}, indent=2))
        return
    if not tokens:
        typer.echo("No staff tokens have been issued.")
        return
    for token in tokens:
        state = "revoked" if token["revoked_at"] else "active"
        typer.echo(
            f"{token['token_id']} [{state}] {token['operator_id']} - {token['operator_display_name']}"
        )


@token_app.command("revoke")
def token_revoke(
    token_id: Annotated[str, typer.Argument(help="Public token id to revoke.")],
    reason: Annotated[
        str,
        typer.Option("--reason", help="Audit reason recorded with the revocation."),
    ] = "operator-requested",
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Revoke a staff token so future staff-route requests fail closed."""

    metadata = _get_staff_token_store().revoke_token(token_id, reason=reason)
    payload = _token_metadata_payload(metadata)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"Revoked staff token {token_id}. Reason: {reason}")


@token_app.command("rotate")
def token_rotate(
    token_id: Annotated[str, typer.Argument(help="Public token id to rotate.")],
    save_keyring: Annotated[
        bool,
        typer.Option("--save-keyring", help="Save the replacement token in the OS keyring."),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Revoke one staff token and issue a replacement for the same operator."""

    issued = _get_staff_token_store().rotate_token(token_id)
    if save_keyring:
        from civiccast.auth.keyring_store import save_staff_token

        save_staff_token(issued.metadata.operator_id, issued.secret)
    payload = _token_metadata_payload(issued.metadata)
    payload["secret"] = issued.secret
    payload["secret_shown_once"] = True
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"Rotated staff token {token_id} -> {issued.metadata.token_id}.")
    typer.echo("Store this replacement token now; CivicCast will not show it again:")
    typer.echo(issued.secret)
    if save_keyring:
        typer.echo(f"Saved replacement token for {issued.metadata.operator_id} in the OS keyring.")


@activitypub_app.command("keygen")
def activitypub_keygen(
    private_key_path: Annotated[
        Path,
        typer.Option("--private-key-path", help="Where to write the ActivityPub private key."),
    ],
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Public HTTPS base URL for this station."),
    ],
    handle: Annotated[
        str,
        typer.Option("--handle", help="Station account handle, e.g. civiccast."),
    ] = "civiccast",
    mode: Annotated[
        str,
        typer.Option("--mode", help="Federation mode: open, limited, or approval-only."),
    ] = "approval-only",
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Generate ActivityPub key material and print non-secret env settings."""

    from civiccast.activitypub.config import load_activitypub_config
    from civiccast.activitypub.keys import generate_activitypub_private_key

    public_key_pem = generate_activitypub_private_key(private_key_path)
    env = {
        "CIVICCAST_ACTIVITYPUB_MODE": mode,
        "CIVICCAST_ACTIVITYPUB_BASE_URL": base_url.rstrip("/"),
        "CIVICCAST_ACTIVITYPUB_HANDLE": handle,
        "CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH": str(private_key_path),
        "CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH": "1",
    }
    config = load_activitypub_config(env | {"CIVICCAST_ACTIVITYPUB_PUBLIC_KEY_PEM": public_key_pem})
    payload = {
        "enabled_after_restart": config.federation_mode != "disabled",
        "mode": config.federation_mode,
        "base_url": config.base_url,
        "handle": config.handle,
        "private_key_path": str(private_key_path),
        "public_key_pem": public_key_pem,
        "env": env,
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo("Generated ActivityPub station key.")
    typer.echo(f"Private key path: {private_key_path}")
    typer.echo("Add these settings before restarting CivicCast:")
    for key, value in env.items():
        typer.echo(f"{key}={value}")
    typer.echo("Public key PEM:")
    typer.echo(public_key_pem.rstrip())


def _render_probe_human(result: HardwareProbe) -> None:
    """Render the probe in the operator-friendly text format."""
    typer.echo(f"CivicCast {result.civiccast_version} - hardware probe")
    typer.echo(f"  hostname: {result.os.hostname}")
    typer.echo(
        f"  os:       {result.os.kind} ({result.os.system} {result.os.release}, {result.os.machine})"
    )
    typer.echo("")
    typer.echo("CPU")
    typer.echo(f"  brand:    {result.cpu.brand}")
    typer.echo(
        f"  cores:    {result.cpu.cores_physical} physical / {result.cpu.cores_logical} logical"
    )
    typer.echo("")
    typer.echo("RAM")
    typer.echo(f"  total:    {result.ram.total_gb} GB    available: {result.ram.available_gb} GB")
    typer.echo("")
    typer.echo("Disk")
    typer.echo(f"  path:     {result.disk.path}")
    typer.echo(f"  total:    {result.disk.total_gb} GB    free: {result.disk.free_gb} GB")
    typer.echo("")
    typer.echo("GPU")
    if result.gpu is None:
        typer.echo("  No NVIDIA GPU detected.")
        typer.echo("  CivicCast can run tier-0 (batch-only / streaming-only, CPU-only AI).")
    else:
        gpu = result.gpu
        typer.echo(f"  name:     {gpu.name}")
        typer.echo(f"  VRAM:     {gpu.vram_total_gb} GB total / {gpu.vram_free_gb} GB free")
        typer.echo(
            f"  driver:   {gpu.driver_version}"
            + (f"    CUDA: {gpu.cuda_version}" if gpu.cuda_version else "")
        )
    typer.echo("")
    typer.echo(f"Recommended deployment tier: {result.recommended_tier}")
    typer.echo(_tier_explanation(result.recommended_tier))

    # Sprint 0.2: streaming tools check (ADR 0007 compliance).
    typer.echo("")
    typer.echo("Streaming tools")
    from civiccast.stream._ffmpeg import check_ffmpeg

    ffmpeg_result = check_ffmpeg()
    if ffmpeg_result is None:
        typer.echo("  ffmpeg:   NOT FOUND — install ffmpeg to use streaming features")
        typer.echo("            e.g. 'apt install ffmpeg'  or  'brew install ffmpeg'")
    else:
        version_str, is_supported = ffmpeg_result
        if is_supported:
            typer.echo(f"  ffmpeg:   {version_str}  (supported)")
        else:
            typer.echo(
                f"  ffmpeg:   {version_str}  WARNING: version below minimum supported (4.4). "
                "Upgrade ffmpeg."
            )

    from civiccast.schedule.ingest import check_ffprobe

    ffprobe_result = check_ffprobe()
    if ffprobe_result is None:
        typer.echo("  ffprobe:  NOT FOUND — install ffmpeg (ships ffprobe) to enable asset ingest")
    else:
        version_str, is_supported = ffprobe_result
        if is_supported:
            typer.echo(f"  ffprobe:  {version_str}  (supported)")
        else:
            typer.echo(
                f"  ffprobe:  {version_str}  WARNING: version below minimum supported (4.4). "
                "Upgrade ffmpeg."
            )

    # Stage C: config-driven CDN check. Resolves through the same factory the
    # app uses (CIVICCAST_CDN_PROVIDER) — the old probe hard-instantiated the
    # R2 adapter and ignored the provider selection entirely.
    _doctor_check_cdn()

    # S11a: the CEA-608/708 caption lane (decode-back + embed capability).
    _doctor_check_captions()


def _doctor_check_cdn() -> None:
    """Report the configured CDN provider, resolved via the shared factory.

    Silent when ``CIVICCAST_CDN_PROVIDER`` is unset/``off`` so stations
    without a CDN see no noise. When a provider is selected: constructs the
    adapter through :func:`civiccast.stream.cdn.factory.build_cdn_adapter`
    (surfacing credential/config errors exactly as app startup would),
    health-checks adapters that support it, and reminds the operator about
    the analytics trusted-proxy reconciliation (Stage A): behind a CDN,
    visitor traffic arrives from edge IPs, so
    ``CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS`` must trust those hops or
    rate limits key on the CDN edge instead of visitors.
    """
    import os

    from civiccast.stream.cdn.factory import CDN_PROVIDER_OFF, CdnSettings, build_cdn_adapter

    try:
        settings = CdnSettings.from_env()
    except ValueError as exc:
        typer.echo("")
        typer.echo("CDN")
        typer.echo(f"  CONFIG ERROR: {exc}")
        return
    if settings.provider == CDN_PROVIDER_OFF:
        return

    typer.echo("")
    typer.echo(f"CDN ({settings.provider})")
    try:
        adapter = build_cdn_adapter(settings)
    except ValueError as exc:
        typer.echo(f"  CONFIG ERROR: {exc}")
        return
    except Exception as exc:  # pragma: no cover — optional-dependency import paths
        typer.echo(f"  ERROR: {exc}")
        return
    if adapter is None:  # pragma: no cover — provider!=off always builds or raises
        return

    health_check = getattr(adapter, "health_check", None)
    if callable(health_check):
        if health_check():
            typer.echo("  connectivity: OK")
        else:
            typer.echo(
                "  connectivity: NOT REACHABLE — check credentials and the provider dashboard"
            )
    else:
        typer.echo("  config: OK (provider has no connectivity probe)")
    sample = adapter.public_url("healthcheck/probe.txt")
    typer.echo(f"  public URL shape: {sample}")

    if not os.environ.get("CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS", "").strip():
        typer.echo(
            "  WARNING: a CDN is selected but CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS "
            "is empty. If the CDN fronts the public portal, analytics rate limiting "
            "will key on CDN edge IPs instead of visitors. Add the CDN's egress "
            "ranges; see docs/ops/cdn-and-providers.md."
        )


def _doctor_check_captions() -> None:
    """Report the CEA-608/708 caption lane (S11a).

    Decode-back proof needs the bundled ffmpeg's ``readeia608``. Embedding is the
    GStreamer engine's job (no ffmpeg build encodes 608/708 from text), so the
    default ffmpeg engine ships captions as a sidecar; the gst engine embeds via
    ``cccombiner``/``tttocea608``/``h264ccinserter`` when those elements are present.
    """
    import contextlib
    import shutil
    import subprocess

    from civiccast.egress.caption_proof import GST_CC_ELEMENTS, caption_lane_report
    from civiccast.stream._ffmpeg import run_ffmpeg

    try:
        filters = run_ffmpeg(["-hide_banner", "-filters"]).stdout or ""
    except Exception:  # pragma: no cover — ffmpeg absent / unreadable
        filters = ""

    present: set[str] = set()
    gst_inspect = shutil.which("gst-inspect-1.0")
    if gst_inspect:
        for element in GST_CC_ELEMENTS:
            with contextlib.suppress(Exception):  # pragma: no cover — gst-inspect transient
                proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                    [gst_inspect, element], capture_output=True, timeout=10, check=False
                )
                if proc.returncode == 0:
                    present.add(element)

    report = caption_lane_report(ffmpeg_filters=filters, gst_elements=present)
    typer.echo("")
    typer.echo("Captions (CEA-608/708)")
    typer.echo(
        "  decode-back proof: "
        + (
            "OK (ffmpeg readeia608)"
            if report.decode_back_capable
            else "UNAVAILABLE — bundled ffmpeg lacks readeia608; caption_status stays not-verified"
        )
    )
    typer.echo(
        "  ffmpeg engine:     captions ship as a sidecar "
        "(no ffmpeg build encodes 608/708 from text)"
    )
    if gst_inspect:
        typer.echo(
            "  GStreamer embed:   "
            + (
                "OK (cccombiner / tttocea608 / h264ccinserter)"
                if report.gst_embed_available
                else "MISSING elements — install gst-plugins-bad + gst-plugins-rs to embed CC"
            )
        )
    else:
        typer.echo(
            "  GStreamer embed:   native CEA-608/708 on the gst engine "
            "(gst-inspect-1.0 not on PATH here; verified on the gst-engine host)"
        )


def _tier_explanation(tier: str) -> str:
    """Brief operator-friendly note about the recommended tier."""
    explanations = {
        "tier-0": (
            "  Tier 0: batch-only or streaming-only without GPU acceleration. "
            "Captions and summaries run on CPU and are slower. Suitable for "
            "stations broadcasting <10 hours per week."
        ),
        "tier-1": (
            "  Tier 1 Streaming: GPU-accelerated captions and summary. "
            "TranslateGemma hot-swaps with summary model. The headline "
            "reference build per spec §10.2."
        ),
        "tier-1-plus": (
            "  Tier 1+ Streaming: 16-24GB VRAM. Captions, summary, and "
            "translation can stay loaded simultaneously — no hot-swap "
            "latency. Comfortable headroom for live caption + live "
            "translation simultaneously."
        ),
        "tier-2": (
            "  Tier 2 multi-stream / consortium: 24GB+ VRAM. Concurrent "
            "live streams (city + education + government channels) with "
            "full AI on each. Suitable for regional consortium hubs."
        ),
    }
    return explanations.get(tier, "")


@media_app.command("thumbnails-backfill")
def media_thumbnails_backfill(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit machine-readable JSON.")
    ] = False,
) -> None:
    """Generate thumbnails for assets that don't have one yet.

    4.0 media-library-hardening: thumbnail generation runs best-effort at
    upload time; this command catches up assets ingested before
    thumbnailing existed, or where generation failed at ingest (e.g.
    ffmpeg wasn't installed yet, or the file was briefly unreadable).
    Synchronous, one file at a time — matches the ingest path (no job
    queue exists in this codebase for this or any other feature).
    """
    from civiccast.schedule.ingest import FfmpegNotFoundError, FfprobeError, extract_thumbnail
    from civiccast.schedule.store import PostgresAssetStore

    store = PostgresAssetStore(_build_cli_session_factory())
    candidates = store.list_missing_thumbnails()
    generated: list[str] = []
    failed: list[str] = []
    for row in candidates:
        if row.file_path is None:
            continue
        source = Path(row.file_path)
        thumbnail_path = source.parent / "thumbnail.jpg"
        try:
            extract_thumbnail(source, thumbnail_path)
        except (FfmpegNotFoundError, FfprobeError, OSError) as exc:
            failed.append(row.asset_id)
            if not json_output:
                typer.echo(f"  {row.asset_id}: FAILED ({exc})")
            continue
        store.set_thumbnail_path(row.asset_id, str(thumbnail_path))
        generated.append(row.asset_id)
        if not json_output:
            typer.echo(f"  {row.asset_id}: generated {thumbnail_path}")

    if json_output:
        typer.echo(json.dumps({"generated": generated, "failed": failed}, indent=2))
    else:
        typer.echo(f"Backfill complete: {len(generated)} generated, {len(failed)} failed.")
    if failed:
        raise typer.Exit(code=1)


@dr_app.command("run-drill")
def dr_run_drill(
    out_dir: Annotated[
        Path,
        typer.Option("--out", help="Directory to write dr-drill-report.md/.json into."),
    ],
    backup_dir: Annotated[
        Path | None,
        typer.Option("--backup-dir", help="Backup destination (default: <out>/backup)."),
    ] = None,
    work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir", help="Scratch dir for restore/crash drills (default: <out>/work)."
        ),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option(
            "--database-url",
            help="DATABASE_URL to drill (default: $DATABASE_URL). sqlite:// or postgresql://.",
        ),
    ] = None,
    media_root: Annotated[
        Path | None,
        typer.Option("--media-root", help="Media library root to manifest (optional)."),
    ] = None,
) -> None:
    """Run the real 0.5.0 disaster-recovery drill: backup, restore, crash-recovery.

    Exits non-zero (and prints the failing detail) if any drill fails — this
    is the CI/operator-facing gate, not a rubber stamp.
    """
    from civiccast.dr.report import render_markdown, run_full_drill, write_report

    resolved_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_url:
        typer.echo("No DATABASE_URL configured; pass --database-url or set $DATABASE_URL.")
        raise typer.Exit(code=2)
    if not (resolved_url.startswith("sqlite") or resolved_url.startswith("postgresql")):
        typer.echo(
            "Unsupported DATABASE_URL scheme for the DR drill; use sqlite:// or postgresql://."
        )
        raise typer.Exit(code=2)

    report = run_full_drill(
        database_url=resolved_url,
        backup_dir=backup_dir or (out_dir / "backup"),
        work_dir=work_dir or (out_dir / "work"),
        media_root=media_root,
    )
    write_report(report, out_dir)
    typer.echo(render_markdown(report))
    if not report.ok:
        raise typer.Exit(code=1)


def main_entrypoint() -> None:  # pragma: no cover - thin shim
    """Console script entry point used by pyproject.toml's [project.scripts]."""
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main_entrypoint()

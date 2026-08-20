#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the complete signed native station distribution.

The NSIS bootstrap stays small. This builder emits the separately signed Core,
mandatory large-v3 Captions, both Summary, and Translation packs plus signed
online and air-gapped indexes that require that exact five-pack set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_distribution import (
    REQUIRED_COMPONENTS,
    build_distribution_index,
)
from civiccast.installer.native_packs import (
    build_native_pack,
    verify_native_pack,
)
from scripts.build_native_caption_pack import require_allowed_signing_key
from scripts.provision_native_ollama_models import (
    load_lock as load_model_lock,
)
from scripts.provision_native_ollama_models import verify_staged_model
from scripts.provision_native_runtime_dependencies import verify_staged_dependencies
from scripts.verify_native_app_payload import check_app_payload_verification

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_LOCK: Final[Path] = ROOT / "native-windows-ollama-models.lock.json"
_REPARSE_POINT: Final[int] = 0x400
_MODEL_COMPONENTS: Final[frozenset[str]] = frozenset(REQUIRED_COMPONENTS[2:])
_SAFE_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,126}\Z")
_LEGACY_CAPTION_ROOT: Final[PurePosixPath] = PurePosixPath("MODELS/faster-whisper-large-v3")


class NativeDistributionBuildError(RuntimeError):
    """The complete reviewed native station set could not be built."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_real_directory(path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        details = path.lstat()
    except OSError as exc:
        raise NativeDistributionBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISDIR(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise NativeDistributionBuildError(
            f"{label} must be a real directory, not a link or reparse point: {path}"
        )
    return path


def _require_regular_file(path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        details = path.lstat()
    except OSError as exc:
        raise NativeDistributionBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise NativeDistributionBuildError(f"{label} must be a regular non-reparse file: {path}")
    return path


def _collect_tree_sources(root: Path, *, prefix: str) -> dict[str, Path]:
    root = _require_real_directory(root, label=f"{prefix} source root")
    sources: dict[str, Path] = {}
    folded_paths: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        relative = PurePosixPath(candidate.relative_to(root).as_posix())
        details = candidate.lstat()
        attributes = int(getattr(details, "st_file_attributes", 0))
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            raise NativeDistributionBuildError(
                f"{prefix} source contains a link or reparse point: {relative}"
            )
        if candidate.is_dir():
            continue
        if not stat.S_ISREG(details.st_mode):
            raise NativeDistributionBuildError(
                f"{prefix} source contains a non-regular file: {relative}"
            )
        destination = PurePosixPath(prefix) / relative
        normalized = destination.as_posix()
        folded = normalized.casefold()
        if folded in folded_paths:
            raise NativeDistributionBuildError(
                f"{prefix} source contains a case-insensitive path collision: {normalized}"
            )
        folded_paths.add(folded)
        sources[normalized] = candidate.resolve(strict=True)
    if not sources:
        raise NativeDistributionBuildError(f"{prefix} source tree is empty")
    return sources


def _reject_legacy_caption_model(app_payload_root: Path) -> None:
    legacy = app_payload_root.joinpath(*_LEGACY_CAPTION_ROOT.parts)
    if legacy.exists():
        raise NativeDistributionBuildError(
            "Core contains the legacy duplicate faster-whisper model; "
            "mandatory caption bytes belong only to the signed captions-large-v3 pack"
        )


def _verified_core_sources(
    app_payload_root: Path,
    runtime_dependencies_root: Path,
    *,
    allow_dirty_source: bool,
) -> tuple[dict[str, Path], dict[str, object]]:
    app_payload_root = _require_real_directory(
        app_payload_root,
        label="native app payload",
    )
    runtime_dependencies_root = _require_real_directory(
        runtime_dependencies_root,
        label="native runtime dependency closure",
    )
    _reject_legacy_caption_model(app_payload_root)
    app_result = check_app_payload_verification(
        app_payload_root,
        require_clean_source=not allow_dirty_source,
        require_caption_pack=True,
        require_console_launchers=True,
        require_dependency_wheels=True,
    )
    if app_result.status != "PASS":
        raise NativeDistributionBuildError(
            f"native app payload verification failed: {app_result.detail}"
        )
    try:
        runtime_manifest = verify_staged_dependencies(runtime_dependencies_root)
    except Exception as exc:
        raise NativeDistributionBuildError(
            f"native runtime dependency verification failed: {exc}"
        ) from exc

    sources = _collect_tree_sources(app_payload_root, prefix="runtime")
    dependency_sources = _collect_tree_sources(
        runtime_dependencies_root,
        prefix="dependencies",
    )
    overlap = {path.casefold() for path in sources} & {
        path.casefold() for path in dependency_sources
    }
    if overlap:
        raise NativeDistributionBuildError(
            "Core app and dependency trees contain destination path collisions"
        )
    sources.update(dependency_sources)
    app_manifest = app_payload_root / "app-payload-manifest.json"
    runtime_manifest_path = runtime_dependencies_root / "native-runtime-dependencies-manifest.json"
    artifacts = runtime_manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise NativeDistributionBuildError(
            "native runtime dependency manifest artifacts must be an object"
        )
    metadata: dict[str, object] = {
        "app_manifest_sha256": _sha256_file(app_manifest),
        "runtime_dependencies_manifest_sha256": _sha256_file(runtime_manifest_path),
        "runtime_dependency_artifacts": sorted(str(name) for name in artifacts),
    }
    return sources, metadata


def _model_sources_and_metadata(
    *,
    model_name: str,
    component: str,
    root: Path,
    lock_path: Path,
) -> tuple[dict[str, Path], dict[str, object]]:
    root = _require_real_directory(root, label=f"{model_name} model root")
    try:
        verify_staged_model(model_name, root, lock_path=lock_path)
    except Exception as exc:
        raise NativeDistributionBuildError(
            f"{model_name} staged model verification failed: {exc}"
        ) from exc
    provenance_path = root / "MODEL-PROVENANCE.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeDistributionBuildError(f"{model_name} provenance is unreadable: {exc}") from exc
    if (
        not isinstance(provenance, dict)
        or provenance.get("model_name") != model_name
        or provenance.get("component") != component
        or not isinstance(provenance.get("manifest_sha256"), str)
        or not isinstance(provenance.get("ollama_runtime_version"), str)
    ):
        raise NativeDistributionBuildError(f"{model_name} provenance identity is inconsistent")
    sources = _collect_tree_sources(root, prefix="")
    normalized_sources = {path.removeprefix("/"): source for path, source in sources.items()}
    return normalized_sources, {
        "manifest_sha256": provenance["manifest_sha256"],
        "model_name": model_name,
        "ollama_runtime_version": provenance["ollama_runtime_version"],
    }


def _copy_pack(source: Path, destination: Path) -> None:
    source = _require_regular_file(source, label="mandatory caption pack")
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.unlink(missing_ok=True)
    try:
        with source.open("rb") as input_file, partial.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _pack_filename(component: str, product_version: str) -> str:
    labels = {
        "core": "Core",
        "captions-large-v3": "Captions-large-v3",
        "summary-gemma4-12b": "Summary-gemma4-12b",
        "summary-gemma4-e4b": "Summary-gemma4-e4b",
        "translation-translategemma-4b": "Translation-translategemma-4b",
    }
    return f"CivicCast-Native-{labels[component]}-{product_version}.ccpack"


def build_native_distribution(
    *,
    output_dir: Path,
    app_payload_root: Path,
    runtime_dependencies_root: Path,
    caption_pack: Path,
    model_roots: Mapping[str, Path],
    model_lock_path: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    channel: str,
    base_url: str,
    created_epoch: int,
    allow_dirty_source: bool = False,
) -> dict[str, Any]:
    """Build one transactional five-pack online and offline station set."""

    if _SAFE_VERSION_RE.fullmatch(product_version) is None:
        raise NativeDistributionBuildError(
            "product version is unsafe for native distribution filenames"
        )
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise NativeDistributionBuildError(
            f"refusing non-empty native distribution output directory: {output_dir}"
        )
    if not signing_key_id or signing_key_id.strip() != signing_key_id:
        raise NativeDistributionBuildError("pack signing key id is invalid")
    model_lock_path = _require_regular_file(
        model_lock_path,
        label="reviewed Ollama model lock",
    )
    try:
        model_lock = load_model_lock(model_lock_path)
    except Exception as exc:
        raise NativeDistributionBuildError(f"reviewed Ollama model lock is invalid: {exc}") from exc
    raw_models = model_lock.get("models") if isinstance(model_lock, dict) else None
    if not isinstance(raw_models, dict):
        raise NativeDistributionBuildError("reviewed Ollama model lock has no model set")
    expected_models = {
        name: item["component"]
        for name, item in raw_models.items()
        if isinstance(name, str)
        and isinstance(item, dict)
        and item.get("component") in _MODEL_COMPONENTS
    }
    if set(expected_models.values()) != _MODEL_COMPONENTS or set(model_roots) != set(
        expected_models
    ):
        missing = sorted(set(expected_models) - set(model_roots))
        extra = sorted(set(model_roots) - set(expected_models))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise NativeDistributionBuildError(
            "native distribution model root set is incomplete"
            + (": " + "; ".join(detail) if detail else "")
        )

    core_sources, core_metadata = _verified_core_sources(
        app_payload_root,
        runtime_dependencies_root,
        allow_dirty_source=allow_dirty_source,
    )
    caption_pack = _require_regular_file(
        caption_pack,
        label="mandatory caption pack",
    )
    verify_native_pack(
        caption_pack,
        public_key=signing_private_key.public_key(),
        expected_component="captions-large-v3",
        expected_product_version=product_version,
        expected_compatible_core=product_version,
        expected_signing_key_id=signing_key_id,
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    try:
        packs: dict[str, Path] = {}
        core_output = temporary / _pack_filename("core", product_version)
        build_native_pack(
            output=core_output,
            component="core",
            product_version=product_version,
            compatible_core=product_version,
            sources=core_sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata=core_metadata,
        )
        packs["core"] = core_output

        caption_output = temporary / _pack_filename(
            "captions-large-v3",
            product_version,
        )
        _copy_pack(caption_pack, caption_output)
        packs["captions-large-v3"] = caption_output

        for model_name, component in sorted(
            expected_models.items(),
            key=lambda item: REQUIRED_COMPONENTS.index(item[1]),
        ):
            sources, metadata = _model_sources_and_metadata(
                model_name=model_name,
                component=component,
                root=model_roots[model_name],
                lock_path=model_lock_path,
            )
            output = temporary / _pack_filename(component, product_version)
            build_native_pack(
                output=output,
                component=component,
                product_version=product_version,
                compatible_core=product_version,
                sources=sources,
                signing_private_key=signing_private_key,
                signing_key_id=signing_key_id,
                metadata=metadata,
            )
            packs[component] = output

        if set(packs) != set(REQUIRED_COMPONENTS):
            raise NativeDistributionBuildError("built native distribution pack set is incomplete")
        verified: dict[str, Any] = {}
        for component in REQUIRED_COMPONENTS:
            verified[component] = verify_native_pack(
                packs[component],
                public_key=signing_private_key.public_key(),
                expected_component=component,
                expected_product_version=product_version,
                expected_compatible_core=product_version,
                expected_signing_key_id=signing_key_id,
            )

        if not base_url.endswith("/"):
            base_url += "/"
        online_urls = {
            component: [
                base_url
                + quote(
                    packs[component].name,
                    safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~+",
                )
            ]
            for component in REQUIRED_COMPONENTS
        }
        channel_path = temporary / (f"CivicCast-Native-{channel}-{product_version}.channel.json")
        station_path = temporary / (f"CivicCast-Native-Station-Pack-{product_version}.ccstation")
        build_distribution_index(
            output=channel_path,
            kind="channel-index",
            channel=channel,
            product_version=product_version,
            compatible_core=product_version,
            packs=packs,
            urls=online_urls,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            created_epoch=created_epoch,
        )
        build_distribution_index(
            output=station_path,
            kind="station-index",
            channel=channel,
            product_version=product_version,
            compatible_core=product_version,
            packs=packs,
            urls={component: [] for component in REQUIRED_COMPONENTS},
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            created_epoch=created_epoch,
        )

        report_packs: dict[str, dict[str, Any]] = {
            component: {
                "filename": packs[component].name,
                "bytes": packs[component].stat().st_size,
                "sha256": verified[component].sha256,
            }
            for component in REQUIRED_COMPONENTS
        }
        channel_index_name = channel_path.name
        station_index_name = station_path.name
        report: dict[str, Any] = {
            "schema_version": 1,
            "product": "civiccast-native",
            "product_version": product_version,
            "channel": channel,
            "signing_key_id": signing_key_id,
            "created_epoch": created_epoch,
            "packs": report_packs,
            "total_pack_bytes": sum(int(item["bytes"]) for item in report_packs.values()),
            "channel_index": channel_index_name,
            "station_index": station_index_name,
        }
        (temporary / "native-distribution-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if output_dir.exists():
            output_dir.rmdir()
        temporary.replace(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return {
        **report,
        "packs": {
            component: {
                **report_packs[component],
                "path": str((output_dir / report_packs[component]["filename"]).resolve()),
            }
            for component in REQUIRED_COMPONENTS
        },
        "channel_index": str((output_dir / channel_index_name).resolve()),
        "station_index": str((output_dir / station_index_name).resolve()),
        "report": str((output_dir / "native-distribution-report.json").resolve()),
    }


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    path = _require_regular_file(path, label="pack signing private key")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise NativeDistributionBuildError(f"pack signing private key is invalid: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise NativeDistributionBuildError("pack signing private key must be Ed25519")
    return key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--app-payload-root", required=True, type=Path)
    parser.add_argument("--runtime-dependencies-root", required=True, type=Path)
    parser.add_argument("--caption-pack", required=True, type=Path)
    parser.add_argument("--gemma4-12b-root", required=True, type=Path)
    parser.add_argument("--gemma4-e4b-root", required=True, type=Path)
    parser.add_argument("--translategemma-4b-root", required=True, type=Path)
    parser.add_argument("--model-lock", type=Path, default=DEFAULT_MODEL_LOCK)
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--channel", default="beta")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--created-epoch", required=True, type=int)
    parser.add_argument("--allow-dirty-source", action="store_true")
    parser.add_argument("--allow-development-key", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    require_allowed_signing_key(
        args.signing_key_id,
        allow_development_key=args.allow_development_key,
    )
    result = build_native_distribution(
        output_dir=args.output_dir,
        app_payload_root=args.app_payload_root,
        runtime_dependencies_root=args.runtime_dependencies_root,
        caption_pack=args.caption_pack,
        model_roots={
            "gemma4-12b": args.gemma4_12b_root,
            "gemma4-e4b": args.gemma4_e4b_root,
            "translategemma-4b": args.translategemma_4b_root,
        },
        model_lock_path=args.model_lock,
        signing_private_key=_load_private_key(args.signing_private_key),
        signing_key_id=args.signing_key_id,
        product_version=args.product_version,
        channel=args.channel,
        base_url=args.base_url,
        created_epoch=args.created_epoch,
        allow_dirty_source=args.allow_dirty_source,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

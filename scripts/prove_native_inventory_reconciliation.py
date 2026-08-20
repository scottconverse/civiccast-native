#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Reconcile the shipped WSL runtime inventory with the native-Windows plan.

The WSL side is read from the exact extracted rc18 installer: its bootstrap,
resolved Linux requirements, and wheelhouse manifest.  The native side is read
from the reviewed Windows requirements/runtime locks and the built GStreamer
manifest.  A report is RECONCILED only when every WSL package has an explicit
native disposition and every complete-station component is allocated to a
required native pack.  RECONCILED does not mean the candidate is ready; planned
pack/service work remains listed as an implementation gap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from packaging.markers import Marker, default_environment
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_NATIVE_REQUIREMENTS: Final[Path] = ROOT / "requirements-native-app.txt"
DEFAULT_RUNTIME_LOCK: Final[Path] = ROOT / "native-windows-runtime-dependencies.lock.json"
DEFAULT_PACK_PLAN: Final[Path] = (
    ROOT / ".agent-runs" / "native-windows" / "specs" / "plan-sub-300mb-bootstrap.md"
)
DEFAULT_GSTREAMER_MANIFEST: Final[Path] = (
    ROOT / "build" / "wp1-gstreamer-closure" / "runtime-manifest.json"
)
DEFAULT_OUTPUT: Final[Path] = ROOT / "build" / "wp1-wsl-vs-native-inventory-reconciliation.json"

WSL_INSTALLER_VERSION: Final[str] = "1.0.0-rc18"
WSL_INSTALLER_BYTES: Final[int] = 243_742_408
WSL_INSTALLER_SHA256: Final[str] = (
    "af4d2017c6287eaed8cb4b1553d539281fc14c3e3863869c0ea5b8d2e73c311b"
)
WSL_TSDUCK_VERSION: Final[str] = "3.44-4676"
WSL_GSTREAMER_VERSION: Final[str] = "1.28.4"

_REQUIREMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)"
    r"(?:\s*;\s*(.*?))?\s*\\?\s*$"
)
_LITERAL_PACKAGE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_PLATFORM_REPLACEMENTS: Final[dict[str, str]] = {
    "jeepney": "Windows credential and IPC APIs replace the Linux D-Bus helper",
    "secretstorage": "Windows credential storage replaces the Linux Secret Service client",
    "uvloop": "uvicorn uses the supported Windows asyncio event loop",
}

_WSL_WHEEL_ONLY_DISPOSITIONS: Final[dict[str, tuple[str, str]]] = {
    "civiccast": (
        "CivicCast application in the native Core pack",
        "the application wheel is installed as the immutable app payload",
    ),
    "colorama": (
        "colorama in the native Core pack",
        "the Windows-only wheelhouse variant is selected by native requirements",
    ),
    "pywin32-ctypes": (
        "pywin32-ctypes in the native Core pack",
        "the Windows-only wheelhouse variant is selected by native requirements",
    ),
    "tzdata": (
        "tzdata in the native Core pack",
        "the wheelhouse fallback is pinned independently for the native payload",
    ),
}

_APT_DISPOSITIONS: Final[dict[str, tuple[str, str]]] = {
    "python3": (
        "core-pack",
        "pinned embeddable CPython runtime",
    ),
    "python3-venv": (
        "core-pack",
        "pre-resolved immutable application payload; no install-time venv",
    ),
    "python3-pip": (
        "core-pack",
        "hash-pinned dependencies are staged at build time; no install-time pip",
    ),
    "python3-gi": (
        "core-pack",
        "native app payload plus reviewed GStreamer/PyGObject runtime closure",
    ),
    "gir1.2-gstreamer-1.0": (
        "core-pack",
        "reviewed native GStreamer typelib/runtime closure",
    ),
    "gir1.2-gst-plugins-base-1.0": (
        "core-pack",
        "reviewed native GStreamer typelib/runtime closure",
    ),
    "ffmpeg": (
        "core-pack",
        "pinned native FFmpeg runtime plus minimal LGPL PyAV FFmpeg DLLs",
    ),
    "ca-certificates": (
        "core-pack",
        "Windows trust store and pinned Python certifi distribution",
    ),
    "libasound2t64": (
        "platform-replaced",
        "Windows WASAPI/DirectSound device paths replace ALSA",
    ),
    "libcairo-gobject2": (
        "core-pack",
        "reviewed native media/graphics closure",
    ),
    "libpango-1.0-0": (
        "core-pack",
        "reviewed native media/text closure",
    ),
    "libpangocairo-1.0-0": (
        "core-pack",
        "reviewed native media/text closure",
    ),
    "libpulse0": (
        "platform-replaced",
        "Windows WASAPI/DirectSound device paths replace PulseAudio",
    ),
    "tar": (
        "bootstrap",
        "bounded pack extractor/verifier replaces the distro tar utility",
    ),
}

_REQUIRED_RUNTIME_ARTIFACTS: Final[frozenset[str]] = frozenset(
    {"ffmpeg", "nats", "node", "ollama", "postgres", "tsduck"}
)
_REQUIRED_DISTRIBUTION_COMPONENTS: Final[tuple[str, ...]] = (
    "core",
    "captions-large-v3",
    "summary-gemma4-12b",
    "summary-gemma4-e4b",
    "translation-translategemma-4b",
)
_REQUIRED_PACK_TOKENS: Final[tuple[str, ...]] = (
    "CivicCast-Native-Core-<version>.ccpack",
    "CivicCast-Native-Captions-large-v3-<revision>.ccpack",
    "CivicCast-Native-Summary-gemma4-12b-<revision>.ccpack",
    "CivicCast-Native-Summary-gemma4-e4b-<revision>.ccpack",
    "CivicCast-Native-Translation-translategemma-4b-<revision>.ccpack",
    "required for a complete default station",
)


class InventoryReconciliationError(RuntimeError):
    """The WSL/native inventory cannot be completely reconciled."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_environment(target: str) -> dict[str, str]:
    environment = {key: str(value) for key, value in default_environment().items()}
    environment.update(
        {
            "implementation_name": "cpython",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "python_full_version": "3.12.10",
            "python_version": "3.12",
        }
    )
    if target == "linux":
        environment.update(
            {
                "os_name": "posix",
                "platform_system": "Linux",
                "sys_platform": "linux",
            }
        )
    elif target == "windows":
        environment.update(
            {
                "os_name": "nt",
                "platform_system": "Windows",
                "sys_platform": "win32",
            }
        )
    else:
        raise InventoryReconciliationError(f"unknown requirement target: {target}")
    return environment


def parse_requirements(text: str, *, target: str) -> dict[str, str]:
    """Return the exact packages selected for Linux or Windows CPython 3.12."""

    environment = _target_environment(target)
    selected: dict[str, str] = {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("--hash="):
            continue
        match = _REQUIREMENT_RE.fullmatch(line)
        if match is None:
            if raw_line[:1].isspace() or line == "\\":
                continue
            raise InventoryReconciliationError(
                f"unrecognized requirement at line {number}: {raw_line!r}"
            )
        raw_name, version, marker_text = match.groups()
        if marker_text is not None:
            marker_text = marker_text.rstrip("\\").strip()
            if not Marker(marker_text).evaluate(environment):
                continue
        name = canonicalize_name(raw_name)
        previous = selected.get(name)
        if previous is not None and previous != version:
            raise InventoryReconciliationError(
                f"target {target} selects conflicting versions for {name}: {previous} and {version}"
            )
        selected[name] = version
    return dict(sorted(selected.items()))


def parse_bootstrap_apt_packages(text: str) -> tuple[str, ...]:
    """Enumerate literal packages from multiline ``apt-get install -y`` blocks."""

    packages: set[str] = set()
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if not re.fullmatch(r"\s*apt-get install -y\s*\\\s*", raw_line):
            continue
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor].strip()
            continued = candidate.endswith("\\")
            token = candidate[:-1].strip() if continued else candidate
            if _LITERAL_PACKAGE_RE.fullmatch(token):
                packages.add(token)
            if not continued:
                break
            cursor += 1
    return tuple(sorted(packages))


def parse_wheelhouse_distributions(
    wheels: Sequence[Mapping[str, object]],
) -> dict[str, tuple[str, ...]]:
    """Return every normalized distribution/version represented by the manifest."""
    distributions: dict[str, set[str]] = {}
    for entry in wheels:
        filename = entry.get("filename")
        if not isinstance(filename, str):
            raise InventoryReconciliationError(
                "WSL wheelhouse entry has no filename"
            )
        try:
            raw_name, version, _build, _tags = parse_wheel_filename(filename)
        except InvalidWheelFilename as error:
            raise InventoryReconciliationError(
                f"invalid WSL wheel filename: {filename}"
            ) from error
        name = canonicalize_name(raw_name)
        distributions.setdefault(name, set()).add(str(version))
    return {
        name: tuple(sorted(versions))
        for name, versions in sorted(distributions.items())
    }


def _row(
    *,
    origin: str,
    wsl_identity: str,
    native_identity: str,
    disposition: str,
    status: str,
) -> dict[str, str]:
    return {
        "disposition": disposition,
        "native_identity": native_identity,
        "origin": origin,
        "status": status,
        "wsl_identity": wsl_identity,
    }


def _validated_distribution_statuses(
    distribution_report: Mapping[str, Any] | None,
) -> dict[str, str]:
    if distribution_report is None:
        return {}
    if distribution_report.get("schema_version") != 1:
        raise InventoryReconciliationError(
            "native distribution report has an unsupported schema version"
        )
    if distribution_report.get("product") != "civiccast-native":
        raise InventoryReconciliationError(
            "native distribution report has the wrong product identity"
        )
    product_version = distribution_report.get("product_version")
    if not isinstance(product_version, str) or not product_version.strip():
        raise InventoryReconciliationError(
            "native distribution report has no product version"
        )
    signing_key_id = distribution_report.get("signing_key_id")
    if not isinstance(signing_key_id, str) or not signing_key_id.strip():
        raise InventoryReconciliationError(
            "native distribution report has no signing key identity"
        )
    packs = distribution_report.get("packs")
    if not isinstance(packs, dict) or set(packs) != set(_REQUIRED_DISTRIBUTION_COMPONENTS):
        raise InventoryReconciliationError(
            "native distribution report does not contain the exact required pack set"
        )
    filenames: set[str] = set()
    observed_total = 0
    for component in _REQUIRED_DISTRIBUTION_COMPONENTS:
        item = packs.get(component)
        if not isinstance(item, dict):
            raise InventoryReconciliationError(
                f"native distribution report pack is not an object: {component}"
            )
        filename = item.get("filename")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or not filename.endswith(".ccpack")
        ):
            raise InventoryReconciliationError(
                f"native distribution report has an unsafe pack filename: {component}"
            )
        folded = filename.casefold()
        if folded in filenames:
            raise InventoryReconciliationError(
                f"native distribution report repeats a pack filename: {filename}"
            )
        filenames.add(folded)
        pack_bytes = item.get("bytes")
        if not isinstance(pack_bytes, int) or isinstance(pack_bytes, bool) or pack_bytes <= 0:
            raise InventoryReconciliationError(
                f"native distribution report has no positive byte length: {component}"
            )
        pack_sha256 = item.get("sha256")
        if not isinstance(pack_sha256, str) or _SHA256_RE.fullmatch(pack_sha256) is None:
            raise InventoryReconciliationError(
                f"native distribution report has an invalid SHA-256: {component}"
            )
        observed_total += pack_bytes
    if distribution_report.get("total_pack_bytes") != observed_total:
        raise InventoryReconciliationError(
            "native distribution report total byte length does not match its packs"
        )
    for field, suffix in (
        ("channel_index", ".channel.json"),
        ("station_index", ".ccstation"),
    ):
        filename = distribution_report.get(field)
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(suffix)
        ):
            raise InventoryReconciliationError(
                f"native distribution report has an unsafe {field.replace('_', ' ')}"
            )
    status = (
        "built-signed-pack-development-trust"
        if signing_key_id.startswith("development-")
        else "built-signed-pack"
    )
    return dict.fromkeys(_REQUIRED_DISTRIBUTION_COMPONENTS, status)


def _required_native_components(
    runtime_lock: Mapping[str, Any],
    *,
    pack_plan: str,
    caption_pack: Mapping[str, Any] | None,
    distribution_statuses: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    unresolved: list[str] = []
    normalized_plan = " ".join(pack_plan.split())
    artifacts = runtime_lock.get("artifacts")
    if not isinstance(artifacts, dict):
        unresolved.append("native runtime dependency lock has no artifacts object")
        artifacts = {}
    missing_artifacts = sorted(_REQUIRED_RUNTIME_ARTIFACTS - set(artifacts))
    unresolved.extend(f"native runtime lock is missing {name}" for name in missing_artifacts)
    unresolved.extend(
        f"required pack plan is missing {token}"
        for token in _REQUIRED_PACK_TOKENS
        if token not in normalized_plan
    )
    caption_status = distribution_statuses.get(
        "captions-large-v3",
        "planned-required-pack",
    )
    if caption_pack is not None and "captions-large-v3" not in distribution_statuses:
        if caption_pack.get("component") != "captions-large-v3":
            unresolved.append("caption pack report has the wrong component identity")
        elif (
            not isinstance(caption_pack.get("pack_bytes"), int)
            or int(caption_pack["pack_bytes"]) <= 0
        ):
            unresolved.append("caption pack report has no positive pack byte length")
        elif not isinstance(caption_pack.get("pack_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}",
            str(caption_pack["pack_sha256"]),
        ):
            unresolved.append("caption pack report has an invalid SHA-256")
        elif str(caption_pack.get("signing_key_id", "")).startswith("development-"):
            caption_status = "built-signed-pack-development-trust"
        else:
            caption_status = "built-signed-pack"
    return (
        {
            "captions-large-v3": caption_status,
            "core": distribution_statuses.get("core", "partially-built"),
            "nats-server": ("built-runtime-closure" if "nats" in artifacts else "unreconciled"),
            "ollama-runtime": (
                "built-runtime-closure"
                if "ollama" in artifacts and "core" in distribution_statuses
                else "planned-core-pack"
            ),
            "postgresql-server": (
                "built-runtime-closure" if "postgres" in artifacts else "unreconciled"
            ),
            "summary-gemma4-12b": distribution_statuses.get(
                "summary-gemma4-12b",
                "planned-required-pack",
            ),
            "summary-gemma4-e4b": distribution_statuses.get(
                "summary-gemma4-e4b",
                "planned-required-pack",
            ),
            "translation-translategemma-4b": distribution_statuses.get(
                "translation-translategemma-4b",
                "planned-required-pack",
            ),
        },
        unresolved,
    )


def build_reconciliation(
    *,
    wsl_packages: Mapping[str, str],
    native_packages: Mapping[str, str],
    apt_packages: Sequence[str],
    runtime_lock: Mapping[str, Any],
    gstreamer_file_count: int,
    pack_plan: str,
    source_identity: Mapping[str, object],
    wsl_wheelhouse_packages: Mapping[str, Sequence[str]] | None = None,
    wheel_only_dispositions: Mapping[str, tuple[str, str]] | None = None,
    caption_pack: Mapping[str, Any] | None = None,
    distribution_report: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Build the complete line-by-line reconciliation document."""

    if gstreamer_file_count <= 0:
        raise InventoryReconciliationError(
            "unreconciled native GStreamer closure: no manifested files"
        )
    rows: list[dict[str, str]] = []
    unresolved: list[str] = []
    distribution_statuses = _validated_distribution_statuses(distribution_report)
    wheelhouse_packages = wsl_wheelhouse_packages or {}
    explicit_wheel_dispositions = wheel_only_dispositions or {}

    for name, version in sorted(wsl_packages.items()):
        native_version = native_packages.get(name)
        if native_version is not None:
            status = "exact-version" if native_version == version else "reviewed-version-change"
            rows.append(
                _row(
                    origin="wsl-pip",
                    wsl_identity=f"{name}=={version}",
                    native_identity=f"{name}=={native_version}",
                    disposition="core-pack-app-payload",
                    status=status,
                )
            )
        elif name in _PLATFORM_REPLACEMENTS:
            rows.append(
                _row(
                    origin="wsl-pip",
                    wsl_identity=f"{name}=={version}",
                    native_identity="Windows platform runtime",
                    disposition=_PLATFORM_REPLACEMENTS[name],
                    status="platform-replaced",
                )
            )
        else:
            unresolved.append(f"wsl-pip:{name}=={version}")

    for name, raw_versions in sorted(wheelhouse_packages.items()):
        versions = tuple(sorted(set(raw_versions)))
        if not versions:
            unresolved.append(f"wheelhouse:{name} has no versions")
            continue
        selected_wsl_version = wsl_packages.get(name)
        for version in versions:
            if version == selected_wsl_version:
                # The normal wsl-pip row above is the explicit disposition for
                # the exact wheel selected by the Linux requirements.
                continue
            if selected_wsl_version is not None:
                native_version = native_packages.get(name)
                rows.append(
                    _row(
                        origin="wsl-wheelhouse-variant",
                        wsl_identity=f"{name}=={version}",
                        native_identity=(
                            f"{name}=={native_version}"
                            if native_version is not None
                            else "not selected by the native requirements"
                        ),
                        disposition=(
                            "artifact is present in the multi-platform WSL "
                            "wheelhouse but is not selected by its Linux requirements"
                        ),
                        status="explicitly-not-selected",
                    )
                )
                continue
            disposition = explicit_wheel_dispositions.get(name)
            if disposition is None:
                unresolved.append(f"wheelhouse-only:{name}=={version}")
                continue
            native_identity, detail = disposition
            rows.append(
                _row(
                    origin="wsl-wheelhouse-only",
                    wsl_identity=f"{name}=={version}",
                    native_identity=native_identity,
                    disposition=detail,
                    status="explicitly-mapped",
                )
            )

    for package in sorted(apt_packages):
        disposition = _APT_DISPOSITIONS.get(package)
        if disposition is None:
            unresolved.append(f"wsl-apt:{package}")
            continue
        destination, detail = disposition
        rows.append(
            _row(
                origin="wsl-apt",
                wsl_identity=package,
                native_identity=destination,
                disposition=detail,
                status="mapped",
            )
        )

    caption_runtime_status = distribution_statuses.get(
        "captions-large-v3",
        (
            "planned-required-pack"
            if caption_pack is None
            else (
                "built-signed-pack-development-trust"
                if str(caption_pack.get("signing_key_id", "")).startswith("development-")
                else "built-signed-pack"
            )
        ),
    )
    ai_pack_status = (
        distribution_statuses["summary-gemma4-12b"]
        if all(
            component in distribution_statuses
            for component in (
                "core",
                "summary-gemma4-12b",
                "summary-gemma4-e4b",
                "translation-translategemma-4b",
            )
        )
        else "planned-required-packs"
    )
    runtime_rows = [
        _row(
            origin="wsl-platform",
            wsl_identity="Ubuntu 24.04 WSL distro",
            native_identity="direct Windows x86-64 runtime",
            disposition="the native product removes the Linux/WSL platform layer",
            status="platform-eliminated",
        ),
        _row(
            origin="wsl-service",
            wsl_identity="systemd:civiccast.service",
            native_identity="SCM:CivicCast (LocalSystem)",
            disposition="native lifecycle package must register and supervise the station",
            status="planned-native-service",
        ),
        _row(
            origin="wsl-bundled-runtime",
            wsl_identity=f"GStreamer {WSL_GSTREAMER_VERSION}",
            native_identity=f"native GStreamer closure ({gstreamer_file_count} files)",
            disposition="reviewed native media closure",
            status="built-runtime-closure",
        ),
        _row(
            origin="wsl-fetched-tool",
            wsl_identity=f"TSDuck {WSL_TSDUCK_VERSION}",
            native_identity=(
                "TSDuck "
                + str(runtime_lock.get("artifacts", {}).get("tsduck", {}).get("version", "missing"))
            ),
            disposition="pinned native runtime dependency closure",
            status=(
                "built-runtime-closure"
                if "tsduck" in runtime_lock.get("artifacts", {})
                else "unreconciled"
            ),
        ),
        _row(
            origin="wsl-frontend",
            wsl_identity="prebuilt operator and public portal resources",
            native_identity="deterministically built Core-pack frontends",
            disposition="native app payload build and manifest coverage",
            status=distribution_statuses.get("core", "partially-built"),
        ),
        _row(
            origin="wsl-model",
            wsl_identity="large-v3 downloaded on first use, not installed by rc18",
            native_identity="CivicCast-Native-Captions-large-v3 required pack",
            disposition="offline legal-caption delivery with no downgrade path",
            status=caption_runtime_status,
        ),
        _row(
            origin="wsl-ai-runtime",
            wsl_identity="no local Ollama runtime or model provisioning in rc18",
            native_identity="Ollama in Core plus both Summary and Translation packs",
            disposition="complete local station model delivery",
            status=ai_pack_status,
        ),
    ]
    rows.extend(runtime_rows)

    required_components, contract_unresolved = _required_native_components(
        runtime_lock,
        pack_plan=pack_plan,
        caption_pack=caption_pack,
        distribution_statuses=distribution_statuses,
    )
    unresolved.extend(contract_unresolved)
    if any(row["status"] == "unreconciled" for row in runtime_rows):
        unresolved.append("runtime row has no native implementation identity")

    native_only = sorted(set(native_packages) - set(wsl_packages))
    for name in native_only:
        rows.append(
            _row(
                origin="native-pip-addition",
                wsl_identity="not selected by WSL rc18",
                native_identity=f"{name}=={native_packages[name]}",
                disposition="required current native application dependency",
                status="native-addition",
            )
        )

    if unresolved:
        raise InventoryReconciliationError(
            "unreconciled WSL/native inventory rows: " + "; ".join(sorted(unresolved))
        )

    rows.sort(
        key=lambda item: (
            item["origin"],
            item["wsl_identity"],
            item["native_identity"],
        )
    )
    implementation_gaps = sorted(
        name
        for name, status in required_components.items()
        if status.startswith(("planned-", "partially-"))
    )
    return {
        "candidate_readiness": (
            "BLOCKED_ON_IMPLEMENTATION" if implementation_gaps else "READY_FOR_PROOF"
        ),
        "implementation_gaps": implementation_gaps,
        "required_native_components": required_components,
        "rows": rows,
        "schema_version": 1,
        "source_identity": dict(source_identity),
        "status": "RECONCILED",
        "summary": {
            "native_additions": len(native_only) + len(required_components),
            "native_pip_packages": len(native_packages),
            "wsl_pip_packages": len(wsl_packages),
            "wsl_rows": len(wsl_packages) + len(apt_packages),
            "wsl_runtime_rows": len(runtime_rows),
            "wsl_wheelhouse_distribution_versions": sum(
                len(set(versions)) for versions in wheelhouse_packages.values()
            ),
        },
        "unreconciled": [],
    }


def render_report(report: Mapping[str, object]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _verified_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise InventoryReconciliationError(f"required inventory source is missing: {path}")
    return {
        "bytes": path.stat().st_size,
        "path": str(path.resolve()),
        "sha256": _sha256_file(path),
    }


def _verify_wsl_release(
    *,
    installer: Path,
    extracted_root: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, tuple[str, ...]]]:
    installer_record = _verified_file(installer)
    if installer_record["bytes"] != WSL_INSTALLER_BYTES:
        raise InventoryReconciliationError(
            f"WSL installer byte length changed: {installer_record['bytes']}"
        )
    if installer_record["sha256"] != WSL_INSTALLER_SHA256:
        raise InventoryReconciliationError(
            f"WSL installer SHA-256 changed: {installer_record['sha256']}"
        )

    resources = extracted_root / "resources"
    bootstrap = resources / "headless-bootstrap.ps1"
    requirements = resources / "wheelhouse" / "requirements.txt"
    manifest_path = resources / "wheelhouse" / "WHEELHOUSE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != WSL_INSTALLER_VERSION:
        raise InventoryReconciliationError(
            f"WSL wheelhouse version is not {WSL_INSTALLER_VERSION}: {manifest.get('version')!r}"
        )
    wheels = manifest.get("wheels")
    if not isinstance(wheels, list):
        raise InventoryReconciliationError("WSL wheelhouse manifest has no wheels list")
    expected_names: set[str] = set()
    for entry in wheels:
        if not isinstance(entry, dict):
            raise InventoryReconciliationError("WSL wheelhouse entry is not an object")
        filename = entry.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise InventoryReconciliationError(f"unsafe WSL wheelhouse filename: {filename!r}")
        wheel = manifest_path.parent / filename
        record = _verified_file(wheel)
        if record["bytes"] != entry.get("size_bytes"):
            raise InventoryReconciliationError(f"WSL wheelhouse size mismatch: {filename}")
        if record["sha256"] != entry.get("sha256"):
            raise InventoryReconciliationError(f"WSL wheelhouse SHA-256 mismatch: {filename}")
        expected_names.add(filename)
    actual_names = {path.name for path in manifest_path.parent.glob("*.whl")}
    if actual_names != expected_names:
        raise InventoryReconciliationError("WSL wheelhouse file set differs from its manifest")
    wheelhouse_packages = parse_wheelhouse_distributions(wheels)
    source_identity: dict[str, object] = {
        "wsl_bootstrap": _verified_file(bootstrap),
        "wsl_installer": installer_record,
        "wsl_requirements": _verified_file(requirements),
        "wsl_wheelhouse": {
            **_verified_file(manifest_path),
            "distribution_count": len(wheelhouse_packages),
            "distribution_version_count": sum(
                len(versions) for versions in wheelhouse_packages.values()
            ),
            "wheel_count": len(wheels),
        },
    }
    return bootstrap, requirements, source_identity, wheelhouse_packages


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryReconciliationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise InventoryReconciliationError(f"{label} is not a JSON object: {path}")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl-installer", required=True, type=Path)
    parser.add_argument("--wsl-extracted-root", required=True, type=Path)
    parser.add_argument(
        "--native-requirements",
        type=Path,
        default=DEFAULT_NATIVE_REQUIREMENTS,
    )
    parser.add_argument("--runtime-lock", type=Path, default=DEFAULT_RUNTIME_LOCK)
    parser.add_argument(
        "--gstreamer-manifest",
        type=Path,
        default=DEFAULT_GSTREAMER_MANIFEST,
    )
    parser.add_argument("--pack-plan", type=Path, default=DEFAULT_PACK_PLAN)
    parser.add_argument("--caption-pack-report", type=Path)
    parser.add_argument("--distribution-report", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    (
        bootstrap_path,
        wsl_requirements_path,
        source_identity,
        wsl_wheelhouse_packages,
    ) = _verify_wsl_release(
        installer=args.wsl_installer.resolve(),
        extracted_root=args.wsl_extracted_root.resolve(),
    )
    native_requirements = args.native_requirements.resolve()
    runtime_lock_path = args.runtime_lock.resolve()
    gstreamer_manifest_path = args.gstreamer_manifest.resolve()
    pack_plan_path = args.pack_plan.resolve()
    caption_pack: dict[str, Any] | None = None
    distribution_report: dict[str, Any] | None = None
    if args.caption_pack_report is not None:
        caption_pack_report_path = args.caption_pack_report.resolve()
        caption_pack = _load_json(
            caption_pack_report_path,
            label="native caption pack build report",
        )
        pack_output = caption_pack.get("output")
        if not isinstance(pack_output, str):
            raise InventoryReconciliationError(
                "native caption pack build report has no output path"
            )
        pack_record = _verified_file(Path(pack_output))
        if pack_record["bytes"] != caption_pack.get("pack_bytes") or pack_record[
            "sha256"
        ] != caption_pack.get("pack_sha256"):
            raise InventoryReconciliationError(
                "native caption pack bytes do not match its build report"
            )
        source_identity["native_caption_pack"] = pack_record
        source_identity["native_caption_pack_report"] = _verified_file(caption_pack_report_path)
    if args.distribution_report is not None:
        distribution_report_path = args.distribution_report.resolve()
        distribution_report = _load_json(
            distribution_report_path,
            label="native distribution report",
        )
        _validated_distribution_statuses(distribution_report)
        distribution_root = distribution_report_path.parent
        raw_packs = distribution_report["packs"]
        assert isinstance(raw_packs, dict)
        pack_records: dict[str, object] = {}
        for component in _REQUIRED_DISTRIBUTION_COMPONENTS:
            item = raw_packs[component]
            assert isinstance(item, dict)
            filename = item["filename"]
            assert isinstance(filename, str)
            record = _verified_file(distribution_root / filename)
            if record["bytes"] != item["bytes"] or record["sha256"] != item["sha256"]:
                raise InventoryReconciliationError(
                    f"native distribution pack bytes do not match its report: {component}"
                )
            pack_records[component] = record
        channel_index = distribution_report["channel_index"]
        station_index = distribution_report["station_index"]
        assert isinstance(channel_index, str)
        assert isinstance(station_index, str)
        source_identity["native_distribution"] = {
            "channel_index": _verified_file(distribution_root / channel_index),
            "packs": pack_records,
            "report": _verified_file(distribution_report_path),
            "station_index": _verified_file(distribution_root / station_index),
        }
        if caption_pack is not None:
            caption_item = raw_packs["captions-large-v3"]
            assert isinstance(caption_item, dict)
            if (
                caption_item["bytes"] != caption_pack.get("pack_bytes")
                or caption_item["sha256"] != caption_pack.get("pack_sha256")
            ):
                raise InventoryReconciliationError(
                    "native distribution caption pack differs from its standalone build report"
                )
    source_identity.update(
        {
            "native_gstreamer_manifest": _verified_file(gstreamer_manifest_path),
            "native_pack_plan": _verified_file(pack_plan_path),
            "native_requirements": _verified_file(native_requirements),
            "native_runtime_lock": _verified_file(runtime_lock_path),
        }
    )
    gstreamer_manifest = _load_json(
        gstreamer_manifest_path,
        label="native GStreamer manifest",
    )
    report = build_reconciliation(
        wsl_packages=parse_requirements(
            wsl_requirements_path.read_text(encoding="utf-8"),
            target="linux",
        ),
        native_packages=parse_requirements(
            native_requirements.read_text(encoding="utf-8"),
            target="windows",
        ),
        apt_packages=parse_bootstrap_apt_packages(
            bootstrap_path.read_text(encoding="utf-8"),
        ),
        runtime_lock=_load_json(runtime_lock_path, label="native runtime lock"),
        gstreamer_file_count=int(gstreamer_manifest.get("file_count", 0)),
        pack_plan=pack_plan_path.read_text(encoding="utf-8"),
        source_identity=source_identity,
        wsl_wheelhouse_packages=wsl_wheelhouse_packages,
        wheel_only_dispositions=_WSL_WHEEL_ONLY_DISPOSITIONS,
        caption_pack=caption_pack,
        distribution_report=distribution_report,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(report), encoding="utf-8", newline="\n")
    print(render_report(report), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InventoryReconciliationError as error:
        raise SystemExit(f"prove_native_inventory_reconciliation: {error}") from error

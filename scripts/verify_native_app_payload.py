#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Verify a built native application payload against its own manifest
(`slice:ws5-installer` WP-6 Part A -- the D2 trust re-check).

Independent of the builder: re-derives every fact from the tree on disk and
refuses on any disagreement, so it can be run at build time (the D2
embedded-bytes gate, before the payload is staged into the installer bundle)
and its logic proven by tests with a committed negative control.

Checks, all fail-loud:
  1. **Byte integrity.** Every `app-payload-manifest.json` entry exists on disk
     with a matching SHA-256 and byte count; every on-disk file (bar the three
     trust artifacts) appears in the manifest. Missing / orphan / mismatch are
     reported in separate labelled sections.
  2. **Interpreter present.** `python.exe` and `python312.dll` are in the tree
     (the installer's D3 gate checks `$INSTDIR\\runtime\\python.exe`; a payload
     without it is not bootable).
  3. **Deny-by-default provenance.** Every distribution the manifest names
     (except the interpreter) is in `AUTHORIZED_APP_DISTRIBUTIONS`, and no
     file's recorded license is GPL/AGPL.

`check_app_payload_verification(tree) -> PayloadVerification` is the reusable
entry point; `main` is a thin CLI that prints the result and sets the exit
code.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from packaging.utils import InvalidWheelFilename, parse_wheel_filename

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.native.app_payload import (  # noqa: E402
    APP_BUILD_REQUIREMENTS_SHA256,
    APP_BUILD_TOOLCHAIN,
    APP_BUILD_TOOLCHAIN_LOCK_SHA256,
    APP_BYTECODE_POLICY_PATH,
    APP_BYTECODE_POLICY_PREFIX,
    APP_DISTRIBUTION_LICENSE,
    APP_EXTERNAL_LICENSE_FILES,
    APP_MANIFEST_SCHEMA_VERSION,
    APP_REQUIREMENTS_SHA256,
    AUTHORIZED_APP_DISTRIBUTIONS,
    AUTHORIZED_NON_WHEEL_COMPONENTS,
    CAPTION_PACK_CONTRACT,
    CIVICCAST_CONSOLE_ENTRY_POINTS,
    CIVICCAST_CONSOLE_LAUNCHERS,
    CIVICCAST_DISTRIBUTION,
    CIVICCAST_RETAINED_WHEEL_PATH,
    EMBEDDED_FFMPEG_LICENSE,
    INTERPRETER_DISTRIBUTION,
    INTERPRETER_LICENSE,
    INTERPRETER_SHA256,
    INTERPRETER_SOURCE_URL,
    INTERPRETER_VERSION,
    MSVC_RUNTIME_DISTRIBUTION,
    MSVC_RUNTIME_FILES,
    WHISPER_MODEL_PAYLOAD_DIR,
    canonical_distribution_name,
    component_version_for_payload_path,
    is_prohibited_license,
    license_for_payload_path,
)

_TRUST_ARTIFACTS = frozenset({"app-payload-manifest.json", "SHA256SUMS", "LICENSE-BOM.md"})
_REQUIRED_INTERPRETER_FILES = ("python.exe", "python312.dll")
APP_REQUIREMENTS_FILE = ROOT / "requirements-native-app.txt"


@dataclass(frozen=True)
class PayloadVerification:
    status: str  # "PASS" | "FAIL"
    detail: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_sha256sums(records: list[dict[str, object]]) -> str:
    return "".join(
        f"{record['sha256']}  {record['path']}\n"
        for record in sorted(records, key=lambda record: str(record["path"]))
    )


def _record_bytes(record: dict[str, object]) -> int:
    value = record["bytes"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"manifest record bytes is not a non-negative integer: {value!r}")
    return value


def _render_license_bom(records: list[dict[str, object]]) -> str:
    by_component: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for record in sorted(records, key=lambda record: str(record["path"])):
        distribution = str(record["distribution"])
        license_ = str(record["license"])
        component = (
            "av (embedded FFmpeg)"
            if distribution == "av" and license_ == EMBEDDED_FFMPEG_LICENSE
            else distribution
        )
        version = component_version_for_payload_path(
            distribution,
            str(record["version"]),
            str(record["path"]),
        )
        by_component.setdefault((component, version, license_), []).append(record)

    lines = ["# CivicCast (Native) Application Payload — License Bill of Materials", ""]
    lines.append(
        "The interpreter (CPython 3.12 embeddable, PSF-2.0), the `civiccast` "
        "application (Apache-2.0), and every hash-pinned third-party pip "
        "dependency. Deny-by-default: every distribution below is in "
        "`civiccast.native.app_payload.AUTHORIZED_APP_DISTRIBUTIONS`. No "
        "GPL/AGPL. License texts ship either in each wheel's installed tree or "
        "under `THIRD-PARTY-LICENSES`; embedded FFmpeg carries its LGPL "
        "compliance text and provenance inside the PyAV wheel."
    )
    lines.extend(
        [
            "",
            "## Summary by distribution",
            "",
            "| Distribution | Version | License | Files | Bytes |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for (component, version, license_), group in sorted(by_component.items()):
        lines.append(
            f"| {component} | {version} | {license_} | {len(group)} | "
            f"{sum(_record_bytes(record) for record in group)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _verify_manifest_header(
    manifest: dict[str, object],
    records: list[dict[str, object]],
    *,
    expected_source_state: dict[str, object] | None = None,
    expected_civiccast_wheel_sha256: str | None = None,
    require_clean_source: bool = False,
) -> list[str]:
    problems: list[str] = []
    expected_interpreter = {
        "distribution": INTERPRETER_DISTRIBUTION,
        "version": INTERPRETER_VERSION,
        "sha256": INTERPRETER_SHA256,
        "source": INTERPRETER_SOURCE_URL,
        "license": INTERPRETER_LICENSE,
    }
    expected = {
        "schema_version": APP_MANIFEST_SCHEMA_VERSION,
        "app_lock_sha256": APP_REQUIREMENTS_SHA256,
        "app_build_lock_sha256": APP_BUILD_REQUIREMENTS_SHA256,
        "build_toolchain_lock_sha256": APP_BUILD_TOOLCHAIN_LOCK_SHA256,
        "build_toolchain": APP_BUILD_TOOLCHAIN,
        "file_count": len(records),
        "total_bytes": sum(_record_bytes(record) for record in records),
        "interpreter": expected_interpreter,
        "caption_pack": CAPTION_PACK_CONTRACT,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            problems.append(
                f"MANIFEST HEADER MISMATCH: {field}={manifest.get(field)!r} != {value!r}"
            )
    civiccast = manifest.get("civiccast")
    if not isinstance(civiccast, dict):
        problems.append("MANIFEST HEADER MISMATCH: civiccast is not an object")
        return problems
    civiccast_versions = {
        str(record["version"])
        for record in records
        if canonical_distribution_name(str(record["distribution"])) == "civiccast"
    }
    if civiccast_versions != {str(civiccast.get("version"))}:
        problems.append(
            "MANIFEST HEADER MISMATCH: civiccast version does not match installed records"
        )
    wheel_sha256 = civiccast.get("wheel_sha256")
    if not isinstance(wheel_sha256, str) or not _is_hex_digest(wheel_sha256, 64):
        problems.append("MANIFEST HEADER MISMATCH: civiccast wheel_sha256 is not a SHA-256")
    elif (
        expected_civiccast_wheel_sha256 is not None
        and wheel_sha256 != expected_civiccast_wheel_sha256
    ):
        problems.append(
            "MANIFEST HEADER MISMATCH: civiccast wheel_sha256 does not match "
            "the independently supplied wheel identity"
        )
    source_state = civiccast.get("source_state")
    if not isinstance(source_state, dict):
        problems.append("MANIFEST HEADER MISMATCH: civiccast source_state is not an object")
        return problems
    if not _is_hex_digest(source_state.get("head"), 40):
        problems.append("MANIFEST HEADER MISMATCH: source_state.head is not a Git SHA")
    if not isinstance(source_state.get("dirty"), bool):
        problems.append("MANIFEST HEADER MISMATCH: source_state.dirty is not boolean")
    for field in ("diff_sha256", "status_sha256"):
        if not _is_hex_digest(source_state.get(field), 64):
            problems.append(f"MANIFEST HEADER MISMATCH: source_state.{field} is not a SHA-256")
    if require_clean_source and source_state.get("dirty") is not False:
        problems.append("MANIFEST HEADER MISMATCH: release source_state is dirty")
    if expected_source_state is not None:
        expected_identity = {
            field: expected_source_state.get(field)
            for field in ("head", "dirty", "diff_sha256", "status_sha256")
        }
        actual_identity = {
            field: source_state.get(field)
            for field in ("head", "dirty", "diff_sha256", "status_sha256")
        }
        if actual_identity != expected_identity:
            problems.append(
                "MANIFEST HEADER MISMATCH: source_state does not match "
                "the independently supplied checkout identity"
            )
    return problems


def _is_hex_digest(value: object, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    return all(character in "0123456789abcdef" for character in value.lower())


def _verify_derived_trust_artifacts(
    tree: Path,
    records: list[dict[str, object]],
) -> list[str]:
    problems: list[str] = []
    for name, expected in (
        ("SHA256SUMS", _render_sha256sums(records)),
        ("LICENSE-BOM.md", _render_license_bom(records)),
    ):
        path = tree / name
        if not path.is_file():
            problems.append(f"{name} is MISSING from the payload")
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name} is not valid UTF-8")
            continue
        if actual != expected:
            problems.append(f"{name} does not match what app-payload-manifest.json implies")
    return problems


def _retained_civiccast_wheel_provenance(
    tree: Path,
    expected_sha256: str,
    *,
    require_console_launchers: bool,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Anchor installed CivicCast files to the retained source wheel."""

    wheel_path = tree / CIVICCAST_RETAINED_WHEEL_PATH
    ownership: dict[str, tuple[str, str]] = {}
    problems: list[str] = []
    if not wheel_path.is_file():
        return ownership, ["PROVENANCE: retained CivicCast wheel is missing"]
    actual_sha256 = _sha256_file(wheel_path)
    if actual_sha256 != expected_sha256:
        problems.append(
            "PROVENANCE: retained CivicCast wheel SHA-256 does not match the manifest header"
        )
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            names = {name for name in archive.namelist() if name and not name.endswith("/")}
            unsafe = sorted(
                name
                for name in names
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            )
            if unsafe:
                return ownership, [
                    "PROVENANCE: retained CivicCast wheel contains unsafe path(s): "
                    + ", ".join(unsafe)
                ]
            record_names = sorted(name for name in names if name.endswith(".dist-info/RECORD"))
            civiccast_records: list[tuple[str, str]] = []
            for name in record_names:
                dist_info = PurePosixPath(name).parts[0]
                raw_name, separator, version = dist_info.removesuffix(".dist-info").rpartition("-")
                if separator and canonical_distribution_name(raw_name) == CIVICCAST_DISTRIBUTION:
                    civiccast_records.append((dist_info, version))
            if len(civiccast_records) != 1:
                return ownership, [
                    "PROVENANCE: retained CivicCast wheel must contain exactly "
                    f"one CivicCast RECORD; found {len(civiccast_records)}"
                ]
            dist_info, version = civiccast_records[0]
            entry_points_name = f"{dist_info}/entry_points.txt"
            if entry_points_name not in names:
                if require_console_launchers:
                    return ownership, [
                        "PROVENANCE: retained CivicCast wheel has no entry_points.txt"
                    ]
                console_scripts: dict[str, str] = {}
            else:
                entry_points = configparser.ConfigParser()
                try:
                    entry_points.read_string(archive.read(entry_points_name).decode("utf-8"))
                    console_scripts = dict(entry_points.items("console_scripts"))
                except (UnicodeDecodeError, configparser.Error, KeyError) as exc:
                    return ownership, [
                        "PROVENANCE: retained CivicCast entry_points.txt is "
                        f"malformed: {type(exc).__name__}: {exc}"
                    ]
                if console_scripts != CIVICCAST_CONSOLE_ENTRY_POINTS:
                    return ownership, [
                        "PROVENANCE: retained CivicCast console entry points do "
                        "not match reviewed policy"
                    ]

            for name in sorted(names):
                installed = tree / "Lib" / "site-packages" / Path(*PurePosixPath(name).parts)
                payload_path = f"Lib/site-packages/{name}"
                ownership[payload_path] = (CIVICCAST_DISTRIBUTION, version)
                if not installed.is_file():
                    problems.append(
                        f"PROVENANCE: retained CivicCast wheel member is missing: {payload_path}"
                    )
                    continue
                if name != f"{dist_info}/RECORD" and installed.read_bytes() != archive.read(name):
                    problems.append(
                        "PROVENANCE: installed file differs from retained CivicCast "
                        f"wheel: {payload_path}"
                    )

            wheel_record_rows = {
                tuple(row)
                for row in csv.reader(
                    archive.read(f"{dist_info}/RECORD").decode("utf-8").splitlines()
                )
            }
            generated_record_rows: set[tuple[str, ...]] = set()
            launcher_policy = CIVICCAST_CONSOLE_LAUNCHERS if console_scripts else {}
            site_packages = tree / "Lib" / "site-packages"
            for relative, (expected_bytes, expected_sha256) in sorted(launcher_policy.items()):
                launcher = site_packages / Path(*PurePosixPath(relative).parts)
                payload_path = f"Lib/site-packages/{relative}"
                ownership[payload_path] = (CIVICCAST_DISTRIBUTION, version)
                if (
                    not launcher.is_file()
                    or launcher.stat().st_size != expected_bytes
                    or _sha256_file(launcher) != expected_sha256
                ):
                    problems.append(
                        "PROVENANCE: generated CivicCast console launcher does "
                        f"not match reviewed uv output: {payload_path}"
                    )
                    continue
                digest = (
                    base64.urlsafe_b64encode(bytes.fromhex(expected_sha256))
                    .decode("ascii")
                    .rstrip("=")
                )
                generated_record_rows.add((relative, f"sha256={digest}", str(expected_bytes)))

            installed_record = tree / "Lib" / "site-packages" / dist_info / "RECORD"
            try:
                installed_record_rows = {
                    tuple(row)
                    for row in csv.reader(installed_record.read_text(encoding="utf-8").splitlines())
                }
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                problems.append(
                    "PROVENANCE: installed CivicCast RECORD is unreadable: "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                expected_record_rows = wheel_record_rows | generated_record_rows
                if installed_record_rows != expected_record_rows:
                    problems.append(
                        "PROVENANCE: installed CivicCast RECORD differs from the "
                        "retained wheel plus reviewed console-launcher transform"
                    )

            site_packages = tree / "Lib" / "site-packages"
            civiccast_installed: set[str] = set()
            for path in site_packages.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(site_packages).as_posix()
                if relative.startswith("civiccast/") or relative.startswith(f"{dist_info}/"):
                    civiccast_installed.add(relative)
            for name in sorted(civiccast_installed - names):
                problems.append(
                    "PROVENANCE: installed CivicCast file is absent from retained "
                    f"CivicCast wheel: Lib/site-packages/{name}"
                )
    except (OSError, zipfile.BadZipFile) as exc:
        problems.append(
            f"PROVENANCE: retained CivicCast wheel is unreadable: {type(exc).__name__}: {exc}"
        )
    return ownership, problems


def _reviewed_requirement_wheels() -> tuple[
    dict[str, tuple[str, frozenset[str]]],
    list[str],
]:
    """Parse the externally hash-anchored application dependency lock."""

    try:
        lock_bytes = APP_REQUIREMENTS_FILE.read_bytes()
    except OSError as exc:
        return {}, [f"PROVENANCE: app requirements lock is unreadable: {exc}"]
    if hashlib.sha256(lock_bytes).hexdigest() != APP_REQUIREMENTS_SHA256:
        return {}, ["PROVENANCE: app requirements lock SHA-256 does not match reviewed policy"]
    try:
        text = lock_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return {}, ["PROVENANCE: app requirements lock is not valid UTF-8"]

    reviewed: dict[str, tuple[str, frozenset[str]]] = {}
    problems: list[str] = []
    pattern = re.compile(
        r"(?ms)^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)\s*\\"
        r"(?P<body>.*?)(?=^[A-Za-z0-9][A-Za-z0-9._-]*==|\Z)"
    )
    for match in pattern.finditer(text):
        distribution = canonical_distribution_name(match.group(1))
        hashes = frozenset(re.findall(r"--hash=sha256:([0-9a-f]{64})", match.group("body")))
        if not hashes:
            problems.append(
                f"PROVENANCE: {distribution} has no SHA-256 artifacts in the reviewed lock"
            )
            continue
        if distribution in reviewed:
            problems.append(
                f"PROVENANCE: duplicate distribution {distribution} in app requirements lock"
            )
            continue
        reviewed[distribution] = (match.group(2), hashes)
    if not reviewed:
        problems.append("PROVENANCE: app requirements lock contains no distributions")
    return reviewed, problems


def _wheel_member_install_path(
    member: str,
    *,
    distribution: str,
) -> str | None:
    """Map a wheel member to its installed path below site-packages."""

    path = PurePosixPath(member)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    if path.parts[0].endswith(".data"):
        if len(path.parts) < 3:
            return None
        scheme = path.parts[1]
        if scheme in {"purelib", "platlib"}:
            return PurePosixPath(*path.parts[2:]).as_posix()
        if scheme == "headers":
            # `uv pip install --target` places wheel header data beneath the
            # target's include/<distribution> directory and records that
            # transformed location in the installed RECORD.
            return PurePosixPath(
                "include",
                distribution,
                *path.parts[2:],
            ).as_posix()
        return None
    return path.as_posix()


def _retained_dependency_wheel_provenance(
    tree: Path,
    *,
    require_complete_wheelhouse: bool,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Anchor third-party package bytes to hash-authorized retained wheels."""

    reviewed, problems = _reviewed_requirement_wheels()
    ownership: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    wheel_dir = tree / "WHEELS"
    for wheel_path in sorted(wheel_dir.glob("*.whl")) if wheel_dir.is_dir() else []:
        if wheel_path.name == Path(CIVICCAST_RETAINED_WHEEL_PATH).name:
            continue
        try:
            raw_name, parsed_version, _build, _tags = parse_wheel_filename(wheel_path.name)
        except InvalidWheelFilename:
            problems.append(f"PROVENANCE: malformed retained dependency wheel {wheel_path.name}")
            continue
        distribution = canonical_distribution_name(str(raw_name))
        version = str(parsed_version)
        identity = reviewed.get(distribution)
        wheel_hash = _sha256_file(wheel_path)
        if identity is None or version != identity[0] or wheel_hash not in identity[1]:
            problems.append(
                f"PROVENANCE: retained dependency wheel {wheel_path.name} does not "
                "match the reviewed version/hash"
            )
            continue
        if distribution in seen:
            problems.append(f"PROVENANCE: multiple retained wheels claim {distribution}")
            continue
        seen.add(distribution)
        owner = (distribution, version)
        ownership[f"WHEELS/{wheel_path.name}"] = owner
        try:
            with zipfile.ZipFile(wheel_path) as archive:
                members = sorted(
                    name for name in archive.namelist() if name and not name.endswith("/")
                )
                unsafe = [
                    name
                    for name in members
                    if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                ]
                if unsafe:
                    problems.append(
                        "PROVENANCE: retained dependency wheel contains unsafe path(s): "
                        + ", ".join(unsafe)
                    )
                    continue
                for member in members:
                    installed_relative = _wheel_member_install_path(
                        member,
                        distribution=distribution,
                    )
                    if installed_relative is None:
                        continue
                    payload_path = f"Lib/site-packages/{installed_relative}"
                    prior = ownership.get(payload_path)
                    if prior is not None and prior != owner:
                        problems.append(
                            f"PROVENANCE: {payload_path} is claimed by both "
                            f"{prior[0]} {prior[1]} and {distribution} {version}"
                        )
                        continue
                    ownership[payload_path] = owner
                    installed = (
                        tree
                        / "Lib"
                        / "site-packages"
                        / Path(*PurePosixPath(installed_relative).parts)
                    )
                    if not installed.is_file():
                        problems.append(
                            "PROVENANCE: retained dependency wheel member is missing: "
                            f"{payload_path}"
                        )
                        continue
                    # RECORD is an installer-produced consistency ledger, never
                    # the ownership root. Every other installed byte must equal
                    # the hash-authorized wheel member.
                    if member.endswith(".dist-info/RECORD"):
                        continue
                    expected_bytes = archive.read(member)
                    if payload_path == APP_BYTECODE_POLICY_PATH and distribution == "setuptools":
                        expected_bytes = APP_BYTECODE_POLICY_PREFIX + expected_bytes
                    if installed.read_bytes() != expected_bytes:
                        problems.append(
                            "PROVENANCE: installed file differs from retained dependency "
                            f"wheel: {payload_path}"
                        )
                    if (
                        distribution == "pywin32"
                        and installed_relative.startswith("pywin32_system32/")
                        and installed_relative.endswith(".dll")
                    ):
                        root_path = PurePosixPath(installed_relative).name
                        ownership[root_path] = owner
                        copied = tree / root_path
                        if not copied.is_file() or copied.read_bytes() != expected_bytes:
                            problems.append(
                                "PROVENANCE: copied pywin32 runtime DLL differs from "
                                f"retained dependency wheel: {root_path}"
                            )
        except (OSError, zipfile.BadZipFile) as exc:
            problems.append(
                "PROVENANCE: retained dependency wheel is unreadable "
                f"({wheel_path.name}): {type(exc).__name__}: {exc}"
            )

    if require_complete_wheelhouse:
        missing = sorted(set(reviewed) - seen)
        if missing:
            problems.append(
                "PROVENANCE: retained dependency wheelhouse is incomplete; missing: "
                + ", ".join(missing)
            )
    return ownership, problems


def _record_provenance(
    tree: Path,
    civiccast_wheel_sha256: str,
    *,
    require_console_launchers: bool,
    require_dependency_wheels: bool,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Reconstruct installed-file ownership from immutable wheel evidence."""

    ownership, problems = _retained_civiccast_wheel_provenance(
        tree,
        civiccast_wheel_sha256,
        require_console_launchers=require_console_launchers,
    )
    dependency_ownership, dependency_problems = _retained_dependency_wheel_provenance(
        tree,
        require_complete_wheelhouse=require_dependency_wheels,
    )
    problems.extend(dependency_problems)
    for payload_path, owner in dependency_ownership.items():
        prior = ownership.get(payload_path)
        if prior is not None and prior != owner:
            problems.append(
                f"PROVENANCE: {payload_path} is claimed by both "
                f"{prior[0]} {prior[1]} and {owner[0]} {owner[1]}"
            )
            continue
        ownership[payload_path] = owner
    return ownership, problems


def _verify_independent_provenance(
    tree: Path,
    records: list[dict[str, object]],
    civiccast_wheel_sha256: str,
    *,
    require_console_launchers: bool,
    require_dependency_wheels: bool,
) -> list[str]:
    ownership, problems = _record_provenance(
        tree,
        civiccast_wheel_sha256,
        require_console_launchers=require_console_launchers,
        require_dependency_wheels=require_dependency_wheels,
    )
    pywin32_versions = {
        version for distribution, version in ownership.values() if distribution == "pywin32"
    }
    allowed_pywin32_root = {"pythoncom312.dll", "pywintypes312.dll"}

    for record in records:
        path = str(record["path"])
        recorded = (
            canonical_distribution_name(str(record["distribution"])),
            str(record["version"]),
        )
        if path.startswith("Lib/site-packages/"):
            actual = ownership.get(path)
            if actual is None:
                problems.append(f"PROVENANCE: {path} is named by no wheel RECORD")
                continue
            expected_version = component_version_for_payload_path(actual[0], actual[1], path)
            if recorded != (actual[0], expected_version):
                problems.append(
                    f"PROVENANCE: {path} claims {recorded[0]} {recorded[1]} "
                    f"but RECORD/component ownership is {actual[0]} {expected_version}"
                )
                continue
            expected_license = license_for_payload_path(actual[0], path)
        elif path == CIVICCAST_RETAINED_WHEEL_PATH:
            civiccast_versions = {
                version
                for distribution, version in ownership.values()
                if distribution == CIVICCAST_DISTRIBUTION
            }
            if recorded[0] != CIVICCAST_DISTRIBUTION or recorded[1] not in civiccast_versions:
                problems.append(
                    f"PROVENANCE: {path} is not attributed to the retained CivicCast wheel version"
                )
            expected_license = APP_DISTRIBUTION_LICENSE[CIVICCAST_DISTRIBUTION]
        elif path.startswith("WHEELS/") and path.endswith(".whl"):
            actual = ownership.get(path)
            if actual is None:
                problems.append(
                    f"PROVENANCE: {path} is not an authorized retained dependency wheel"
                )
                continue
            expected_version = component_version_for_payload_path(actual[0], actual[1], path)
            if recorded != (actual[0], expected_version):
                problems.append(
                    f"PROVENANCE: {path} claims {recorded[0]} {recorded[1]} "
                    f"but retained-wheel ownership is {actual[0]} {expected_version}"
                )
            expected_license = license_for_payload_path(actual[0], path)
        elif path.startswith(f"{WHISPER_MODEL_PAYLOAD_DIR}/"):
            problems.append(
                "PROVENANCE: legacy caption model bytes must not be embedded in Core; "
                f"the signed captions-large-v3 pack owns {path}"
            )
            continue
        elif path in APP_EXTERNAL_LICENSE_FILES:
            distribution, version, license_, sha256 = APP_EXTERNAL_LICENSE_FILES[path]
            if recorded != (distribution, version):
                problems.append(
                    f"PROVENANCE: {path} claims {recorded[0]} {recorded[1]} "
                    f"but policy requires {distribution} {version}"
                )
            if record["sha256"] != sha256:
                problems.append(f"PROVENANCE: {path} does not match its reviewed source hash")
            expected_license = license_
        elif path.startswith("THIRD-PARTY-LICENSES/"):
            problems.append(f"PROVENANCE: unreviewed external license artifact {path}")
            continue
        elif path in allowed_pywin32_root:
            actual = ownership.get(path)
            if (
                actual is None
                or recorded[0] != "pywin32"
                or recorded[1] != actual[1]
                or recorded[1] not in pywin32_versions
            ):
                problems.append(
                    f"PROVENANCE: {path} is not attributed to the installed pywin32 version"
                )
            expected_license = APP_DISTRIBUTION_LICENSE["pywin32"]
        elif path in MSVC_RUNTIME_FILES:
            expected = MSVC_RUNTIME_FILES[path]
            expected_identity = (
                MSVC_RUNTIME_DISTRIBUTION,
                str(expected["version"]),
            )
            if recorded != expected_identity:
                problems.append(
                    f"PROVENANCE: {path} claims {recorded[0]} {recorded[1]} "
                    f"but policy requires {expected_identity[0]} {expected_identity[1]}"
                )
            if record["sha256"] != expected["sha256"] or record["bytes"] != expected["bytes"]:
                problems.append(f"PROVENANCE: {path} does not match the reviewed Microsoft runtime")
            expected_license = str(expected["license"])
        else:
            if recorded != (INTERPRETER_DISTRIBUTION, INTERPRETER_VERSION):
                problems.append(
                    f"PROVENANCE: {path} is outside wheel RECORDs but claims "
                    f"{recorded[0]} {recorded[1]}"
                )
            expected_license = INTERPRETER_LICENSE

        if str(record["license"]) != expected_license:
            problems.append(
                f"PROVENANCE: {path} records license {record['license']!r}; "
                f"reviewed policy requires {expected_license!r}"
            )
    return problems


def _verify_required_caption_pack_contract(
    manifest: dict[str, object],
    records: list[dict[str, object]],
) -> list[str]:
    problems: list[str] = []
    if manifest.get("caption_pack") != CAPTION_PACK_CONTRACT:
        problems.append(
            "CAPTION PACK: app payload does not bind the exact mandatory "
            "captions-large-v3 component contract"
        )
    embedded_paths = sorted(
        str(record["path"])
        for record in records
        if str(record["path"]).startswith(f"{WHISPER_MODEL_PAYLOAD_DIR}/")
    )
    if embedded_paths:
        problems.append(
            "CAPTION PACK: Core contains legacy duplicate caption model bytes: "
            + ", ".join(embedded_paths)
        )
    return problems


def check_app_payload_verification(
    tree: Path,
    *,
    expected_source_state: dict[str, object] | None = None,
    expected_civiccast_wheel_sha256: str | None = None,
    require_clean_source: bool = False,
    require_caption_pack: bool = False,
    require_console_launchers: bool = False,
    require_dependency_wheels: bool = False,
) -> PayloadVerification:
    """Re-derive and byte-check the payload tree against its manifest."""
    manifest_path = tree / "app-payload-manifest.json"
    if not manifest_path.is_file():
        return PayloadVerification("FAIL", f"no app-payload-manifest.json at {tree}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise TypeError("manifest root is not an object")
        records = manifest.get("files", [])
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise TypeError("manifest files is not a list of objects")
        required_record_fields = {
            "path",
            "sha256",
            "bytes",
            "distribution",
            "version",
            "license",
        }
        for record in records:
            missing_fields = required_record_fields - set(record)
            if missing_fields:
                raise KeyError(f"record is missing field(s): {', '.join(sorted(missing_fields))}")
            _record_bytes(record)
    except UnicodeDecodeError:
        return PayloadVerification(
            "FAIL",
            "app-payload-manifest.json is not valid UTF-8",
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return PayloadVerification(
            "FAIL",
            f"app-payload-manifest.json is malformed: {type(exc).__name__}: {exc}",
        )

    manifest_by_path: dict[str, dict[str, object]] = {}
    duplicates: list[str] = []
    for record in records:
        path = str(record["path"])
        if path in manifest_by_path:
            duplicates.append(path)
        manifest_by_path[path] = record
    if duplicates:
        return PayloadVerification(
            "FAIL",
            "manifest names the same path more than once: " + ", ".join(sorted(set(duplicates))),
        )

    on_disk: dict[str, Path] = {
        p.relative_to(tree).as_posix(): p
        for p in tree.rglob("*")
        if p.is_file() and p.relative_to(tree).as_posix() not in _TRUST_ARTIFACTS
    }

    missing = sorted(set(manifest_by_path) - set(on_disk))
    orphans = sorted(set(on_disk) - set(manifest_by_path))
    mismatched: list[str] = []
    for path in sorted(set(manifest_by_path) & set(on_disk)):
        record = manifest_by_path[path]
        actual = _sha256_file(on_disk[path])
        if actual != record["sha256"]:
            mismatched.append(f"{path} (manifest {record['sha256']} != disk {actual})")
        elif on_disk[path].stat().st_size != record["bytes"]:
            mismatched.append(
                f"{path} (byte count {on_disk[path].stat().st_size} != manifest {record['bytes']})"
            )

    sections = _verify_manifest_header(
        manifest,
        records,
        expected_source_state=expected_source_state,
        expected_civiccast_wheel_sha256=expected_civiccast_wheel_sha256,
        require_clean_source=require_clean_source,
    )
    sections.extend(_verify_derived_trust_artifacts(tree, records))
    civiccast = manifest.get("civiccast")
    civiccast_wheel_sha256 = (
        str(civiccast.get("wheel_sha256")) if isinstance(civiccast, dict) else ""
    )
    sections.extend(
        _verify_independent_provenance(
            tree,
            records,
            civiccast_wheel_sha256,
            require_console_launchers=require_console_launchers,
            require_dependency_wheels=require_dependency_wheels,
        )
    )
    if require_caption_pack:
        sections.extend(_verify_required_caption_pack_contract(manifest, records))
    if missing:
        sections.append("MISSING (in manifest, absent on disk):\n  " + "\n  ".join(missing))
    if orphans:
        sections.append("ORPHAN (on disk, absent from manifest):\n  " + "\n  ".join(orphans))
    if mismatched:
        sections.append("HASH/SIZE MISMATCH:\n  " + "\n  ".join(mismatched))

    # Interpreter presence (D3 gate precondition).
    for required in _REQUIRED_INTERPRETER_FILES:
        if required not in manifest_by_path:
            sections.append(f"MISSING INTERPRETER FILE: {required} not in manifest")

    if any(
        canonical_distribution_name(str(record["distribution"])) == "ctranslate2"
        for record in records
    ):
        for required in MSVC_RUNTIME_FILES:
            if required not in manifest_by_path:
                sections.append(f"MISSING MSVC RUNTIME FILE: {required} required by CTranslate2")

    # Deny-by-default provenance re-check.
    named = {
        str(r["distribution"]) for r in records if r["distribution"] != INTERPRETER_DISTRIBUTION
    }
    unauthorized = sorted(named - AUTHORIZED_APP_DISTRIBUTIONS - AUTHORIZED_NON_WHEEL_COMPONENTS)
    if unauthorized:
        sections.append("UNAUTHORIZED DISTRIBUTION(S): " + ", ".join(unauthorized))
    gpl = sorted(
        {str(r["distribution"]) for r in records if is_prohibited_license(str(r["license"]))}
    )
    if gpl:
        sections.append("GPL/AGPL LICENSE RECORDED FOR: " + ", ".join(gpl))

    if sections:
        return PayloadVerification(
            "FAIL",
            "app payload does not verify against its manifest:\n\n" + "\n\n".join(sections),
        )
    return PayloadVerification(
        "PASS",
        f"app-payload-manifest.json verified against {len(manifest_by_path)} on-disk file(s) "
        "(trust artifacts excluded); interpreter present; all distributions authorized, no GPL/AGPL",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a native application payload tree.")
    parser.add_argument("tree", type=Path, help="the built payload tree directory")
    args = parser.parse_args(argv)
    result = check_app_payload_verification(
        args.tree.resolve(),
        require_caption_pack=True,
        require_console_launchers=True,
        require_dependency_wheels=True,
    )
    print(f"app_payload_verification: {result.status} - {result.detail}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: Apache-2.0
"""Verified security-library replacements for the existing native pack builders."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "native-windows-security-libraries.lock.json"
ARCHIVE_NAME = "civiccast-rc1-security-libraries-windows-x64.zip"


def policy() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _verify_file(path: Path, pin: dict) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != pin["bytes"]
        or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]
    ):
        raise ValueError(f"unverified security-library input: {path}")


def acquire_runtime(cache: Path) -> Path:
    reviewed = policy()
    out = cache / f"security-libraries-{reviewed['archive']['sha256'][:16]}"
    if not out.exists():
        archive = Path(
            os.environ.get(
                "CIVICCAST_SECURITY_LIBRARIES_ZIP",
                str(Path("C:/CivicCastTester/runtime-artifact-mirror") / ARCHIVE_NAME),
            )
        )
        _verify_file(archive, reviewed["archive"])
        cache.mkdir(parents=True, exist_ok=True)
        with (
            zipfile.ZipFile(archive) as bundle,
            tempfile.TemporaryDirectory(prefix=".security-", dir=cache) as temporary,
        ):
            names = bundle.namelist()
            if len(names) != len(set(names)) or set(names) != set(reviewed["files"]):
                raise ValueError("unexpected security-library archive members")
            for name in names:
                if "/" in name or "\\" in name or ":" in name or name in {".", ".."}:
                    raise ValueError("unsafe security-library archive path")
            bundle.extractall(temporary)
            for name, pin in reviewed["files"].items():
                _verify_file(Path(temporary) / name, pin)
            Path(temporary).rename(out)
    for name, pin in reviewed["files"].items():
        _verify_file(out / name, pin)
    if {p.name for p in out.iterdir()} != set(reviewed["files"]):
        raise ValueError("unexpected cached security-library files")
    return out


def assert_compatible_imports(consumers: list[Path], replacements: dict[str, Path]) -> None:
    import pefile

    exports = {}
    for name, path in replacements.items():
        with pefile.PE(str(path)) as pe:
            exports[name.lower()] = {
                symbol.name if symbol.name else symbol.ordinal
                for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols
            }
    for path in consumers:
        with pefile.PE(str(path)) as pe:
            for imported in [
                *getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
                *getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []),
            ]:
                name = imported.dll.decode("ascii").lower()
                if name not in exports:
                    continue
                missing = [
                    symbol.name if symbol.name else symbol.ordinal
                    for symbol in imported.imports
                    if (symbol.name if symbol.name else symbol.ordinal) not in exports[name]
                ]
                if missing:
                    raise ValueError(f"security-library ABI mismatch in {path}: {name}: {missing}")


def _sources(kind: str, runtime: Path) -> dict[str, Path]:
    return {pin[kind]: runtime / name for name, pin in policy()["files"].items() if kind in pin}


def verify_overlay(out: Path, kind: str = "gstreamer") -> None:
    for pin in policy()["files"].values():
        if kind in pin:
            _verify_file(out / pin[kind], pin)


def overlay_directory(out: Path, cache: Path) -> dict[str, tuple[str, str, str]]:
    runtime = acquire_runtime(cache)
    sources = _sources("gstreamer", runtime)
    dlls = {Path(rel).name: source for rel, source in sources.items() if rel.endswith(".dll")}
    consumers = [
        p
        for p in out.rglob("*")
        if p.suffix.lower() in {".dll", ".pyd", ".exe"} and p.name not in dlls
    ]
    assert_compatible_imports([*consumers, *dlls.values()], dlls)
    attribution = {}
    reviewed = policy()
    for name, pin in reviewed["files"].items():
        if "gstreamer" not in pin:
            continue
        relative = pin["gstreamer"]
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime / name, destination)
        attribution[relative] = (
            pin["component"],
            reviewed["components"][pin["component"]]["version"],
            pin["license"],
        )
    return attribution


def secured_postgres_sources(sources: dict[str, Path], cache: Path) -> dict[str, Path]:
    runtime = acquire_runtime(cache)
    replacements = _sources("postgres", runtime)
    dlls = {Path(rel).name: source for rel, source in replacements.items() if rel.endswith(".dll")}
    consumers = [
        p
        for rel, p in sources.items()
        if p.suffix.lower() in {".dll", ".exe"} and rel not in replacements
    ]
    assert_compatible_imports([*consumers, *dlls.values()], dlls)
    return {**sources, **replacements}

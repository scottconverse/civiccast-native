# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the minimal offline OCR closure inside the existing app payload.

PDFium supplies bounded RGB BMP images. Leptonica needs no third-party codecs;
Tesseract, Leptonica and the MSVC runtime are statically linked. No training
tools, network clients, archive parsers or additional DLLs are distributed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.native.app_payload import OCR_FILES, OCR_LOCK_SHA256  # noqa: E402
from scripts.build_native_pyav_wheel import (  # noqa: E402
    find_vcvarsall,
    load_pinned_msvc_environment,
)
from scripts.provision_native_build_toolchain import verify_msvc_cmake_tools  # noqa: E402


def _acquire(spec: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        partial = destination.with_suffix(destination.suffix + ".partial")
        with urllib.request.urlopen(spec["url"], timeout=120) as response:
            partial.write_bytes(response.read())
        _verify(spec, partial)
        partial.replace(destination)
    _verify(spec, destination)


def _verify(spec: dict, destination: Path) -> None:
    data = destination.read_bytes()
    if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError(f"OCR artifact hash/size mismatch: {destination}")


def _extract_sources(archive: Path, scratch: Path) -> None:
    """Reuse only byte-identical sources, preserving incremental compile evidence."""
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = scratch / member.filename
            if not target.resolve().is_relative_to(scratch.resolve()):
                raise ValueError("Unsafe OCR source archive path")
            if member.is_dir():
                continue
            data = bundle.read(member)
            if target.exists():
                if target.read_bytes() != data:
                    raise ValueError(f"Modified OCR source cache: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)


def _run_build_command(args: list[str], environment: dict[str, str]) -> str:
    """Keep successful builds quiet, but retain bounded compiler failure diagnostics."""
    try:
        result = subprocess.run(
            args,
            env=environment,
            check=True,
            text=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.CalledProcessError as error:
        print(f"OCR build command failed ({error.returncode}): {args!r}", file=sys.stderr)
        for name, output in (("stdout", error.stdout), ("stderr", error.stderr)):
            if output:
                bounded = (
                    output
                    if len(output) <= 24000
                    else output[:12000] + "\n[...truncated...]\n" + output[-12000:]
                )
                print(
                    f"--- OCR {name} (bounded first/last output) ---\n{bounded}",
                    file=sys.stderr,
                )
                for line in output.splitlines():
                    if "dotproduct.cpp" in line and "cl.exe" in line:
                        print(f"OCR dotproduct compiler command: {line[:12000]}", file=sys.stderr)
                        break
        raise
    return result.stdout


def _report_tesseract_arch_failure(build: Path) -> None:
    """Expose only bounded compiler-output paths needed to diagnose missing objects."""
    arch = build / "CMakeFiles/libtesseract.dir/src/arch"
    target = arch / "dotproduct.cpp.obj"
    print(f"OCR failed-build object: {target}", file=sys.stderr)
    try:
        print(
            json.dumps(
                {
                    "exists": target.is_file(),
                    "bytes": target.stat().st_size if target.is_file() else None,
                }
            ),
            file=sys.stderr,
        )
        entries = sorted(arch.iterdir(), key=lambda path: path.name) if arch.is_dir() else []
        print(
            "OCR failed-build arch entries: "
            + json.dumps(
                [{"name": path.name, "bytes": path.stat().st_size} for path in entries[:40]]
            ),
            file=sys.stderr,
        )
        response = build / "CMakeFiles/libtesseract.rsp"
        if response.is_file():
            paths = response.read_text(encoding="utf-8-sig", errors="replace")
            bounded = (
                paths
                if len(paths) <= 8000
                else paths[:4000] + "\n[...truncated...]\n" + paths[-4000:]
            )
            print(f"OCR failed-build libtesseract.rsp paths: {bounded!r}", file=sys.stderr)
        else:
            print("OCR failed-build libtesseract.rsp is absent", file=sys.stderr)
    except OSError as error:
        print(f"OCR failed-build path inspection failed: {type(error).__name__}", file=sys.stderr)


def stage_offline_ocr(out: Path, scratch: Path) -> dict[str, tuple[str, str, str]]:
    """Return every shipped file's manifest attribution; fail on tool/source drift."""
    lock_path = ROOT / "native-windows-ocr.lock.json"
    if hashlib.sha256(lock_path.read_bytes()).hexdigest() != OCR_LOCK_SHA256:
        raise ValueError("OCR source/build lock does not match reviewed policy")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    components = lock["components"]
    vcvarsall = find_vcvarsall()
    environment = load_pinned_msvc_environment(vcvarsall)
    # CMake's try_compile subprocess can reinitialize empty cache entries from
    # these environment variables, so clear both sources of ambient launchers.
    environment = {
        key: value
        for key, value in environment.items()
        if key.upper() not in {"CMAKE_C_COMPILER_LAUNCHER", "CMAKE_CXX_COMPILER_LAUNCHER"}
    }
    # VC/Auxiliary/Build/vcvarsall.bat identifies the actual selected installation;
    # a runner may provision it anywhere, independently of ProgramFiles and PATH.
    tools = verify_msvc_cmake_tools(vcvarsall.parents[3], lock["build"])

    def run(args: list[str]) -> str:
        return _run_build_command(args, environment)

    cmake, ninja = (str(tools[name]) for name in ("cmake", "ninja"))
    scratch.mkdir(parents=True, exist_ok=True)
    cache = ROOT / "build/native-ocr-cache"
    for name in ("leptonica", "tesseract"):
        spec = components[name]
        archive = cache / f"{spec['source_directory']}.zip"
        _acquire(spec, archive)
        _extract_sources(archive, scratch)

    prefix = scratch / "prefix"
    common = [
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
        "-DCMAKE_C_COMPILER_LAUNCHER:STRING=",
        "-DCMAKE_CXX_COMPILER_LAUNCHER:STRING=",
        f"-DCMAKE_INSTALL_PREFIX={prefix.as_posix()}",
        f"-DCMAKE_C_FLAGS={' '.join(lock['build']['c_flags'])} /pathmap:{scratch.resolve()}=ocr-source",
        f"-DCMAKE_CXX_FLAGS={' '.join(lock['build']['cxx_flags'])} /pathmap:{scratch.resolve()}=ocr-source",
        "-DCMAKE_EXE_LINKER_FLAGS=/Brepro",
    ]
    for name in ("leptonica", "tesseract"):
        spec = components[name]
        build = scratch / f"build-{name}"
        options = (
            ["-DSW_BUILD=OFF", "-DBUILD_PROG=OFF"]
            + [
                f"-DENABLE_{codec}=OFF"
                for codec in ("ZLIB", "PNG", "GIF", "JPEG", "TIFF", "WEBP", "OPENJPEG")
            ]
            if name == "leptonica"
            else [
                f"-DCMAKE_PREFIX_PATH={prefix.as_posix()}",
                "-DBUILD_TRAINING_TOOLS=OFF",
                "-DBUILD_TESTS=OFF",
                "-DOPENMP_BUILD=OFF",
                "-DGRAPHICS_DISABLED=ON",
                "-DDISABLED_LEGACY_ENGINE=ON",
                "-DDISABLE_TIFF=ON",
                "-DDISABLE_ARCHIVE=ON",
                "-DDISABLE_CURL=ON",
                "-DINSTALL_CONFIGS=OFF",
                "-DENABLE_NATIVE=OFF",
                "-DENABLE_CCACHE=OFF",
            ]
        )
        run(
            [
                cmake,
                "-S",
                str(scratch / spec["source_directory"]),
                "-B",
                str(build),
                *common,
                *options,
            ]
        )
        try:
            run([cmake, "--build", str(build), "--parallel", "2", "--verbose"])
        except subprocess.CalledProcessError:
            if name == "tesseract":
                _report_tesseract_arch_failure(build)
            raise
        run([cmake, "--install", str(build)])

    target = out / "OCR"
    (target / "tessdata").mkdir(parents=True, exist_ok=True)
    (target / "LICENSES").mkdir(exist_ok=True)
    shutil.copy2(prefix / "bin/tesseract.exe", target / "tesseract.exe")
    with pefile.PE(str(target / "tesseract.exe")) as binary:
        imports = {item.dll.decode("ascii").lower() for item in binary.DIRECTORY_ENTRY_IMPORT}
        imports.update(
            item.dll.decode("ascii").lower()
            for item in getattr(binary, "DIRECTORY_ENTRY_DELAY_IMPORT", [])
        )
    if imports != {"kernel32.dll"}:
        raise ValueError(f"OCR static closure has unexpected DLL imports: {sorted(imports)}")
    _acquire(components["tessdata-fast-eng"], cache / "eng.traineddata")
    shutil.copy2(cache / "eng.traineddata", target / "tessdata/eng.traineddata")
    index = {}
    for name in ("tesseract", "leptonica"):
        spec = components[name]
        license_path = target / f"LICENSES/{name}.txt"
        shutil.copy2(scratch / spec["source_directory"] / spec["license_file"], license_path)
        index[license_path.relative_to(out).as_posix()] = (name, spec["version"], spec["license"])
    # tessdata_fast's Apache-2.0 terms are the same full text shipped above.
    shutil.copy2(target / "LICENSES/tesseract.txt", target / "LICENSES/tessdata-fast-eng.txt")
    for relative, name in (
        ("tesseract.exe", "tesseract"),
        ("tessdata/eng.traineddata", "tessdata-fast-eng"),
        ("LICENSES/tessdata-fast-eng.txt", "tessdata-fast-eng"),
    ):
        spec = components[name]
        index[f"OCR/{relative}"] = (name, spec["version"], spec["license"])
    # The executable statically contains Leptonica and the licensed MSVC CRT.
    # Their full notices ship alongside it / in THIRD-PARTY-LICENSES respectively.
    index["OCR/tesseract.exe"] = OCR_FILES["OCR/tesseract.exe"]
    # Preserve static dependencies, toolchain and input hashes inside the signed tree.
    shutil.copy2(lock_path, target / "provenance.json")
    index["OCR/provenance.json"] = ("tesseract", components["tesseract"]["version"], "Apache-2.0")
    version = run([str(target / "tesseract.exe"), "--version"])
    if "5.5.4" not in version or "leptonica-1.87.0" not in version:
        raise ValueError(f"Unexpected compiled OCR runtime: {version}")
    if index != OCR_FILES:
        raise ValueError("OCR files do not match reviewed payload policy")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(stage_offline_ocr(args.out.resolve(), args.scratch.resolve()), indent=2))
    except subprocess.CalledProcessError as error:
        print(error.stdout, error.stderr, file=sys.stderr)
        raise

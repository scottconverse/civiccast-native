# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build CivicCast's reproducible LGPL-only PyAV wheel for native Windows.

PyPI's Windows PyAV wheels bundle an FFmpeg build whose enabled codec set does
not satisfy CivicCast's no-GPL packaging policy.  The native station payload
therefore builds PyAV from the pinned upstream sdist against a pinned,
minimal, LGPL-shared FFmpeg build, repairs the wheel with those shared
libraries, and adds the license/provenance material to PyAV's dist-info
directory.

The command-line build orchestration is intentionally kept beside the pure
verification/repacking helpers below so policy tests can falsify archive,
license, RECORD, and reproducibility behavior without invoking MSVC.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Final


class PyAvWheelBuildError(RuntimeError):
    """The pinned PyAV build or its policy verification failed."""


ROOT: Final[Path] = Path(__file__).resolve().parent.parent
BUILD_REQUIREMENTS: Final[Path] = ROOT / "requirements-native-pyav-build.txt"
DEFAULT_CACHE: Final[Path] = ROOT / "build" / "native-pyav-cache"
DEFAULT_OUTPUT: Final[Path] = ROOT / "build" / "native-wheelhouse"

PYAV_VERSION: Final[str] = "18.0.0"
PYAV_SDIST_URL: Final[str] = (
    "https://files.pythonhosted.org/packages/ae/a4/"
    "570a5a35c8638aba01e739925846c35fdd6b0756a15526766d0a4dd3b7df/"
    "av-18.0.0.tar.gz"
)
PYAV_SDIST_SHA256: Final[str] = "4ef7e72c3d3a872584a1215173b16e0226811037f40dcdbf75992631098df1ba"
PYAV_SDIST_BYTES: Final[int] = 4_340_222

FFMPEG_COMMIT: Final[str] = "8c9502e9b048e21e1cae96477e338ac0635645ba"
FFMPEG_BUILD: Final[str] = f"{FFMPEG_COMMIT[:10]}-minimal-msvc"
FFMPEG_SOURCE_URL: Final[str] = f"https://github.com/FFmpeg/FFmpeg/archive/{FFMPEG_COMMIT}.tar.gz"
FFMPEG_SOURCE_SHA256: Final[str] = (
    "97da8d05b040186096349179bd349168609235781776acee37015e87f8e898fc"
)
FFMPEG_SOURCE_BYTES: Final[int] = 16_902_915
MSYS2_BASE_URL: Final[str] = (
    "https://repo.msys2.org/distrib/x86_64/msys2-base-x86_64-20260611.tar.xz"
)
MSYS2_BASE_SHA256: Final[str] = "a2d047e8ee213c3c6a49a8de427eb1069df12207c0422ff1b3cbb5c905c34221"
MSYS2_BASE_BYTES: Final[int] = 53_555_380
MSYS2_BUILD_PACKAGES: Final[tuple[tuple[str, int, str], ...]] = (
    (
        "diffutils-3.12-1-x86_64.pkg.tar.zst",
        394_515,
        "7902c8ce3d4dd69a0f5e98dc9d5c83c17b23314ba486169db57ef6e2835ce3b6",
    ),
    (
        "make-4.4.1-3-x86_64.pkg.tar.zst",
        514_683,
        "af0bdba17f06fe037f0194069adaa31a8fe45f1a11381501896aea1fae37bd5d",
    ),
    (
        "nasm-2.16.03-1-x86_64.pkg.tar.zst",
        343_935,
        "e5f54d79b94c0290579c20d092603dc97289887ba1c281ac0af88626bfbf1cab",
    ),
)
FFMPEG_CONFIGURE_OPTIONS: Final[tuple[str, ...]] = (
    "--toolchain=msvc",
    "--arch=x86_64",
    "--target-os=win64",
    "--enable-shared",
    "--disable-static",
    "--disable-programs",
    "--disable-doc",
    "--disable-debug",
    "--disable-autodetect",
    "--disable-network",
    "--disable-everything",
    "--enable-avcodec",
    "--enable-avdevice",
    "--enable-avfilter",
    "--enable-avformat",
    "--enable-avutil",
    "--enable-swresample",
    "--enable-swscale",
    "--enable-protocol=file,pipe",
    "--enable-demuxer=wav,mov,matroska,mp3,flac,ogg,mpegts,aac",
    "--enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,aac,mp3,flac,opus,vorbis,h264,hevc,mpeg2video",
    "--enable-parser=aac,h264,hevc,mpegaudio,mpeg4video",
    "--enable-filter=aresample,aformat,anull,volume",
    "--extra-cflags=/Brepro @civiccast-cl.rsp",
    "--extra-ldflags=/Brepro",
)
FFMPEG_X86ASM_EXE: Final[str] = "nasm --reproducible"
MSVC_LINK_RETRY_ATTEMPTS: Final[int] = 5

MSVC_COMPILER_VERSION: Final[str] = "19.50.35730"
MSVC_LINKER_VERSION: Final[str] = "14.50.35730.0"
SOURCE_DATE_EPOCH: Final[int] = 1_704_067_200
UV_VERSION: Final[str] = "uv 0.11.15 (3cffe97c2 2026-05-18 x86_64-pc-windows-msvc)"
UV_SHA256: Final[str] = "d4ffe0b73cbb1fa3d11242567d55c6e9058c4e885fae9272764409583a4e8640"
EXPECTED_WHEEL_SHA256: Final[str] = (
    "445e6a94724b6e83639c3ff4f35135cf3ae7e13a4954957d54cedf91f2e98622"
)
EXPECTED_WHEEL_BYTES: Final[int] = 4_346_940

_DIST_INFO: Final[str] = f"av-{PYAV_VERSION}.dist-info"
_RECORD: Final[str] = f"{_DIST_INFO}/RECORD"
_LICENSE_ROOT: Final[str] = f"{_DIST_INFO}/licenses"
_LGPL_NOTICE: Final[str] = f"{_LICENSE_ROOT}/FFmpeg-LGPL-2.1-or-later.txt"
_PROVENANCE: Final[str] = f"{_DIST_INFO}/FFMPEG-PROVENANCE.json"
_FIXED_ZIP_TIME: Final[tuple[int, int, int, int, int, int]] = (2024, 1, 1, 0, 0, 0)
_ALLOWED_FFMPEG_DLL_PREFIXES: Final[tuple[str, ...]] = (
    "avcodec-",
    "avdevice-",
    "avfilter-",
    "avformat-",
    "avutil-",
    "swresample-",
    "swscale-",
)
_FORBIDDEN_DLL_TOKENS: Final[tuple[str, ...]] = ("x264", "x265", "fdk-aac")
_DOWNLOAD_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "files.pythonhosted.org",
        "github.com",
        "release-assets.githubusercontent.com",
        "codeload.github.com",
        "repo.msys2.org",
    }
)


def ffmpeg_provenance() -> dict[str, object]:
    """Machine-readable notice shipped inside the repaired PyAV wheel.

    Doubles as the wheel's own build-provenance record: alongside the
    FFmpeg component notice, it names the two pinned, hash-verified
    upstream inputs this wheel was compiled FROM -- the PyAV sdist and the
    FFmpeg source archive. Both are acquired via `acquire_verified_artifact`
    with the default `advisory=False`, so they are a hard failure on every
    build lane, self-hosted included (see `verify_artifact`'s docstring) --
    unlike the FINAL COMPILED wheel's own bytes, which can legitimately
    differ by build machine (docs/process/pyav-wheel-reproducibility.md).
    `scripts/verify_native_app_payload.py`'s provenance sweep reads these
    two fields back out of THIS wheel and re-asserts them against the same
    PYAV_SDIST_SHA256/BYTES and FFMPEG_SOURCE_SHA256/BYTES constants to
    authorize a self-hosted-built `av` wheel by build provenance instead of
    by wheel byte hash -- see that module's `_retained_dependency_wheel_
    provenance` and docs/process/pyav-wheel-reproducibility.md.
    """

    return {
        "schema_version": 1,
        "component": "FFmpeg",
        "build": FFMPEG_BUILD,
        "license": "LGPL-2.1-or-later",
        "linkage": "shared DLLs",
        "source_archive_url": FFMPEG_SOURCE_URL,
        "source_archive_sha256": FFMPEG_SOURCE_SHA256,
        "source_archive_bytes": FFMPEG_SOURCE_BYTES,
        "external_libraries": [],
        "configure_options": list(FFMPEG_CONFIGURE_OPTIONS),
        "relinking": (
            "The FFmpeg components are separate shared DLLs under av.libs. "
            "They may be replaced with interface-compatible modified builds; "
            "keep the filenames expected by the repaired extension modules."
        ),
        "pyav_sdist_url": PYAV_SDIST_URL,
        "pyav_sdist_sha256": PYAV_SDIST_SHA256,
        "pyav_sdist_bytes": PYAV_SDIST_BYTES,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_pinned_uv(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Resolve uv once and refuse any executable/version outside the reviewed pin."""

    configured = os.environ.get("CIVICCAST_UV_EXE")
    executable = Path(configured) if configured else Path(shutil.which("uv") or "")
    if not str(executable) or not executable.exists():
        raise PyAvWheelBuildError("the pinned uv executable was not found")
    resolved = executable.resolve()
    actual_sha256 = sha256_file(resolved)
    if actual_sha256 != UV_SHA256:
        raise PyAvWheelBuildError(f"uv executable SHA-256 {actual_sha256} != pinned {UV_SHA256}")
    version = runner(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    actual_version = f"{version.stdout}{version.stderr}".strip()
    if actual_version != UV_VERSION:
        raise PyAvWheelBuildError(f"uv version {actual_version!r} != pinned {UV_VERSION!r}")
    return str(resolved)


def verify_artifact(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    advisory: bool = False,
) -> None:
    """Fail unless an acquired build input has exactly the pinned identity.

    ``advisory=True`` downgrades a mismatch to a logged warning instead of a
    hard failure. This exists ONLY for the final compiled PyAV wheel on the
    self-hosted build lane (see the two ``verify_artifact(candidate, ...)`` /
    ``verify_artifact(output, ...)`` call sites in ``build()``): the MSVC
    compiler can embed build-machine-dependent state (absolute scratch
    paths, PDB paths) into the wheel even when the toolchain identity is
    byte-identical to hosted, so a different physical machine can produce a
    non-byte-identical-but-otherwise-correct wheel. Every OTHER call to this
    function -- every pinned download (uv, the FFmpeg source archive, the
    MSYS2 base, the PyAV sdist) -- always uses the default ``advisory=False``
    and stays a hard failure on any lane. Advisory mode never weakens input
    verification, only the final build's byte-exact reproducibility
    assertion.
    """

    actual_bytes = path.stat().st_size
    actual_sha256 = sha256_file(path)
    mismatch_detail: str | None = None
    if actual_bytes != expected_bytes:
        mismatch_detail = (
            f"{path.name} byte length {actual_bytes} != pinned {expected_bytes}; "
            f"SHA-256 {actual_sha256}"
        )
    elif actual_sha256 != expected_sha256.lower():
        mismatch_detail = f"{path.name} SHA-256 {actual_sha256} != pinned {expected_sha256.lower()}"
    if mismatch_detail is None:
        return
    if advisory:
        print(
            "::warning::PyAV wheel byte-exact reproducibility check is ADVISORY on this "
            f"build lane and did not match the pinned reference: {mismatch_detail}. "
            "Every pinned DOWNLOAD (uv, FFmpeg source, MSYS2 base, PyAV sdist) was still "
            "verified strictly; only the compiled wheel's byte-exact identity is advisory "
            "here. See docs/process/pyav-wheel-reproducibility.md."
        )
        return
    raise PyAvWheelBuildError(mismatch_detail)


def _download_https(url: str, destination: Path) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _DOWNLOAD_HOSTS:
        raise PyAvWheelBuildError(f"refusing download from unapproved URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "CivicCast-native-builder/1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in _DOWNLOAD_HOSTS:
            raise PyAvWheelBuildError(f"download redirected to unapproved URL: {response.geturl()}")
        with destination.open("wb") as target:
            shutil.copyfileobj(response, target)


def acquire_verified_artifact(
    url: str,
    destination: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    downloader: Callable[[str, Path], None] = _download_https,
) -> Path:
    """Reuse only a valid cache entry; otherwise download, verify, then publish."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            verify_artifact(
                destination,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
            )
        except PyAvWheelBuildError:
            destination.unlink()
        else:
            return destination

    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    try:
        downloader(url, partial)
        verify_artifact(
            partial,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or any(":" in part for part in path.parts)
    ):
        raise PyAvWheelBuildError(f"unsafe archive path: {name!r}")
    return path


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    """Extract a zip without permitting traversal or symlink entries."""

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = _safe_member_path(member.filename)
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise PyAvWheelBuildError(f"unsafe archive symlink: {member.filename!r}")
            output = destination.joinpath(*relative.parts)
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output.open("wb") as target:
                shutil.copyfileobj(source, target)


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    """Extract regular files/directories without links, devices, or traversal."""

    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            relative = _safe_member_path(member.name)
            output = destination.joinpath(*relative.parts)
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PyAvWheelBuildError(f"unsafe tar member type: {member.name!r}")
            source = archive.extractfile(member)
            if source is None:
                raise PyAvWheelBuildError(f"could not read tar member: {member.name!r}")
            output.parent.mkdir(parents=True, exist_ok=True)
            with source, output.open("wb") as target:
                shutil.copyfileobj(source, target)


def reproducible_build_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a build environment with deterministic compiler/runtime settings."""

    result = dict(os.environ if environment is None else environment)
    result.update(
        {
            "CL": "/Brepro",
            "LINK": "/Brepro",
            "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
            "PYTHONHASHSEED": "0",
        }
    )
    return result


def parse_set_output(output: str) -> dict[str, str]:
    """Parse `cmd.exe set` output without discarding empty environment values."""

    environment: dict[str, str] = {}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            environment[name] = value
    return environment


def assert_exact_toolchain_versions(
    compiler: subprocess.CompletedProcess[str],
    linker: subprocess.CompletedProcess[str],
) -> None:
    """Refuse a toolchain whose reported compiler or linker version drifted."""

    compiler_output = f"{compiler.stdout}\n{compiler.stderr}"
    linker_output = f"{linker.stdout}\n{linker.stderr}"
    if (
        re.search(
            rf"(?<![\d.]){re.escape(MSVC_COMPILER_VERSION)}(?![\d.])",
            compiler_output,
        )
        is None
    ):
        raise PyAvWheelBuildError(
            f"compiler version is not pinned {MSVC_COMPILER_VERSION}: {compiler_output.strip()!r}"
        )
    if (
        re.search(
            rf"(?<![\d.]){re.escape(MSVC_LINKER_VERSION)}(?![\d.])",
            linker_output,
        )
        is None
    ):
        raise PyAvWheelBuildError(
            f"linker version is not pinned {MSVC_LINKER_VERSION}: {linker_output.strip()!r}"
        )


def build_and_repair_wheel(
    *,
    source_dir: Path,
    ffmpeg_dir: Path,
    build_python: Path,
    work_dir: Path,
    environment: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Compile PyAV against the pinned FFmpeg tree, then vendor its shared DLLs."""

    if not build_python.is_file():
        raise PyAvWheelBuildError(f"isolated build interpreter is missing: {build_python}")
    if not (ffmpeg_dir / "bin").is_dir():
        raise PyAvWheelBuildError(f"pinned FFmpeg bin directory is missing: {ffmpeg_dir / 'bin'}")
    raw_dir = work_dir / "raw"
    repaired_dir = work_dir / "repaired"
    raw_dir.mkdir(parents=True, exist_ok=True)
    repaired_dir.mkdir(parents=True, exist_ok=True)
    build_environment = dict(environment)
    runner(
        [
            str(build_python),
            "setup.py",
            f"--ffmpeg-dir={ffmpeg_dir}",
            "bdist_wheel",
            "--dist-dir",
            str(raw_dir),
        ],
        cwd=source_dir,
        env=build_environment,
        check=True,
    )
    raw_wheels = sorted(raw_dir.glob(f"av-{PYAV_VERSION}-*.whl"))
    if len(raw_wheels) != 1:
        raise PyAvWheelBuildError(f"expected exactly one raw PyAV wheel, found {len(raw_wheels)}")
    runner(
        [
            str(build_python),
            "-m",
            "delvewheel",
            "repair",
            str(raw_wheels[0]),
            "--add-path",
            str(ffmpeg_dir / "bin"),
            "--wheel-dir",
            str(repaired_dir),
        ],
        env=build_environment,
        check=True,
    )
    repaired_wheels = sorted(repaired_dir.glob(f"av-{PYAV_VERSION}-*.whl"))
    if len(repaired_wheels) != 1:
        raise PyAvWheelBuildError(
            f"expected exactly one repaired PyAV wheel, found {len(repaired_wheels)}"
        )
    return repaired_wheels[0]


def assert_runtime_probe_report(report: Mapping[str, object]) -> None:
    """Validate the clean-environment import, DLL-license, and decode report."""

    if report.get("pyav_version") != PYAV_VERSION:
        raise PyAvWheelBuildError(
            f"runtime probe loaded PyAV {report.get('pyav_version')!r}, expected {PYAV_VERSION}"
        )
    dlls = report.get("dlls")
    if not isinstance(dlls, list) or len(dlls) != len(_ALLOWED_FFMPEG_DLL_PREFIXES):
        raise PyAvWheelBuildError(f"runtime probe did not load exactly seven FFmpeg DLLs: {dlls!r}")
    licenses = report.get("licenses")
    if not isinstance(licenses, dict):
        raise PyAvWheelBuildError("runtime probe returned no FFmpeg license map")
    expected_libraries = {prefix.removesuffix("-") for prefix in _ALLOWED_FFMPEG_DLL_PREFIXES}
    if set(licenses) != expected_libraries:
        raise PyAvWheelBuildError(f"runtime probe license map is incomplete: {sorted(licenses)!r}")
    non_lgpl = {
        name: license_
        for name, license_ in licenses.items()
        if license_ != "LGPL version 2.1 or later"
    }
    if non_lgpl:
        raise PyAvWheelBuildError(
            f"runtime probe found non-LGPL FFmpeg library/license(s): {non_lgpl!r}"
        )
    frames = report.get("decoded_frames")
    if not isinstance(frames, int) or frames <= 0:
        raise PyAvWheelBuildError("runtime probe decoded no audio frames")


def _single_directory(parent: Path, expected_name: str) -> Path:
    expected = parent / expected_name
    if not expected.is_dir():
        found = sorted(path.name for path in parent.iterdir())
        raise PyAvWheelBuildError(
            f"archive did not contain expected root {expected_name!r}: {found!r}"
        )
    return expected


def create_isolated_build_environment(
    destination: Path,
    *,
    uv_executable: str = "uv",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Create a Python 3.12 venv containing only the hash-locked build tools."""

    if sys.version_info[:2] != (3, 12):
        raise PyAvWheelBuildError(
            f"the PyAV builder requires Python 3.12, got {sys.version.split()[0]}"
        )
    if not BUILD_REQUIREMENTS.is_file():
        raise PyAvWheelBuildError(f"missing build requirements lock: {BUILD_REQUIREMENTS}")
    lock_text = BUILD_REQUIREMENTS.read_text(encoding="utf-8")
    if "--hash=" not in lock_text:
        raise PyAvWheelBuildError(f"build requirements lock has no hashes: {BUILD_REQUIREMENTS}")
    runner([sys.executable, "-m", "venv", str(destination)], check=True)
    build_python = destination / "Scripts" / "python.exe"
    if not build_python.is_file():
        raise PyAvWheelBuildError(f"venv did not create the Windows interpreter: {build_python}")
    runner(
        [
            uv_executable,
            "pip",
            "install",
            "--python",
            str(build_python),
            "--require-hashes",
            "--no-deps",
            "-r",
            str(BUILD_REQUIREMENTS),
        ],
        check=True,
    )
    return build_python


def find_vcvarsall(
    *,
    environment: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Locate an explicit reviewed MSVC root or the latest matching install."""

    env = os.environ if environment is None else environment
    configured = env.get("CIVICCAST_MSVC_INSTALLATION_PATH")
    if configured:
        vcvarsall = Path(configured) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
        if not vcvarsall.is_file():
            raise PyAvWheelBuildError(f"configured MSVC vcvarsall.bat is missing: {vcvarsall}")
        return vcvarsall
    program_files_x86 = env.get("ProgramFiles(x86)")
    if not program_files_x86:
        raise PyAvWheelBuildError("ProgramFiles(x86) is unavailable; cannot locate vswhere")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        raise PyAvWheelBuildError(f"Visual Studio locator is missing: {vswhere}")
    result = runner(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    installation = Path(result.stdout.strip())
    vcvarsall = installation / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvarsall.is_file():
        raise PyAvWheelBuildError(f"vcvarsall.bat is missing: {vcvarsall}")
    return vcvarsall


def load_pinned_msvc_environment(
    vcvarsall: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    """Load vcvarsall, then refuse unless compiler and linker versions are exact."""

    with tempfile.TemporaryDirectory(prefix="cc-vcvars-") as temporary:
        wrapper = Path(temporary) / "load-msvc.cmd"
        wrapper.write_text(
            "\r\n".join(
                (
                    "@echo off",
                    f'call "{vcvarsall}" x64 >nul',
                    "if errorlevel 1 exit /b %errorlevel%",
                    "set",
                    "",
                )
            ),
            encoding="utf-8",
        )
        captured = runner(
            ["cmd.exe", "/d", "/c", str(wrapper)],
            capture_output=True,
            text=True,
            check=True,
        )
    environment = reproducible_build_environment(parse_set_output(captured.stdout))
    compiler = runner(
        ["cmd.exe", "/d", "/c", "cl.exe"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    linker = runner(
        ["cmd.exe", "/d", "/c", "link.exe"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert_exact_toolchain_versions(compiler, linker)
    return environment


def isolate_ffmpeg_git_discovery(
    environment: Mapping[str, str],
    *,
    source_dir: Path,
) -> dict[str, str]:
    """Prevent FFmpeg configure from describing CivicCast's outer Git checkout.

    Git archive sources contain no ``.git`` directory.  Without a ceiling,
    FFmpeg's version probe walks into the surrounding CivicCast worktree and
    embeds that unrelated HEAD in every DLL, making the reviewed wheel change
    after every CivicCast commit.  Stop discovery at the extraction directory
    so only the pinned FFmpeg archive determines the binary identity.
    """

    isolated = dict(environment)
    isolated["GIT_CEILING_DIRECTORIES"] = str(source_dir.parent.resolve())
    return isolated


def write_msvc_link_retry_wrapper(path: Path) -> None:
    """Retry only transient Windows linker output-file locks during configure.

    FFmpeg's configure probes repeatedly overwrite one ``test.exe``.  Real-time
    scanners can briefly retain that file after a successful probe, causing the
    next otherwise-valid link to fail with LNK1104 and silently changing
    configure results.  Retry that one transient error; preserve every other
    linker failure unchanged.
    """

    path.write_text(
        f"""#!/usr/bin/env bash
attempt=1
while :; do
    output="$(mktemp)" || exit 1
    ./compat/windows/mslink "$@" >"$output" 2>&1
    status=$?
    cat "$output" >&2
    if [ "$status" -eq 0 ]; then
        rm -f "$output"
        exit 0
    fi
    if ! grep -Fq "LNK1104: cannot open file" "$output" || [ "$attempt" -ge "{MSVC_LINK_RETRY_ATTEMPTS}" ]; then
        rm -f "$output"
        exit "$status"
    fi
    rm -f "$output"
    attempt=$((attempt + 1))
    sleep 0.2
done
""",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o755)


def build_minimal_ffmpeg(
    *,
    cache_dir: Path,
    scratch: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Build a shared LGPL FFmpeg with zero external libraries."""

    scratch.mkdir(parents=True, exist_ok=False)
    source_archive = acquire_verified_artifact(
        FFMPEG_SOURCE_URL,
        cache_dir / f"ffmpeg-{FFMPEG_COMMIT}.tar.gz",
        expected_bytes=FFMPEG_SOURCE_BYTES,
        expected_sha256=FFMPEG_SOURCE_SHA256,
    )
    msys_archive = acquire_verified_artifact(
        MSYS2_BASE_URL,
        cache_dir / "msys2-base-x86_64-20260611.tar.xz",
        expected_bytes=MSYS2_BASE_BYTES,
        expected_sha256=MSYS2_BASE_SHA256,
    )
    package_paths: list[Path] = []
    for filename, size, digest in MSYS2_BUILD_PACKAGES:
        package_paths.append(
            acquire_verified_artifact(
                f"https://repo.msys2.org/msys/x86_64/{filename}",
                cache_dir / filename,
                expected_bytes=size,
                expected_sha256=digest,
            )
        )

    msys_root = scratch / "msys64"
    msys_root.mkdir()
    runner(
        [
            "tar.exe",
            "-xf",
            str(msys_archive),
            "-C",
            str(msys_root),
            "--strip-components=1",
        ],
        check=True,
    )
    package_cache = msys_root / "tmp" / "civiccast-build-packages"
    package_cache.mkdir(parents=True)
    for package in package_paths:
        shutil.copy2(package, package_cache / package.name)
    bash = msys_root / "usr" / "bin" / "bash.exe"
    local_packages = " ".join(
        shlex.quote(f"/tmp/civiccast-build-packages/{path.name}") for path in package_paths
    )
    runner(
        [str(bash), "-lc", f"pacman -U --noconfirm {local_packages}"],
        check=True,
    )

    source_extract = scratch / "ffmpeg-source"
    safe_extract_tar(source_archive, source_extract)
    source_dir = _single_directory(source_extract, f"FFmpeg-{FFMPEG_COMMIT}")
    (source_dir / "civiccast-cl.rsp").write_text(
        "/experimental:deterministic\n"
        f'"/pathmap:{source_dir.resolve()}=C:\\CivicCast\\FFmpegSource"\n',
        encoding="utf-8",
        newline="\n",
    )
    linker_wrapper = source_dir / "civiccast-mslink"
    write_msvc_link_retry_wrapper(linker_wrapper)
    install_root = scratch / "install-root"
    output = install_root / "CivicCast" / "FFmpeg"
    environment = isolate_ffmpeg_git_discovery(
        load_pinned_msvc_environment(find_vcvarsall(), runner=runner),
        source_dir=source_dir,
    )
    environment.pop("CL", None)
    environment.pop("LINK", None)
    path_key = next((key for key in environment if key.lower() == "path"), "PATH")
    environment[path_key] = (
        str(msys_root / "usr" / "bin") + os.pathsep + environment.get(path_key, "")
    )
    environment.update(
        {
            "CHERE_INVOKING": "1",
            "MSYS2_ARG_CONV_EXCL": "*",
            "MSYS2_PATH_TYPE": "inherit",
        }
    )
    configure = [
        "./configure",
        "--prefix=/CivicCast/FFmpeg",
        f"--ld=./{linker_wrapper.name}",
        f"--x86asmexe={FFMPEG_X86ASM_EXE}",
        *FFMPEG_CONFIGURE_OPTIONS,
    ]
    configured = runner(
        [str(bash), "-lc", " ".join(shlex.quote(arg) for arg in configure)],
        cwd=source_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    report = configured.stdout
    if (
        "External libraries:\n\nExternal libraries providing hardware acceleration:\n\n"
        not in report.replace("\r\n", "\n")
        or "License: LGPL version 2.1 or later" not in report
    ):
        raise PyAvWheelBuildError(
            "minimal FFmpeg configure report did not prove zero external libraries and LGPL"
        )
    runner(
        [
            str(bash),
            "-lc",
            f"make -j16 && make DESTDIR={install_root.as_posix()} install",
        ],
        cwd=source_dir,
        env=environment,
        check=True,
    )
    for import_library in (output / "bin").glob("*.lib"):
        shutil.copy2(import_library, output / "lib" / import_library.name)
    shutil.copy2(source_dir / "COPYING.LGPLv2.1", output / "LICENSE.txt")
    dlls = sorted((output / "bin").glob("*.dll"))
    if len(dlls) != len(_ALLOWED_FFMPEG_DLL_PREFIXES):
        raise PyAvWheelBuildError(f"minimal FFmpeg emitted unexpected DLL set: {dlls!r}")
    return output


_RUNTIME_PROBE = r"""
import ctypes
import json
import pathlib
import tempfile
import wave

import av

site_packages = pathlib.Path(av.__file__).resolve().parent.parent
libs_dir = site_packages / "av.libs"
prefixes = ("avcodec", "avdevice", "avfilter", "avformat", "avutil", "swresample", "swscale")
dll_paths = sorted(libs_dir.glob("*.dll"))
licenses = {}
for prefix in prefixes:
    matches = [path for path in dll_paths if path.name.lower().startswith(prefix + "-")]
    if len(matches) != 1:
        raise RuntimeError(f"{prefix}: expected one DLL, found {len(matches)}")
    library = ctypes.CDLL(str(matches[0]))
    license_function = getattr(library, prefix + "_license")
    license_function.restype = ctypes.c_char_p
    licenses[prefix] = license_function().decode("ascii")

with tempfile.TemporaryDirectory(prefix="cc-pyav-probe-") as temporary:
    wav_path = pathlib.Path(temporary) / "silence.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    with av.open(str(wav_path)) as container:
        decoded_frames = sum(1 for _frame in container.decode(audio=0))

print(json.dumps({
    "pyav_version": av.__version__,
    "dlls": [path.name for path in dll_paths],
    "licenses": licenses,
    "decoded_frames": decoded_frames,
}, sort_keys=True))
"""


def run_runtime_probe(
    wheel: Path,
    *,
    destination: Path,
    uv_executable: str = "uv",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Install only the produced wheel into a fresh venv and prove import/decode."""

    runner([sys.executable, "-m", "venv", str(destination)], check=True)
    runtime_python = destination / "Scripts" / "python.exe"
    runner(
        [
            uv_executable,
            "pip",
            "install",
            "--python",
            str(runtime_python),
            "--no-deps",
            str(wheel),
        ],
        check=True,
    )
    result = runner(
        [str(runtime_python), "-I", "-c", _RUNTIME_PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    if not isinstance(report, dict):
        raise PyAvWheelBuildError("runtime probe did not return a JSON object")
    assert_runtime_probe_report(report)
    return report


def _record_digest(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _render_record(payloads: Mapping[str, bytes]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(payloads):
        if name == _RECORD:
            continue
        payload = payloads[name]
        writer.writerow((name, _record_digest(payload), str(len(payload))))
    writer.writerow((_RECORD, "", ""))
    return output.getvalue().encode("utf-8")


def _write_deterministic_wheel(path: Path, payloads: Mapping[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name in sorted(payloads):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, payloads[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )


def repack_with_ffmpeg_notices(
    repaired_wheel: Path,
    output_wheel: Path,
    *,
    lgpl_text: bytes,
    provenance: Mapping[str, object],
) -> None:
    """Add FFmpeg obligations and normalize the complete wheel byte-for-byte."""

    with zipfile.ZipFile(repaired_wheel) as archive:
        payloads = {
            member.filename: archive.read(member)
            for member in archive.infolist()
            if not member.is_dir() and member.filename not in {_RECORD, _LGPL_NOTICE, _PROVENANCE}
        }
    payloads[_LGPL_NOTICE] = lgpl_text
    payloads[_PROVENANCE] = (
        json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    payloads[_RECORD] = _render_record(payloads)
    _write_deterministic_wheel(output_wheel, payloads)


def validate_wheel_layout(wheel: Path) -> None:
    """Reject missing obligations, forbidden codecs, or unexpected bundled DLLs."""

    with zipfile.ZipFile(wheel) as archive:
        names = {member.filename for member in archive.infolist() if not member.is_dir()}

    dll_names = sorted(
        PurePosixPath(name).name.lower() for name in names if name.lower().endswith(".dll")
    )
    forbidden = [
        name for name in dll_names if any(token in name for token in _FORBIDDEN_DLL_TOKENS)
    ]
    if forbidden:
        raise PyAvWheelBuildError(f"forbidden DLL(s) in PyAV wheel: {forbidden}")

    unexpected = [
        name
        for name in dll_names
        if not any(name.startswith(prefix) for prefix in _ALLOWED_FFMPEG_DLL_PREFIXES)
    ]
    if unexpected:
        raise PyAvWheelBuildError(f"unexpected bundled DLL(s) in PyAV wheel: {unexpected}")

    missing_dlls = [
        prefix
        for prefix in _ALLOWED_FFMPEG_DLL_PREFIXES
        if not any(name.startswith(prefix) for name in dll_names)
    ]
    if missing_dlls:
        raise PyAvWheelBuildError(f"missing FFmpeg DLL family/families: {missing_dlls}")

    required = {_LGPL_NOTICE, _PROVENANCE, _RECORD}
    missing = sorted(required - names)
    if missing:
        raise PyAvWheelBuildError(f"missing FFmpeg notice/provenance file(s): {missing}")


def build(
    *,
    output_dir: Path,
    cache_dir: Path,
    scratch: Path,
    advisory_wheel_hash: bool = False,
) -> tuple[Path, dict[str, object]]:
    """Build, legally verify, and runtime-test the pinned native PyAV wheel.

    ``advisory_wheel_hash`` -- see ``verify_artifact``'s docstring -- only
    affects the two FINAL compiled-wheel identity checks below (``candidate``
    and ``output``); every pinned-download verification in this function
    stays strict regardless.
    """

    if scratch.exists() and any(scratch.iterdir()):
        raise PyAvWheelBuildError(f"scratch directory must be empty: {scratch}")
    scratch.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    uv_executable = resolve_pinned_uv()

    pyav_sdist = acquire_verified_artifact(
        PYAV_SDIST_URL,
        cache_dir / f"av-{PYAV_VERSION}.tar.gz",
        expected_bytes=PYAV_SDIST_BYTES,
        expected_sha256=PYAV_SDIST_SHA256,
    )
    source_extract = scratch / "source"
    safe_extract_tar(pyav_sdist, source_extract)
    source_dir = _single_directory(source_extract, f"av-{PYAV_VERSION}")
    ffmpeg_dir = build_minimal_ffmpeg(
        cache_dir=cache_dir,
        scratch=scratch / "ffmpeg-build",
    )
    lgpl_text = ffmpeg_dir / "LICENSE.txt"
    if not lgpl_text.is_file():
        raise PyAvWheelBuildError(f"FFmpeg archive has no LICENSE.txt: {ffmpeg_dir}")
    if b"LESSER GENERAL PUBLIC LICENSE" not in lgpl_text.read_bytes():
        raise PyAvWheelBuildError("FFmpeg LICENSE.txt is not the expected LGPL text")

    build_python = create_isolated_build_environment(
        scratch / "build-env",
        uv_executable=uv_executable,
    )
    vcvarsall = find_vcvarsall()
    build_environment = load_pinned_msvc_environment(vcvarsall)
    repaired = build_and_repair_wheel(
        source_dir=source_dir,
        ffmpeg_dir=ffmpeg_dir,
        build_python=build_python,
        work_dir=scratch / "wheel-build",
        environment=build_environment,
    )

    candidate = scratch / repaired.name
    repack_with_ffmpeg_notices(
        repaired,
        candidate,
        lgpl_text=lgpl_text.read_bytes(),
        provenance=ffmpeg_provenance(),
    )
    validate_wheel_layout(candidate)
    verify_artifact(
        candidate,
        expected_bytes=EXPECTED_WHEEL_BYTES,
        expected_sha256=EXPECTED_WHEEL_SHA256,
        advisory=advisory_wheel_hash,
    )
    runtime_report = run_runtime_probe(
        candidate,
        destination=scratch / "runtime-probe",
        uv_executable=uv_executable,
    )

    output = output_dir / candidate.name
    shutil.copyfile(candidate, output)
    verify_artifact(
        output,
        expected_bytes=EXPECTED_WHEEL_BYTES,
        expected_sha256=EXPECTED_WHEEL_SHA256,
        advisory=advisory_wheel_hash,
    )
    return output, runtime_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build CivicCast's pinned reproducible LGPL-only PyAV wheel."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--scratch",
        type=Path,
        help="empty scratch directory to preserve (default: temporary and removed)",
    )
    parser.add_argument(
        "--advisory-wheel-hash",
        action="store_true",
        help=(
            "log a warning instead of failing when the FINAL compiled wheel's byte-exact "
            "hash does not match the pinned reference (every pinned download still "
            "verifies strictly). Intended for build lanes running on a different physical "
            "machine than the one the pinned hash was reviewed on -- see verify_artifact()."
        ),
    )
    args = parser.parse_args(argv)

    if args.scratch is not None:
        output, report = build(
            output_dir=args.output_dir.resolve(),
            cache_dir=args.cache_dir.resolve(),
            scratch=args.scratch.resolve(),
            advisory_wheel_hash=args.advisory_wheel_hash,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="cc-pyav-build-") as temporary:
            output, report = build(
                output_dir=args.output_dir.resolve(),
                cache_dir=args.cache_dir.resolve(),
                scratch=Path(temporary),
                advisory_wheel_hash=args.advisory_wheel_hash,
            )
    print(
        json.dumps(
            {
                "wheel": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256_file(output),
                "runtime_probe": report,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PyAvWheelBuildError as error:
        raise SystemExit(f"build_native_pyav_wheel: {error}") from error

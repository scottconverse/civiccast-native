#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Build the signed native ``native-cuda-runtime`` component pack: the
Windows cuBLAS + cuDNN runtime DLLs a capable station needs to run caption
inference on GPU.

The gap this closes: ``civiccast.native.station_runtime.resolve_cuda_bin_dir``
already ships (a prior work package) -- ``resolve_whisper_device`` selects
``cuda`` only when both ``cublas64_12.dll`` and ``cudnn64_9.dll`` are
verifiably staged at ``<root>\dependencies\cuda\bin``. Nothing built the
artifact that satisfies that gate: cuBLAS/cuDNN are absent on the base
station install (owner review finding, station_runtime.py's own dated
comment, 2026-08-15) and only ever arrive via a separate CUDA component pack.
This script is that builder.

Mirrors ``scripts/build_native_ffmpeg_pack.py``'s conventions: pinned-input
validation before packing, a signed ZIP64 pack via ``build_native_pack``, a
development-signing-key guard, and a ``--report`` JSON. Differs in shape
where the inputs themselves differ:

* The two inputs are PyPI wheels (``nvidia-cublas-cu12``, ``nvidia-cudnn-
  cu12``), not a hash-pinned archive from the reviewed native-Windows
  runtime-dependency lock -- CUDA is a Python-ecosystem redistribution
  channel, not a native-toolchain one, so ``--acquire`` resolves each
  wheel's real download URL from PyPI's own JSON API (the wheel's on-disk
  path under ``files.pythonhosted.org`` is a content-hash directory this
  builder cannot precompute) and then verifies the downloaded bytes against
  this builder's OWN pinned byte-length + SHA-256 -- never trusting the API
  response's own hash for identity, only for locating the file.
* This pack ships EVERY DLL each wheel carries under its own
  ``nvidia/cublas/bin/``/``nvidia/cudnn/bin/`` directory, flattened into
  ``payload/bin/`` -- not a minimized PE-import closure the way the FFmpeg
  pack's ``FFMPEG_BIN_PINS`` is. cuBLAS/cuDNN's own inter-DLL dependency
  graph (cuBLAS on cuBLASLt; cuDNN's `cudnn64_9.dll` front-end on its several
  per-backend `cudnn_*64_9.dll` engine libraries) is NVIDIA's to define, and
  re-deriving it with a PE walk the way FFmpeg's closure is derived would
  risk silently dropping a DLL faster-whisper's own CUDA execution provider
  loads indirectly at model-load time, not at pack-build time.
* cuBLAS and cuDNN are proprietary NVIDIA software under NVIDIA's own EULAs,
  not an open-source license this pack could bundle verbatim text for (see
  ``civiccast.native.runtime_licenses``'s Category 8 header). The pack
  carries REFERENCE license texts naming the governing agreement and its
  URL, plus the required NVIDIA attribution string, rather than a
  redistributed copy of NVIDIA's copyrighted EULA text.

## Payload layout, and why it is ``bin/``-rooted

``native_pack_staging::pack_extraction_destination`` maps this component to
``<INSTDIR>\dependencies\cuda`` -- the SAME per-component bridge shape
``native-ffmpeg-runtime`` already uses for ``<INSTDIR>\dependencies\ffmpeg``.
Rooting the payload at ``bin/`` therefore lands ``cublas64_12.dll`` at
exactly ``<INSTDIR>\dependencies\cuda\bin\cublas64_12.dll`` -- the path
``station_runtime.cuda_bin_dir`` already computes and
``resolve_cuda_bin_dir``'s presence gate already checks, reached without
inventing a second convention anywhere.

## OPTIONAL, not required

Unlike ``native-ffmpeg-runtime``/``native-server-binaries``, this component
is NOT enrolled in ``native_pack_staging::DEFAULT_REQUIRED_COMPONENTS``: a
station with no NVIDIA GPU, or one whose operator declines the extra
download, must install and run identically to today, on CPU. It is enrolled
in ``native_pack_staging::DEFAULT_OPTIONAL_COMPONENTS`` instead -- present and
staged, it is verified exactly as strictly as any required pack (a corrupt or
tampered optional pack still fails staging loud); absent, setup simply
continues without it and the presence gate falls back to CPU, exactly as it
already does today for every station that has not obtained this pack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast._native_version import __version__  # noqa: E402
from civiccast.installer.native_packs import build_native_pack  # noqa: E402
from civiccast.native.runtime_licenses import (  # noqa: E402
    classify_cuda_pack_file,
    is_gpl_license,
)

_REPARSE_POINT: Final[int] = 0x400

#: The pack "component" identity. Mirrored on the Rust side by
#: ``native_pack_staging::CUDA_RUNTIME_COMPONENT`` (a drift-guard test there
#: pins the two against each other, the same way ``FFMPEG_RUNTIME_COMPONENT``
#: already is).
CUDA_RUNTIME_COMPONENT: Final[str] = "native-cuda-runtime"

#: The exact DLL names ``civiccast.native.station_runtime``'s presence gate
#: checks for (``_CUDA_REQUIRED_DLL_NAMES``). Kept as this builder's OWN
#: literal -- not a cross-module import of a private name -- and cross-
#: checked against the real attribute by
#: ``tests/native/test_build_native_cuda_pack.py``'s drift-guard test, the
#: same "pin the literal, test the pin" shape ``FFMPEG_RUNTIME_COMPONENT``'s
#: Rust-side cross-language guard already uses. If the pinned wheels do not
#: actually carry both of these names, :func:`build_cuda_pack` stops the
#: build rather than shipping a pack the gate can never see.
CUDA_REQUIRED_DLL_NAMES: Final[tuple[str, ...]] = ("cublas64_12.dll", "cudnn64_9.dll")

#: The required NVIDIA attribution string this pack's NOTICE must carry
#: verbatim.
NVIDIA_ATTRIBUTION_NOTICE: Final[str] = (
    "This software contains source code provided by NVIDIA Corporation."
)

#: Reference URLs for the two governing NVIDIA EULAs (owner-approved plan).
#: Neither license's text is reproduced verbatim in this repository or in the
#: pack this builder produces -- see the module doc and Category 8's header
#: in ``civiccast.native.runtime_licenses`` for why.
CUDA_TOOLKIT_EULA_URL: Final[str] = "https://docs.nvidia.com/cuda/eula"
CUDNN_EULA_URL: Final[str] = "https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html"

_PYPI_API_HOST: Final[str] = "pypi.org"
_PYPI_FILE_HOST: Final[str] = "files.pythonhosted.org"


class CudaPackBuildError(RuntimeError):
    """The native-cuda-runtime pack could not be built."""


@dataclass(frozen=True)
class _WheelPin:
    """One pinned PyPI wheel input: identity for acquisition
    (``pypi_project``/``version``/``filename``), a fail-closed byte-identity
    check (``bytes``/``sha256``), and where inside the wheel its runtime
    DLLs live (``wheel_bin_prefix``, a POSIX zip-member prefix)."""

    pypi_project: str
    version: str
    filename: str
    bytes: int
    sha256: str
    wheel_bin_prefix: str


#: Pins verified against PyPI (coordinator-supplied, 2026-08-15 owner-approved
#: plan "option A"). ``wheel_bin_prefix`` is each wheel's own on-disk layout
#: (``nvidia-cublas-cu12``/``nvidia-cudnn-cu12`` both vendor their Windows
#: runtime DLLs under ``nvidia/<library>/bin/`` -- the same layout PyTorch's
#: own CUDA wheels rely on to find these libraries at import time).
CUDA_WHEEL_PINS: Final[dict[str, _WheelPin]] = {
    "cublas": _WheelPin(
        pypi_project="nvidia-cublas-cu12",
        version="12.9.2.10",
        filename="nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
        bytes=553_162_896,
        sha256="623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",
        wheel_bin_prefix="nvidia/cublas/bin/",
    ),
    "cudnn": _WheelPin(
        pypi_project="nvidia-cudnn-cu12",
        version="9.24.0.43",
        filename="nvidia_cudnn_cu12-9.24.0.43-py3-none-win_amd64.whl",
        bytes=737_103_728,
        sha256="cbd41a0ab084422c936dc9fb2fc89be5ea9a85bc421c6f23d0243bdfc945fbef",
        wheel_bin_prefix="nvidia/cudnn/bin/",
    ),
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_regular_file(path: Path, *, label: str) -> Path:
    try:
        details = path.lstat()
    except OSError as exc:
        raise CudaPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise CudaPackBuildError(f"{label} must be a regular non-reparse file: {path}")
    return path


def _validate_pinned_file(
    path: Path, *, expected_bytes: int, expected_sha256: str, label: str
) -> None:
    path = _require_regular_file(path, label=label)
    data = path.read_bytes()
    if len(data) != expected_bytes:
        raise CudaPackBuildError(
            f"{label} byte length mismatch: expected {expected_bytes}, observed {len(data)}"
        )
    observed = _sha256_bytes(data)
    if observed != expected_sha256:
        raise CudaPackBuildError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, observed {observed}"
        )


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    """Keep development trust roots out of an accidental release build (same
    contract as every sibling pack builder's guard)."""

    if key_id.startswith("development-") and not allow_development_key:
        raise CudaPackBuildError(
            "development pack signing keys require --allow-development-key; "
            "release packaging must use Scott-approved production key custody"
        )


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        raise CudaPackBuildError(f"pack signing private key is missing: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise CudaPackBuildError("pack signing private key must be Ed25519")
    return key


# ---------------------------------------------------------------------------
# Acquisition (--acquire): resolve each wheel's real URL from PyPI, download,
# verify against this builder's OWN pins.
# ---------------------------------------------------------------------------


def _resolve_pypi_wheel_url(project: str, version: str, filename: str) -> str:
    """Resolve ``filename``'s real download URL from PyPI's own JSON API for
    ``project``==``version``.

    PyPI's warehouse serves every file from a content-hash-derived directory
    under ``files.pythonhosted.org`` that cannot be precomputed from this
    builder's pinned SHA-256 alone, so the URL is looked up, never guessed or
    hand-constructed. The API response is used ONLY to locate the file --
    this builder's own pinned ``bytes``/``sha256`` (checked by
    :func:`_validate_pinned_file` after download, not here) remain the sole
    trust boundary for the file's identity.
    """

    api_url = f"https://{_PYPI_API_HOST}/pypi/{project}/{version}/json"
    request = urllib.request.Request(
        api_url, headers={"User-Agent": "CivicCast-native-cuda-pack-builder/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    for entry in payload.get("urls", []):
        if entry.get("filename") == filename:
            url = str(entry.get("url"))
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != _PYPI_FILE_HOST:
                raise CudaPackBuildError(
                    f"PyPI resolved an unapproved download host for {filename}: {url}"
                )
            return url
    raise CudaPackBuildError(
        f"PyPI release {project}=={version} does not list a file named {filename!r}"
    )


def _download_to(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "CivicCast-native-cuda-pack-builder/1"}
    )
    partial = destination.with_name(f"{destination.name}.partial")
    partial.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            partial.open("wb") as handle,
        ):
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def acquire_cuda_pack_sources(cache: Path) -> dict[str, Path]:
    """Download + verify the two pinned NVIDIA wheels into ``cache``,
    returning ``{"cublas": path, "cudnn": path}``.

    ``cache`` is caller-controlled and MUST live outside the repository --
    callers pass a scratch/temp directory, mirroring
    ``acquire_ffmpeg_pack_sources``'s own contract. Idempotent: a
    already-cached, still-verifying file is reused rather than re-downloaded.
    """

    cache.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, Path] = {}
    for key, pin in CUDA_WHEEL_PINS.items():
        destination = cache / pin.filename
        already_verified = False
        if destination.is_file():
            try:
                _validate_pinned_file(
                    destination,
                    expected_bytes=pin.bytes,
                    expected_sha256=pin.sha256,
                    label=f"pinned {key} wheel",
                )
                already_verified = True
            except CudaPackBuildError:
                destination.unlink()
        if not already_verified:
            url = _resolve_pypi_wheel_url(pin.pypi_project, pin.version, pin.filename)
            _download_to(url, destination)
            _validate_pinned_file(
                destination,
                expected_bytes=pin.bytes,
                expected_sha256=pin.sha256,
                label=f"pinned {key} wheel",
            )
        resolved[key] = destination
    return resolved


# ---------------------------------------------------------------------------
# Wheel -> flattened bin/ extraction
# ---------------------------------------------------------------------------


def _extract_wheel_bin_dlls(wheel_path: Path, wheel_bin_prefix: str) -> dict[str, bytes]:
    """Every ``.dll`` directly under ``wheel_bin_prefix`` inside
    ``wheel_path`` (a real PyPI wheel -- itself a zip archive), keyed by its
    flattened basename. Only files DIRECTLY under the prefix are taken (no
    ``/`` in the remainder) -- neither wheel nests a further subdirectory
    under its own ``bin/``, and refusing to recurse means a future wheel
    layout change that DID add one is a visible "0 DLLs found" build failure
    rather than a silent partial selection.
    """

    extracted: dict[str, bytes] = {}
    with zipfile.ZipFile(wheel_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not name.startswith(wheel_bin_prefix):
                continue
            remainder = name[len(wheel_bin_prefix) :]
            if "/" in remainder or not remainder.lower().endswith(".dll"):
                continue
            extracted[remainder] = archive.read(info)
    return extracted


def _render_eula_reference(*, title: str, url: str) -> str:
    return (
        f"{title} -- license reference\n"
        "\n"
        f"{NVIDIA_ATTRIBUTION_NOTICE}\n"
        "\n"
        "Use of the files this component ships is governed by NVIDIA's own\n"
        "end-user license agreement, published at:\n"
        "\n"
        f"  {url}\n"
        "\n"
        "This file is a REFERENCE, not a verbatim copy of that agreement: NVIDIA's\n"
        "EULA is proprietary text this repository does not have redistribution\n"
        "rights to reproduce. Read the agreement at the URL above before using the\n"
        "software this component stages.\n"
    )


def _render_notice(bin_paths: tuple[str, ...]) -> str:
    packed = "\n".join(f"  {path}" for path in bin_paths)
    cublas = CUDA_WHEEL_PINS["cublas"]
    cudnn = CUDA_WHEEL_PINS["cudnn"]
    return (
        "CivicCast native CUDA-runtime pack\n"
        "\n"
        f"{NVIDIA_ATTRIBUTION_NOTICE}\n"
        "\n"
        f"cuBLAS {cublas.version} and cuDNN {cudnn.version}, the Windows x86_64\n"
        f"runtime DLLs NVIDIA distributes as the {cublas.pypi_project} and\n"
        f"{cudnn.pypi_project} PyPI wheels.\n"
        "\n"
        "These binaries are proprietary NVIDIA software distributed under NVIDIA's\n"
        "own end-user license agreements, not an open-source license. This pack does\n"
        "not and cannot re-license them; using the software staged from this pack\n"
        "means accepting those agreements, reproduced by REFERENCE (not verbatim --\n"
        "see the packed license files) here:\n"
        "\n"
        f"  CUDA Toolkit EULA (governs cuBLAS): {CUDA_TOOLKIT_EULA_URL}\n"
        f"  cuDNN Supplement to the EULA:       {CUDNN_EULA_URL}\n"
        "\n"
        "Files in this component:\n"
        f"{packed}\n"
        "\n"
        "SCOPE OF THIS NOTICE\n"
        "--------------------\n"
        "This pack ships the runtime DLLs verbatim and unmodified, exactly as\n"
        "NVIDIA publishes them in the pinned wheels named above -- CivicCast does\n"
        "not build, patch, or relink them. This notice records the license\n"
        "reference this investigation confirmed; it is not a substitute for reading\n"
        "the linked agreements.\n"
    )


def _require_full_license_provenance(sources: dict[str, Path]) -> None:
    """Refuse the build if any packed path has no confirmed license, or a
    confirmed license that is GPL-family (impossible for genuine cuBLAS/cuDNN
    bytes, but checked anyway -- the same defense-in-depth posture
    ``build_native_ffmpeg_pack``'s equivalent gate takes). Runs on every path
    this build is ABOUT to pack, so a future addition to the extracted DLL
    set that does not match ``CUDA_PACK_BIN_BASENAME_PREFIX_LICENSE``'s
    prefixes fails the build loud instead of shipping an unreviewed file
    silently."""

    unresolved: list[str] = []
    gpl_flagged: list[tuple[str, str]] = []
    for relative_path in sorted(sources):
        if relative_path.startswith("notices/"):
            continue  # this builder's own generated NOTICE, not NVIDIA bytes
        license_id = classify_cuda_pack_file(relative_path)
        if license_id is None:
            unresolved.append(relative_path)
        elif is_gpl_license(license_id):
            gpl_flagged.append((relative_path, license_id))
    if gpl_flagged:
        raise CudaPackBuildError(
            "native-cuda-runtime pack refuses GPL/AGPL-family entries (impossible "
            "for genuine NVIDIA bytes -- this indicates a corrupted classification "
            "table, not a real license change): "
            + ", ".join(f"{path} ({license_id})" for path, license_id in gpl_flagged)
        )
    if unresolved:
        raise CudaPackBuildError(
            "native-cuda-runtime pack has unconfirmed license provenance for: "
            + ", ".join(unresolved[:10])
            + (f" (+{len(unresolved) - 10} more)" if len(unresolved) > 10 else "")
        )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_cuda_pack(
    *,
    output: Path,
    cublas_wheel: Path,
    cudnn_wheel: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    compatible_core: str | None = None,
) -> dict[str, object]:
    """Validate the pinned wheel inputs and build the signed
    ``native-cuda-runtime`` pack.

    Stops (raises :class:`CudaPackBuildError`) rather than shipping a pack
    the presence gate can never see when the extracted DLL set does not
    carry both :data:`CUDA_REQUIRED_DLL_NAMES` -- the exact names
    ``civiccast.native.station_runtime``'s ``_CUDA_REQUIRED_DLL_NAMES``
    checks for.
    """

    cublas_pin = CUDA_WHEEL_PINS["cublas"]
    cudnn_pin = CUDA_WHEEL_PINS["cudnn"]
    _validate_pinned_file(
        cublas_wheel,
        expected_bytes=cublas_pin.bytes,
        expected_sha256=cublas_pin.sha256,
        label="pinned cublas wheel",
    )
    _validate_pinned_file(
        cudnn_wheel,
        expected_bytes=cudnn_pin.bytes,
        expected_sha256=cudnn_pin.sha256,
        label="pinned cudnn wheel",
    )

    cublas_dlls = _extract_wheel_bin_dlls(cublas_wheel, cublas_pin.wheel_bin_prefix)
    cudnn_dlls = _extract_wheel_bin_dlls(cudnn_wheel, cudnn_pin.wheel_bin_prefix)
    if not cublas_dlls:
        raise CudaPackBuildError(
            f"no DLLs found under {cublas_pin.wheel_bin_prefix!r} in {cublas_wheel}"
        )
    if not cudnn_dlls:
        raise CudaPackBuildError(
            f"no DLLs found under {cudnn_pin.wheel_bin_prefix!r} in {cudnn_wheel}"
        )

    collisions = sorted(set(cublas_dlls) & set(cudnn_dlls))
    if collisions:
        raise CudaPackBuildError(
            "cuBLAS and cuDNN wheels ship colliding DLL basenames, refusing to "
            f"flatten them silently onto one bin/ directory: {collisions}"
        )

    flattened: dict[str, bytes] = {**cublas_dlls, **cudnn_dlls}
    missing_required = [name for name in CUDA_REQUIRED_DLL_NAMES if name not in flattened]
    if missing_required:
        raise CudaPackBuildError(
            "STOP: the pinned wheels do not ship the DLL name(s) "
            f"{missing_required} that civiccast.native.station_runtime's presence "
            "gate checks for (_CUDA_REQUIRED_DLL_NAMES) -- refusing to ship a pack "
            "the gate can never see. Re-pin the wheels and CUDA_REQUIRED_DLL_NAMES "
            "together after confirming the real shipped name against the gate; "
            "never change one without the other."
        )

    with tempfile.TemporaryDirectory(prefix="civiccast-cuda-pack-") as temporary:
        temp_root = Path(temporary)
        sources: dict[str, Path] = {}

        bin_dir = temp_root / "staged-bin"
        bin_dir.mkdir()
        for name, data in flattened.items():
            path = bin_dir / name
            path.write_bytes(data)
            sources[f"bin/{name}"] = path

        cuda_license_path = temp_root / "cuda-eula-reference.txt"
        cuda_license_path.write_text(
            _render_eula_reference(
                title="CUDA Toolkit EULA (governs cuBLAS)", url=CUDA_TOOLKIT_EULA_URL
            ),
            encoding="utf-8",
            newline="\n",
        )
        sources["licenses/cuda/LICENSE.txt"] = cuda_license_path

        cudnn_license_path = temp_root / "cudnn-eula-reference.txt"
        cudnn_license_path.write_text(
            _render_eula_reference(
                title="cuDNN Supplement to the CUDA Toolkit EULA", url=CUDNN_EULA_URL
            ),
            encoding="utf-8",
            newline="\n",
        )
        sources["licenses/cudnn/LICENSE.txt"] = cudnn_license_path

        notice_path = temp_root / "NOTICE.txt"
        notice_path.write_text(
            _render_notice(tuple(sorted(f"bin/{name}" for name in flattened))),
            encoding="utf-8",
            newline="\n",
        )
        sources["notices/native-cuda-runtime.txt"] = notice_path

        _require_full_license_provenance(sources)

        result = build_native_pack(
            output=output,
            component=CUDA_RUNTIME_COMPONENT,
            product_version=product_version,
            compatible_core=compatible_core or product_version,
            sources=sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={
                "cublas_wheel_version": cublas_pin.version,
                "cudnn_wheel_version": cudnn_pin.version,
                "required_dll_names": list(CUDA_REQUIRED_DLL_NAMES),
                "dll_names": sorted(flattened),
                "attribution": NVIDIA_ATTRIBUTION_NOTICE,
            },
        )
    return {
        "component": result.component,
        "file_count": result.file_count,
        "output": str(result.path),
        "pack_bytes": result.path.stat().st_size,
        "pack_sha256": result.sha256,
        "payload_bytes": result.total_bytes,
        "payload_tree_sha256": result.payload_tree_sha256,
        "product_version": result.product_version,
        "signing_key_id": result.signing_key_id,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--acquire",
        action="store_true",
        help=(
            "download + verify the two pinned NVIDIA wheels from PyPI into --cache "
            "before building (mutually exclusive with --cublas-wheel/--cudnn-wheel)"
        ),
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "civiccast-native-cuda-pack-cache",
        help="scratch directory OUTSIDE the repo for --acquire's downloads",
    )
    parser.add_argument("--cublas-wheel", type=Path)
    parser.add_argument("--cudnn-wheel", type=Path)
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--product-version", default=__version__)
    parser.add_argument("--compatible-core", default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--allow-development-key",
        action="store_true",
        help="explicitly allow a development-only trust root for non-release proof",
    )
    args = parser.parse_args()

    try:
        require_allowed_signing_key(
            args.signing_key_id, allow_development_key=args.allow_development_key
        )
        key = load_ed25519_private_key(args.signing_private_key)

        if args.acquire:
            if args.cublas_wheel or args.cudnn_wheel:
                raise CudaPackBuildError(
                    "--acquire is mutually exclusive with --cublas-wheel/--cudnn-wheel"
                )
            print("build_native_cuda_pack: resolving and downloading pinned wheels from PyPI...")
            resolved = acquire_cuda_pack_sources(args.cache)
            cublas_wheel, cudnn_wheel = resolved["cublas"], resolved["cudnn"]
        elif args.cublas_wheel is None or args.cudnn_wheel is None:
            raise CudaPackBuildError(
                "missing required flags (or pass --acquire): --cublas-wheel and --cudnn-wheel"
            )
        else:
            cublas_wheel, cudnn_wheel = args.cublas_wheel, args.cudnn_wheel

        report = build_cuda_pack(
            output=args.output.resolve(),
            cublas_wheel=cublas_wheel,
            cudnn_wheel=cudnn_wheel,
            signing_private_key=key,
            signing_key_id=args.signing_key_id,
            product_version=args.product_version,
            compatible_core=args.compatible_core,
        )
    except CudaPackBuildError as exc:
        print(f"build_native_cuda_pack: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"cuda pack report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

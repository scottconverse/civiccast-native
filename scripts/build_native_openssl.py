#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the supported OpenSSL 3.5 LTS ABI used by PostgreSQL and GStreamer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from scripts.build_native_pyav_wheel import find_vcvarsall, load_pinned_msvc_environment

SOURCE = {
    "version": "3.5.9",
    "url": "https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz",
    "bytes": 53279637,
    "sha256": "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a",
}
PERL = {
    "version": "5.42.3.1",
    "url": "https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54231_64bit/strawberry-perl-5.42.3.1-64bit-portable.zip",
    "bytes": 304765269,
    "sha256": "6a081a811781c30aca51dbc036afd93092af91e3297901f02c17043795a10690",
}


def fetch(item: dict, path: Path) -> Path:
    if not path.exists():
        urllib.request.urlretrieve(item["url"], path)
    if (
        path.stat().st_size != item["bytes"]
        or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
    ):
        raise ValueError(f"unverified OpenSSL build input: {path}")
    return path


def build(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    source_archive = fetch(SOURCE, root / "openssl.tar.gz")
    perl_archive = fetch(PERL, root / "perl.zip")
    source = root / "openssl-3.5.9"
    if not source.exists():
        with tarfile.open(source_archive) as archive:
            archive.extractall(root, filter="data")
    perl = root / "perl/perl/bin/perl.exe"
    if not perl.exists():
        with zipfile.ZipFile(perl_archive) as archive:
            archive.extractall(root / "perl")
    env = load_pinned_msvc_environment(find_vcvarsall())
    path_key = next(key for key in env if key.lower() == "path")
    env[path_key] = str(perl.parent) + os.pathsep + env[path_key]
    # Upstream C fallbacks avoid a new assembler toolchain. NMake runs serially.
    configure = [
        str(perl),
        "Configure",
        "VC-WIN64A",
        "shared",
        "no-asm",
        "no-tests",
        "no-module",
        "no-legacy",
        "/Brepro",
        "/MT",
    ]
    nmake = shutil.which("nmake.exe", path=env[path_key])
    if not nmake:
        raise RuntimeError("pinned MSVC installation has no NMake")
    # A configuration/runtime change must never reuse objects compiled with /MD.
    marker = root / "configuration.json"
    configuration = json.dumps(configure[1:])
    changed = not marker.exists() or marker.read_text() != configuration
    if changed or not (source / "makefile").exists():
        subprocess.run(configure, cwd=source, env=env, check=True)
    if (marker.exists() and marker.read_text() != configuration) or (
        not marker.exists() and list(source.rglob("*.obj"))
    ):
        subprocess.run([nmake, "/NOLOGO", "clean"], cwd=source, env=env, check=True)
    marker.write_text(configuration)
    subprocess.run(
        [nmake, "/NOLOGO", "libcrypto-3-x64.dll", "libssl-3-x64.dll"],
        cwd=source,
        env=env,
        check=True,
    )
    out = root / "runtime"
    out.mkdir(exist_ok=True)
    for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll", "LICENSE.txt"):
        shutil.copyfile(source / name, out / name)
    return package_runtime(root, configure[1:])


def package_runtime(root: Path, configure: list[str] | None = None) -> Path:
    from scripts.native_openssl_overlay import assert_runtime_closure

    out = root / "runtime"
    if configure is None:
        configure = json.loads((root / "configuration.json").read_text())
    shutil.copyfile(
        Path(__file__).resolve().parents[1]
        / "civiccast/native/license_texts/LicenseRef-Microsoft-VCRedist.txt",
        out / "LicenseRef-Microsoft-VCRedist.txt",
    )
    provenance = {
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source": SOURCE,
        "build_only_perl": PERL,
        "configure": configure,
        "compiler": "MSVC 19.50.35730",
        "linker": "14.50.35730.0",
        "pe_imports": assert_runtime_closure(out),
        "files": {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in sorted(out.iterdir())
            if p.name != "provenance.json"
        },
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    archive_path = root / "openssl-3.5.9-civiccast-windows-x64.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.iterdir()):
            info = zipfile.ZipInfo(path.name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--package-existing",
        action="store_true",
        help="Restage provenance/licenses without recompiling verified runtime bytes",
    )
    args = parser.parse_args()
    print(
        package_runtime(args.work.resolve())
        if args.package_existing
        else build(args.work.resolve())
    )

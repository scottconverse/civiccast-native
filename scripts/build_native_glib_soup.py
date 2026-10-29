#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the GLib/libsoup/nghttp2 DLL subset against the reviewed GStreamer SDK."""

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

SOURCES = [
    {
        "name": "glib",
        "version": "2.88.4",
        "license": "LGPL-2.1-or-later",
        "url": "https://download.gnome.org/sources/glib/2.88/glib-2.88.4.tar.xz",
        "bytes": 5797568,
        "sha256": "25fd169f3b2f91fe2391ad297883ce0fcf30c69fc789ffd1c9672d1332b1c5a8",
    },
    {
        "name": "libsoup",
        "version": "3.8.1",
        "license": "LGPL-2.0-or-later",
        "url": "https://download.gnome.org/sources/libsoup/3.8/libsoup-3.8.1.tar.xz",
        "bytes": 1621608,
        "sha256": "5013dcef9136f6f861e6529fca578af50c1f52a39219027fb5aff652d1371a04",
    },
    {
        "name": "nghttp2",
        "version": "1.70.0",
        "license": "MIT",
        "url": "https://github.com/nghttp2/nghttp2/releases/download/v1.70.0/nghttp2-1.70.0.tar.xz",
        "bytes": 2018996,
        "sha256": "e05cb1388eaca3830aded4ccf20044b6e1ac1a61411dcca11b0437c4285c8bc2",
    },
]
SDK_SHA256 = "e4c41ee6ee9c6c32a45d198463ec08d79bac3bd5fa58adc93d13fe4a08abc9d9"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


BUILDER_SHA256 = sha(Path(__file__))


def build(work: Path, sdk: Path, pkgconfig: Path, tools: Path, sdk_archive: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    if not sdk_archive.is_file() or sha(sdk_archive) != SDK_SHA256:
        raise ValueError(f"unverified GStreamer SDK installer: {sdk_archive}")
    env = load_pinned_msvc_environment(find_vcvarsall())
    path_key = next(key for key in env if key.lower() == "path")
    env[path_key] = os.pathsep.join([str(tools), str(sdk / "bin"), env[path_key]])
    # Each build owns its pkg-config view; never rewrite the shared SDK.
    pc = work / "sdk-pkgconfig"
    pc.mkdir(exist_ok=True)
    for source in pkgconfig.glob("*.pc"):
        text = source.read_text(encoding="utf-8").replace(
            "prefix=${pcfiledir}/../..", f"prefix={sdk.as_posix()}"
        )
        (pc / source.name).write_text(text, encoding="utf-8")
    prefix = work / "install"
    env["PKG_CONFIG_PATH"] = os.pathsep.join([str(prefix / "lib/pkgconfig"), str(pc)])
    env["PKG_CONFIG_LIBDIR"] = str(pc)
    env["CFLAGS"] = f'/I"{sdk / "include"}"'
    env["CXXFLAGS"] = env["CFLAGS"]
    env["INCLUDE"] = str(sdk / "include") + os.pathsep + env.get("INCLUDE", "")
    env["LIB"] = str(sdk / "lib") + os.pathsep + env.get("LIB", "")
    env["LDFLAGS"] = f'/LIBPATH:"{sdk / "lib"}"'
    commands = []
    log = work / "build.log"

    def run(command: list[str]) -> None:
        commands.append(command)
        with log.open("a", encoding="utf-8") as output:
            output.write("\n" + subprocess.list2cmdline(command) + "\n")
            output.flush()
            subprocess.run(
                command,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    for item in SOURCES:
        archive = work / f"{item['name']}-{item['version']}.tar.xz"
        if not archive.exists():
            urllib.request.urlretrieve(item["url"], archive)
        if archive.stat().st_size != item["bytes"] or sha(archive) != item["sha256"]:
            raise ValueError(f"unverified source archive: {archive}")
        source = work / f"{item['name']}-{item['version']}"
        if not source.exists():
            with tarfile.open(archive) as bundle:
                bundle.extractall(work, filter="data")
        # Reusing a configured build never authorizes edited upstream sources.
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if member.isfile():
                    current = work / member.name
                    with bundle.extractfile(member) as original:
                        expected = hashlib.file_digest(original, "sha256").hexdigest()
                    if not current.is_file() or sha(current) != expected:
                        raise ValueError(f"source tree differs from verified archive: {current}")

    meson = str(tools / "meson.exe")
    for name, version, options in [
        (
            "glib",
            "2.88.4",
            [
                "-Dtests=false",
                "-Dinstalled_tests=false",
                "-Dintrospection=disabled",
                "-Dman-pages=disabled",
                "-Ddocumentation=false",
                "-Dnls=disabled",
                "-Dlibmount=disabled",
                "-Dselinux=disabled",
                "-Dlibelf=disabled",
                "-Dsysprof=disabled",
            ],
        ),
    ]:
        directory = work / f"build-{name}"
        if not (directory / "build.ninja").exists():
            run(
                [
                    meson,
                    "setup",
                    str(directory),
                    str(work / f"{name}-{version}"),
                    f"--prefix={prefix}",
                    "--libdir=lib",
                    "--buildtype=release",
                    "--wrap-mode=nofallback",
                    *options,
                ]
            )
        run([meson, "compile", "-C", str(directory), "-j", "2"])
        run([meson, "install", "-C", str(directory), "--no-rebuild"])

    cmake = shutil.which("cmake")
    if not cmake:
        raise RuntimeError("CMake is required for the upstream nghttp2 library-only build")
    directory = work / "build-nghttp2"
    run(
        [
            cmake,
            "-S",
            str(work / "nghttp2-1.70.0"),
            "-B",
            str(directory),
            "-G",
            "Ninja",
            f"-DCMAKE_INSTALL_PREFIX={prefix}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DENABLE_LIB_ONLY=ON",
            "-DENABLE_DOC=OFF",
            "-DBUILD_STATIC_LIBS=OFF",
            "-DBUILD_SHARED_LIBS=ON",
            "-DBUILD_TESTING=OFF",
        ]
    )
    run([cmake, "--build", str(directory), "--parallel", "2"])
    run([cmake, "--install", str(directory)])

    directory = work / "build-libsoup"
    if not (directory / "build.ninja").exists():
        run(
            [
                meson,
                "setup",
                str(directory),
                str(work / "libsoup-3.8.1"),
                f"--prefix={prefix}",
                "--libdir=lib",
                "--buildtype=release",
                "--wrap-mode=nofallback",
                "-Dtests=false",
                "-Dintrospection=disabled",
                "-Dvapi=disabled",
                "-Ddocs=disabled",
                "-Dsysprof=disabled",
                "-Dgssapi=disabled",
                "-Dntlm=disabled",
                "-Dbrotli=disabled",
                "-Dzstd=disabled",
                "-Dtls_check=false",
                "-Dpkcs11_tests=disabled",
            ]
        )
    run([meson, "compile", "-C", str(directory), "-j", "2"])
    run([meson, "install", "-C", str(directory), "--no-rebuild"])
    receipt = {
        "sources": SOURCES,
        "sdk_sha256": SDK_SHA256,
        "builder_sha256": BUILDER_SHA256,
        "commands": commands,
        "meson_options": {
            name: json.loads(
                (work / f"build-{name}" / "meson-info/intro-buildoptions.json").read_text()
            )
            for name in ("glib", "libsoup")
        },
        "nghttp2_cmake_cache_sha256": sha(work / "build-nghttp2/CMakeCache.txt"),
        "pkgconfig_inputs": {p.name: sha(p) for p in sorted(pkgconfig.glob("*.pc"))},
        "tools": {
            name: {"path": str(path), "sha256": sha(path)}
            for name, path in {
                "meson": tools / "meson.exe",
                "ninja": tools / "ninja.exe",
                "pkgconf": tools / "pkg-config.exe",
                "cl": Path(shutil.which("cl.exe", path=env[path_key])),
                "link": Path(shutil.which("link.exe", path=env[path_key])),
            }.items()
        },
        "sdk_inputs": {
            str(p.relative_to(sdk)): sha(p)
            for p in sorted(sdk.rglob("*"))
            if p.is_file() and (p.suffix in {".h", ".lib", ".pc"})
        },
        "files": {
            str(p.relative_to(prefix)): {"bytes": p.stat().st_size, "sha256": sha(p)}
            for p in sorted(prefix.rglob("*.dll"))
        },
    }
    (work / "build-provenance.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    runtime = work / "runtime"
    runtime.mkdir(exist_ok=True)
    names = {
        "glib": [
            "glib-2.0-0.dll",
            "gobject-2.0-0.dll",
            "gmodule-2.0-0.dll",
            "gio-2.0-0.dll",
            "gthread-2.0-0.dll",
        ],
        "libsoup": ["soup-3.0-0.dll"],
        "nghttp2": ["nghttp2.dll"],
    }
    files = {}
    for component in SOURCES:
        name = component["name"]
        paths = {filename: prefix / "bin" / filename for filename in names[name]}
        paths[f"{name}-COPYING.txt"] = work / f"{name}-{component['version']}" / "COPYING"
        for filename, source in paths.items():
            target = runtime / filename
            shutil.copyfile(source, target)
            files[filename] = {
                "bytes": target.stat().st_size,
                "sha256": sha(target),
                "component": name,
                "version": component["version"],
                "license": component["license"],
            }
    shutil.copyfile(work / "build-provenance.json", runtime / "provenance.json")
    files["provenance.json"] = {
        "bytes": (runtime / "provenance.json").stat().st_size,
        "sha256": sha(runtime / "provenance.json"),
        "component": "glib-libsoup-nghttp2-build",
        "version": "1",
        "license": "Apache-2.0",
    }
    archive = work / "glib-2.88.4-libsoup-3.8.1-nghttp2-1.70.0-civiccast-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for filename in sorted(files):
            info = zipfile.ZipInfo(filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, (runtime / filename).read_bytes())
    lock = {
        "schema_version": 1,
        "sources": SOURCES,
        "sdk_sha256": SDK_SHA256,
        "archive": {
            "filename": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": sha(archive),
        },
        "files": files,
    }
    (work / "overlay-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(lock["archive"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--sdk-archive", type=Path, required=True)
    parser.add_argument("--pkgconfig", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    args = parser.parse_args()
    build(
        args.work.resolve(),
        args.sdk.resolve(),
        args.pkgconfig.resolve(),
        args.tools.resolve(),
        args.sdk_archive.resolve(),
    )


if __name__ == "__main__":
    main()

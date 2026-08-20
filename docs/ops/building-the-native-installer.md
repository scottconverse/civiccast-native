# Building the native Windows installer

How to build `CivicCast (Native)_<version>_x64-setup.exe` on a Windows
workstation, and what currently stops that build from finishing.

Nothing in this repository documented this before. Every step below was
recovered by reading `.github/workflows/native-beta-candidate-artifacts.yml`
and running it, so it is a record of what actually happens rather than what
was intended.

**Status: the build does not complete.** Stages 1–3 pass; stage 4 fails on a
reproducibility pin. See "Where it stops" at the end — that section is the
point of this document, not an aside.

---

## What builds what

| Script | Produces |
| --- | --- |
| `scripts/provision_native_build_toolchain.py` | the reviewed node / npm / python / uv, and the reviewed MSVC Build Tools |
| `scripts/build_native_runtime_closure.py` | the GStreamer runtime tree (221 files) |
| `scripts/build_native_pyav_wheel.py` | the LGPL-only PyAV wheel, compiled from source |
| `scripts/build_native_app_payload.py` | the application payload tree |
| `scripts/build_native_installer.py` | the **unsigned** installer `.exe`, orchestrating all of the above |

Signing is separate and needs the owner's credentials — see "Signing".

## Prerequisites

* 64-bit Windows.
* Git, and a checkout with a **clean working tree**. `build_native_app_payload`
  refuses a dirty source: release payloads require a reproducible checkout.
  (`--allow-dirty-source` exists for explicitly non-release proof builds.)
* About 3 GB of free disk for the toolchain, plus ~1 GB of build trees.
* Nothing else. The reviewed toolchain is downloaded and hash-verified; it does
  not use, and does not modify, any Visual Studio already on the machine.

## 1. Provision the reviewed toolchain

```powershell
python -I -B scripts/provision_native_build_toolchain.py `
  --cache  "$env:TEMP\civiccast-toolchain-cache" `
  --output build\wp1-native-toolchain `
  --msvc-install "C:\ccmsvc"
```

Every byte is pinned by SHA-256 in `native-windows-build-toolchain.lock.json`.
On success it prints the verified identities: node `v24.15.0`, npm `11.12.1`,
python `3.12.13`, uv `0.11.15`, and MSVC compiler `19.50.35730`.

Two things that will waste your time otherwise:

* **`--output` must be empty or absent.** It refuses a non-empty directory.
* **`--msvc-install` must be a NEW directory, not an existing Visual Studio.**
  Point it at your installed VS and the script verifies *that* compiler and
  rejects it — e.g. `MSVC compiler is not reviewed 19.50.35730: ... Version
  19.44.35228`. Given a fresh path it downloads the pinned
  `vs_BuildTools-18.5.2.exe` and installs a self-contained copy there.
  Keep the path short: Microsoft's installer rejects a full path of 80
  characters or more, *after* downloading the product.

## 2. Cache the pinned payload interpreter

The payload embeds CPython 3.12.10 (the **embeddable** package, which is not
the same binary as a normal 3.12.10 install):

```powershell
Invoke-WebRequest `
  -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" `
  -OutFile "build\native-app-cache\python-3.12.10-embed-amd64.zip"
```

Reviewed identity: 11,133,606 bytes, SHA-256
`4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`.

## 3. Build

Order matters, and getting it wrong fails late and confusingly.

```powershell
$toolchain = (Resolve-Path "build\wp1-native-toolchain").Path
$env:UV_PYTHON            = "$toolchain\python\python.exe"
$env:UV_PYTHON_DOWNLOADS  = "never"
$env:UV_PROJECT_ENVIRONMENT = "C:\ccbuildvenv"
& "$toolchain\uv\uv.exe" sync --frozen --all-groups `
    --python "$toolchain\python\python.exe" --project .

# MSVC FIRST: importing vcvars re-exports the whole cmd environment, PATH
# included, so a PATH prefix set before this is silently wiped.
cmd /c '"C:\ccmsvc\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 && set' |
  ForEach-Object { if ($_ -match "^([^=]+)=(.*)$") {
      Set-Item ("Env:" + $matches[1]) $matches[2] -ErrorAction SilentlyContinue } }

# Toolchain prefix SECOND.
$env:PATH = "C:\ccbuildvenv\Scripts;$toolchain\node;$toolchain\uv;$env:PATH"

& "C:\ccbuildvenv\Scripts\python.exe" scripts\build_native_installer.py
```

The build venv is seeded *from* the reviewed interpreter, so
`sys._base_executable` resolves to the reviewed build while the venv still
carries the project's dependencies. Neither a bare PATH-prepend of the
provisioned python nor an unreviewed system python satisfies both at once.

Why the ordering rule is spelled out: prepending the toolchain before
importing vcvars leaves the ambient `uv` on PATH, and the build then dies four
stages later with `uv executable SHA-256 68a22cba... != pinned d4ffe0b7...`,
which does not obviously mean "your PATH got clobbered".

### Useful flags

* `--stage-only` — stop after staging and verifying both payloads; skip Tauri.
* `--skip-closure-build` — reuse an existing tree at `--tree-out`.
* `--skip-app-build` — reuse an existing payload at `--app-tree-out`.

## Where it stops

Measured on a clean Windows 11 workstation, 2026-08-20, with everything above
verified as matching the reviewed identities:

| Stage | Result |
| --- | --- |
| Runtime closure | **PASS** — 106 PE files, 221 files, 75,319,816 bytes; `manifest_verification: PASS` byte-for-byte |
| Toolchain provisioning | **PASS** — every hash matched, MSVC `19.50.35730` |
| PyAV compile | **PASS** — compiled, linked, and repaired into a wheel |
| PyAV reproducibility pin | **FAIL** — `av-18.0.0-cp311-abi3-win_amd64.whl byte length 4346817 != pinned 4346940` |

`build_native_pyav_wheel.py` requires the wheel it just compiled to be
**byte-identical** to a pinned SHA-256. This machine's is 123 bytes different.

Everything the build controls was eliminated as the cause:

* compiler `19.50.35730` and linker `14.50.35730.0` — pinned and matching
* Windows SDK `10.0.26100.0` — the only SDK present, and the one
  `Windows11SDK.26100` names
* `/Brepro` on both compiler and linker, `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED=0`
* `delvewheel==1.13.0`, hash-pinned
* the PyAV source archive and the FFmpeg binaries, both hash-pinned
* the repacked provenance notice, which is entirely constants

So the reviewed wheel hash **is not reproducible from the reviewed toolchain
specification alone**. Something outside that specification contributed to the
recorded hash. Until that input is identified and pinned, this build cannot be
completed by following its own recipe on a clean machine — and the same pin
will fail in CI whenever the `windows-latest` image drifts.

This has not been observed in CI, because the native candidate workflow has
never completed a run in this repository.

## Signing

`build_native_installer.py` produces an **unsigned** `.exe`. Signing happens in
`native-beta-candidate-artifacts.yml` via Azure Artifact Signing and needs
repository credentials that are not set here:

| Kind | Name |
| --- | --- |
| Variable | `CIVICCAST_PACK_PUBLIC_KEY_BASE64` |
| Variable | `CIVICCAST_PACK_SIGNING_KEY_ID` |
| Secret | `CIVICCAST_PACK_SIGNING_PRIVATE_KEY` |
| Secret | `AZURE_CLIENT_ID` |
| Secret | `AZURE_TENANT_ID` |
| Secret | `AZURE_CLIENT_SECRET` |

The pack build fails closed without them:
`throw "Pack signing private-key secret is missing."`

## Cleaning up

```powershell
Remove-Item -Recurse -Force C:\ccmsvc, C:\ccbuildvenv, build\wp1-native-toolchain,
  build\native-runtime-tree, build\native-app-tree, build\native-pyav-cache,
  build\native-app-cache, "$env:TEMP\civiccast-toolchain-cache"
```

Nothing above is placed on the system PATH or registered with Windows.

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Stage the built, signed ``native-server-binaries`` pack into the native
installer's own tree so a future exe rebuild can carry it -- the same
git-ignored-staging-directory pattern ``scripts/build_native_installer.py``
already uses for the media runtime closure (``native-runtime/``) and the
application payload (``runtime/``): build the verified artifact into its OWN
directory outside the checked-out tree, clean-copy/extract the VERIFIED
result into ``src-tauri/``, then re-verify the STAGED copy (D2 posture --
"verify before laying files; corrupt => loud failure", applied here to the
copy about to be embedded, not just the one just built).

Stages BOTH forms, matching the two ways the pack is consumed:

* the raw signed ``.ccpack`` file at ``src-tauri/packs/
  native-server-binaries.ccpack`` -- the exact path
  ``civiccast.native.provision.__main__.resolve_provision_paths``'s
  ``default_server_pack_path`` expects at
  ``<install_root>\\packs\\native-server-binaries.ccpack``;
* its EXTRACTED payload at ``src-tauri/packs/native-server-binaries/`` (the
  ``payload/`` prefix from the ZIP preserved) -- the exact tree
  ``default_initdb_path`` expects at ``<install_root>\\packs\\
  native-server-binaries\\payload\\bin\\initdb.exe``.

**Genuine, disclosed architecture tension (not resolved here):** the
CURRENTLY ACTIVE native Tauri config (``tauri.native.conf.json``) targets the
owner-approved sub-300 MB bootstrap architecture
(``.agent-runs/native-windows/specs/plan-sub-300mb-bootstrap.md``): its
``bundle.resources`` is asserted by ``scripts/build_native_bootstrap.py``'s
``validate_native_bootstrap_config`` to contain ONLY the pinned VC++
redistributable -- station bytes belong in signed, separately-distributed
packs, never embedded in the bootstrap executable. Wiring this staging
directory into THAT config's ``bundle.resources`` would therefore violate the
owner-approved size gate. ``nsis-hooks-native.nsh`` (the D4 provisioning
wiring this task closes the gap for) is REAL, tested code, but as of this
writing its own Tauri config (the one WP-6 embedded the full application
payload under) is not the config any current build target references --
``tauri.native.conf.json`` points at ``nsis-hooks-bootstrap.nsh`` instead.
Reconciling which installer architecture embeds this pack (embedded resource
vs. a channel-index-referenced sidecar download, same as the Core/Captions/
Summary/Translation packs ``scripts/build_native_distribution.py`` already
produces) is a bigger decision than this task's scope -- this script makes
the verified bytes available at the ALREADY-established path convention
(``resolve_provision_paths``) so whichever architecture wins next can pick
them up without re-deriving the pinned inventory again. See the evidence
file for the full disclosure.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.installer.native_packs import verify_native_pack  # noqa: E402
from civiccast.native.provision.pack import verify_server_binaries_pack  # noqa: E402

INSTALLER_DIR: Final[Path] = ROOT / "civiccast" / "apps" / "installer"
SRC_TAURI: Final[Path] = INSTALLER_DIR / "src-tauri"

#: Git-ignored staging locations -- see the accompanying `.gitignore` entry.
#: Named after the pack's own component identity
#: (`civiccast.native.provision.pack.SERVER_BINARIES_COMPONENT`), a sibling
#: convention to `native-runtime/`/`runtime/`, not a reuse of the pre-existing
#: (never wired up) `runtime-dependencies/` entry, which names a broader,
#: differently-scoped tree (this pack's own docstring explains why it is
#: NOT that tree: PostgreSQL/TSDuck only, minimized, not the general
#: closure).
STAGED_PACK_FILE: Final[Path] = SRC_TAURI / "packs" / "native-server-binaries.ccpack"
STAGED_PACK_EXTRACTED: Final[Path] = SRC_TAURI / "packs" / "native-server-binaries"


class StageServerPackError(RuntimeError):
    """The verified server pack could not be staged for the installer build."""


def stage_server_pack(
    built_pack: Path,
    *,
    public_key: Ed25519PublicKey,
    expected_product_version: str,
    expected_compatible_core: str,
    expected_signing_key_id: str,
) -> dict[str, object]:
    """Verify ``built_pack`` through the REAL provisioning trust wire, then
    stage both the raw file and its extracted payload -- re-verifying the
    staged copy afterward (D2: never trust a copy just because the source
    was good)."""

    built_pack = built_pack.expanduser().resolve(strict=True)
    verify_server_binaries_pack(
        built_pack,
        public_key=public_key,
        expected_product_version=expected_product_version,
        expected_compatible_core=expected_compatible_core,
        expected_signing_key_id=expected_signing_key_id,
    )

    STAGED_PACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STAGED_PACK_FILE.exists():
        STAGED_PACK_FILE.unlink()
    shutil.copyfile(built_pack, STAGED_PACK_FILE)

    if STAGED_PACK_EXTRACTED.exists():
        shutil.rmtree(STAGED_PACK_EXTRACTED)
    with zipfile.ZipFile(STAGED_PACK_FILE) as archive:
        archive.extractall(STAGED_PACK_EXTRACTED)

    # Re-verify the STAGED copy (not the original) -- proves the bytes that
    # just landed in the installer tree are the same bytes that were built,
    # not a corrupted or partial copy.
    result = verify_native_pack(
        STAGED_PACK_FILE,
        public_key=public_key,
        expected_component="native-server-binaries",
        expected_product_version=expected_product_version,
        expected_compatible_core=expected_compatible_core,
        expected_signing_key_id=expected_signing_key_id,
    )

    initdb_on_disk = STAGED_PACK_EXTRACTED / "payload" / "bin" / "initdb.exe"
    if not initdb_on_disk.is_file():
        raise StageServerPackError(
            f"staged pack extraction is missing the expected initdb.exe at {initdb_on_disk} "
            "-- civiccast.native.provision.__main__.resolve_provision_paths' default_initdb_path "
            "contract would not resolve against this staged tree"
        )

    return {
        "staged_pack": str(STAGED_PACK_FILE),
        "staged_extracted_root": str(STAGED_PACK_EXTRACTED),
        "initdb_path": str(initdb_on_disk),
        "component": result.component,
        "file_count": result.file_count,
        "pack_sha256": result.sha256,
        "pack_bytes": STAGED_PACK_FILE.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack", required=True, type=Path, help="the built native-server-binaries.ccpack"
    )
    parser.add_argument("--public-key-base64", required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--compatible-core", required=True)
    parser.add_argument("--signing-key-id", required=True)
    args = parser.parse_args()

    import base64
    import json

    raw = base64.b64decode(args.public_key_base64, validate=True)
    if len(raw) != 32:
        raise StageServerPackError("pack public key must decode to exactly 32 Ed25519 bytes")
    public_key = Ed25519PublicKey.from_public_bytes(raw)

    report = stage_server_pack(
        args.pack,
        public_key=public_key,
        expected_product_version=args.product_version,
        expected_compatible_core=args.compatible_core,
        expected_signing_key_id=args.signing_key_id,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

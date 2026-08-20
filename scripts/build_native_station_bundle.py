#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
r"""Build the signed native STATION BUNDLE that the K1 flat-activation fix
consumes: ``station-index.json`` plus every component pack it names, laid
out flat in one output directory so it can be side-loaded next to the
installer at ``$EXEDIR\station\`` (the exact path
``nsis-hooks-bootstrap.nsh`` wires ``--civiccast-activate-station
--civiccast-import-station`` to, between ``--civiccast-provision`` and
``--civiccast-register-native-service``).

## The gap this closes

``main.rs::run_native_flat_activation_cli`` (K1) can activate a flat station
GIVEN a real ``AcquiredDistribution`` -- but nothing in this repository ever
produced a signed station bundle in the shape it, and
``native_distribution::acquire_station_distribution``, actually require.
This script is that builder.

## The contract, derived from the consumer -- not invented here

Read straight from ``native_distribution.rs`` (``verify_distribution_bytes``,
``component_sort_key``, ``validate_urls``, ``safe_pack_filename``,
``canonical_json``) and ``native_activation.rs``
(``REQUIRED_COMPONENTS``/``OPTIONAL_COMPONENTS``/``staged_component_root``),
never from the STALE five-pack builder (``scripts/build_native_distribution.py``,
``civiccast.installer.native_distribution.REQUIRED_COMPONENTS``) -- that
module still pins ``captions-large-v3`` as the mandatory caption pack and
carries no ``captions-floor`` component at all, predating the owner's
2026-08-07 ratified floor-tier-mandatory / large-v3-optional swap that
``native_distribution.rs``/``native_activation.rs`` already made. Reusing it
here would build a bundle the CURRENT Rust verifier rejects outright
(``"Native distribution required component set is incomplete: captions-floor"``).
Reconciling that stale module is real, separate work this script
deliberately does not attempt -- see this slice's report.

What IS safely reused, because it has zero coupling to that stale constant:
``civiccast.installer.native_packs.build_native_pack`` (the generic signed
``.ccpack`` builder -- manifest.json + manifest.sig + payload/*, ed25519 over
canonical JSON, byte-identical to what ``native_packs.rs::open_and_verify_pack``
expects) and ``civiccast.installer.native_distribution.canonical_json`` (the
pure JSON-canonicalization function the signature covers, proven
byte-for-byte compatible with the Rust side by the existing five-pack tests).

## The component set

``core``, ``captions-floor``, ``summary-gemma4-12b``, ``summary-gemma4-e4b``,
``translation-translategemma-4b`` are REQUIRED (``native_distribution.rs::
REQUIRED_COMPONENTS``); ``captions-large-v3`` is OPTIONAL
(``native_activation.rs::OPTIONAL_COMPONENTS``) -- present when
``--captions-large-v3-root`` is given, simply absent when it is not, exactly
mirroring the Rust-side "optional means may be absent, never may be
untrusted" posture (a present-but-empty root still fails loud, never
silently skipped).

``core``'s payload is a synthetic placeholder, NEVER real runtime bytes --
see :func:`_core_placeholder_sources`'s doc for why: the flat-activation
consumer (``native_activation::activate_flat_station_with``) deliberately
never extracts ``core`` onto ``$INSTDIR``, because the real runtime bytes
already live there, staged and D2-verified by the elevated installer's OWN
``--civiccast-stage-packs`` step. Shipping real runtime bytes in ``core``
here would be dead weight at best and a silent-overwrite hazard at worst.

Every OTHER component's payload is EXACTLY the file tree found under its
``--<component>-root`` input, verbatim, relative-path-preserved -- this
script does not fabricate or download model weights (never in scope: the
task's own instruction). Each root must already be a real, complete
artifact -- e.g. ``--captions-floor-root`` pointing at a directory shaped
``models/faster-whisper-medium/{config.json,model.bin,tokenizer.json,
vocabulary.txt}`` plus ``self-test/jfk.wav`` (the exact relative layout
``native_activation.rs``'s ``FLOOR_STAGED_ROOT``/``validate_staged_runtime_layout``
pin, and the same layout the ollama-model roots must carry the standard
``blobs/`` + ``manifests/registry.ollama.ai/library/<repo>/<tag>`` shape
``compose_ollama_model_store`` expects). This script does not deep-validate
that internal shape (that is the self-test's job, at activation time, on a
real station); it fails loud only when an entire required root is missing,
empty, or not a real directory -- see :func:`_require_pack_root`.

## Reuse, not a fork

The index-signing shape (``build_distribution_index``,
``civiccast.installer.native_distribution``) is ALSO not reused: it shares
the same stale ``REQUIRED_COMPONENTS`` coupling (a hard membership check, a
per-pack ``required`` flag derived from it, and its own sort key). This
script's own :func:`_build_station_index` is a small, self-contained,
schema-faithful builder instead -- same envelope shape
(``{"manifest": ..., "signature": ...}``), same manifest fields, same
canonical-JSON signing, same station-index URL-emptiness rule
(``native_distribution.rs::validate_urls``: a station (air-gapped) index
carries NO network locations, ever), just parameterized on THIS script's own
(correct, current) component set rather than the stale one.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.installer.native_distribution import canonical_json  # noqa: E402
from civiccast.installer.native_packs import (  # noqa: E402
    OLLAMA_MODEL_COMPONENTS,
    build_native_pack,
)

_REPARSE_POINT: Final[int] = 0x400

#: The station bundle's required component set -- mirrored EXACTLY from
#: ``native_distribution.rs::REQUIRED_COMPONENTS`` (order matters: it is
#: also this script's canonical sort-key source, matching
#: ``native_distribution.rs::component_sort_key``).
REQUIRED_COMPONENTS: Final[tuple[str, ...]] = (
    "core",
    "captions-floor",
    "summary-gemma4-12b",
    "summary-gemma4-e4b",
    "translation-translategemma-4b",
)

#: Mirrored from ``native_activation.rs::OPTIONAL_COMPONENTS``.
OPTIONAL_COMPONENTS: Final[tuple[str, ...]] = ("captions-large-v3",)

#: The literal filename ``nsis-hooks-bootstrap.nsh`` invokes
#: ``--civiccast-import-station`` with (K1 wiring commit
#: e07cc50d9). Kept as a literal here, not derived, so a rename on either
#: side is a loud mismatch rather than a silent drift -- the policy test
#: this script's own test file adds cross-checks the two.
STATION_INDEX_FILENAME: Final[str] = "station-index.json"

#: The literal filename ``scripts/provision_native_ollama_models.py``'s
#: ``PROVENANCE_NAME`` writes into every Ollama model root it stages. Kept
#: as a literal here, not imported (that script is a sibling CLI, not a
#: package module) -- same "a rename on either side is a loud mismatch"
#: posture as ``STATION_INDEX_FILENAME`` above.
OLLAMA_MODEL_PROVENANCE_FILENAME: Final[str] = "MODEL-PROVENANCE.json"

DISTRIBUTION_SCHEMA_VERSION: Final[int] = 1
DISTRIBUTION_PRODUCT: Final[str] = "civiccast-native"


class StationBundleBuildError(RuntimeError):
    """The signed native station bundle could not be built."""


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    """Same contract as every sibling pack builder's guard
    (``scripts/build_native_cuda_pack.py``, ``scripts/build_native_ffmpeg_pack.py``,
    ...): a ``development-``-prefixed signing key id must never land in a
    release build by accident."""

    if key_id.startswith("development-") and not allow_development_key:
        raise StationBundleBuildError(
            "development pack signing keys require --allow-development-key; "
            "release packaging must use Scott-approved production key custody"
        )


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        raise StationBundleBuildError(f"pack signing private key is missing: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise StationBundleBuildError("pack signing private key must be Ed25519")
    return key


def _require_pack_root(path: Path | None, *, component: str, required: bool) -> Path | None:
    """The one structural check this script performs on a component's input
    root: it must be a real, non-symlink, non-empty directory. Never a
    deeper semantic check (exact file names, pinned model hashes) -- that is
    ``native_activation.rs``'s live self-test's job, against a real station,
    not this builder's. "Fail loud, name exactly what is missing" (task
    instruction) means failing on ABSENCE, not re-implementing runtime
    verification here."""

    if path is None:
        if required:
            raise StationBundleBuildError(f"missing required pack artifact root: {component}")
        return None
    resolved = path.expanduser().resolve()
    try:
        details = resolved.lstat()
    except OSError as exc:
        raise StationBundleBuildError(
            f"missing required pack artifact root: {component} (not found: {resolved})"
        ) from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISDIR(details.st_mode) or resolved.is_symlink() or attributes & _REPARSE_POINT:
        raise StationBundleBuildError(
            f"pack artifact root for {component} must be a real directory, not a link: {resolved}"
        )
    if not any(resolved.iterdir()):
        raise StationBundleBuildError(f"pack artifact root for {component} is empty: {resolved}")
    return resolved


def _collect_tree_sources(root: Path) -> dict[str, Path]:
    """Every regular file under ``root``, keyed by its POSIX-relative path --
    the pack's payload verbatim. Rejects symlinks/reparse points and
    case-insensitive path collisions (Windows extracts case-insensitively;
    two entries differing only in case would silently overwrite one
    another there even though this build machine may not be Windows)."""

    sources: dict[str, Path] = {}
    folded: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        details = candidate.lstat()
        attributes = int(getattr(details, "st_file_attributes", 0))
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            raise StationBundleBuildError(f"pack artifact root contains a link: {candidate}")
        if candidate.is_dir():
            continue
        if not stat.S_ISREG(details.st_mode):
            raise StationBundleBuildError(
                f"pack artifact root contains a non-regular file: {candidate}"
            )
        relative = PurePosixPath(candidate.relative_to(root).as_posix()).as_posix()
        if relative.casefold() in folded:
            raise StationBundleBuildError(
                f"pack artifact root contains a case-insensitive path collision: {relative}"
            )
        folded.add(relative.casefold())
        sources[relative] = candidate.resolve(strict=True)
    if not sources:
        raise StationBundleBuildError(f"pack artifact root has no files to pack: {root}")
    return sources


def _core_placeholder_sources(temp_root: Path, *, product_version: str) -> dict[str, Path]:
    """``core``'s entire payload: one small NOTICE explaining why it carries
    no real bytes. See this module's own doc for the full rationale --
    short version: the flat-activation consumer never extracts `core` onto
    `$INSTDIR` (the real runtime is already there, staged by the elevated
    installer's own separate pack-staging step), so shipping real runtime
    bytes here would be dead weight or a silent-overwrite hazard, and
    `build_native_pack` refuses an empty payload -- so this is the one
    payload file `core` needs to exist as a structurally valid, verifiable
    pack at all."""

    notice_path = temp_root / "core-notice.txt"
    notice_path.write_text(
        "CivicCast (Native) station bundle -- core placeholder\n"
        "\n"
        f"product_version: {product_version}\n"
        "\n"
        "This pack intentionally carries NO real runtime bytes. In the flat-\n"
        "layout activation this station bundle is built for (K1 fix,\n"
        "native_activation.rs::activate_flat_station_with), the real runtime\n"
        "(interpreter, dependencies) is already staged and D2-verified at the\n"
        "install root by the elevated installer's OWN --civiccast-stage-packs\n"
        "step before station activation ever runs. `core` exists in this\n"
        "bundle's index only so the signed distribution's structural contract\n"
        "(native_activation.rs::validate_complete_distribution) is satisfied;\n"
        "its payload is never extracted onto the install root.\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"NOTICE.txt": notice_path}


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _ollama_model_pack_metadata(component: str, root: Path) -> dict[str, object]:
    """The extra manifest metadata an Ollama-model component pack needs to
    pass ``civiccast.installer.native_packs._validate_ollama_model_contract``
    (and its Rust mirror, ``native_packs.rs::validate_ollama_model_contract``):
    ``model_name`` (the reviewed lock's OWN dict key, e.g. ``"gemma4-12b"``),
    ``manifest_sha256``, and ``ollama_runtime_version``.

    Sourced from ``MODEL-PROVENANCE.json``, the file
    ``scripts/provision_native_ollama_models.py::stage_model`` writes at the
    top of every model root it stages -- itself derived from the SAME
    reviewed lock the verifier checks against
    (``provision_native_ollama_models.py``'s own ``stage_model``/
    ``verify_staged_model`` round-trip already proves those fields are
    correct for the bytes actually staged under ``root``). Reusing it here,
    rather than re-deriving ``model_name`` by re-parsing the lock a second
    time, keeps this script decoupled from the lock's internal schema while
    still resting on the one place that identity is already computed and
    verified.

    This is a safe source to trust for METADATA purposes specifically
    because it is not the last word: ``_validate_ollama_model_contract``
    independently re-verifies every blob and manifest byte the pack
    actually carries against whatever lock entry ``model_name`` names, so a
    wrong or stale provenance file fails CLOSED (a metadata/bytes mismatch)
    rather than smuggling unreviewed content through -- it can misdirect
    which lock entry a pack is checked against, never bypass that check.

    Fails loud (:class:`StationBundleBuildError`) if the provenance file is
    missing, unreadable, or internally inconsistent with the component this
    pack is being built for -- never silently proceeds with a guessed or
    partial metadata set."""

    path = root / OLLAMA_MODEL_PROVENANCE_FILENAME
    label = f"{component} model provenance ({OLLAMA_MODEL_PROVENANCE_FILENAME})"
    if not path.is_file():
        raise StationBundleBuildError(f"{label} is missing: {path}")
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StationBundleBuildError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(provenance, dict):
        raise StationBundleBuildError(f"{label} root must be an object")

    model_name = provenance.get("model_name")
    manifest_sha256 = provenance.get("manifest_sha256")
    ollama_runtime_version = provenance.get("ollama_runtime_version")
    provenance_component = provenance.get("component")
    if not isinstance(model_name, str) or not model_name:
        raise StationBundleBuildError(f"{label} is missing a valid model_name")
    if not _is_lower_sha256(manifest_sha256):
        raise StationBundleBuildError(f"{label} is missing a valid manifest_sha256")
    if not isinstance(ollama_runtime_version, str) or not ollama_runtime_version:
        raise StationBundleBuildError(f"{label} is missing a valid ollama_runtime_version")
    if provenance_component != component:
        raise StationBundleBuildError(
            f"{label} component {provenance_component!r} does not match the pack "
            f"being built: {component!r}"
        )

    return {
        "source_root": str(root),
        "model_name": model_name,
        "manifest_sha256": manifest_sha256,
        "ollama_runtime_version": ollama_runtime_version,
    }


def _station_component_sort_key(component: str) -> tuple[int, int, str]:
    """Mirrors ``native_distribution.rs::component_sort_key`` exactly:
    required components first, in their declared order; anything else
    (an optional component actually present) after, alphabetically."""

    try:
        return (0, REQUIRED_COMPONENTS.index(component), "")
    except ValueError:
        return (1, 0, component)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _build_station_index(
    *,
    output: Path,
    channel: str,
    product_version: str,
    compatible_core: str,
    signing_key_id: str,
    created_epoch: int,
    packs: dict[str, Path],
    signing_private_key: Ed25519PrivateKey,
) -> dict[str, object]:
    """Build and sign ``station-index.json`` -- schema-faithful to
    ``native_distribution.rs::DistributionManifest``/``DistributionEnvelope``,
    parameterized on THIS script's (current, correct) component set rather
    than the stale ``civiccast.installer.native_distribution.
    build_distribution_index``. See the module doc's "Reuse, not a fork"
    section."""

    entries: list[dict[str, object]] = []
    for component in sorted(packs, key=_station_component_sort_key):
        pack_path = packs[component]
        entries.append(
            {
                "component": component,
                "filename": pack_path.name,
                "bytes": pack_path.stat().st_size,
                "sha256": _sha256_file(pack_path),
                "required": component in REQUIRED_COMPONENTS,
                # A station (air-gapped) index carries NO network locations,
                # ever -- native_distribution.rs::validate_urls's
                # kind == "station-index" branch rejects a non-empty list
                # outright.
                "urls": [],
            }
        )
    manifest: dict[str, object] = {
        "schema_version": DISTRIBUTION_SCHEMA_VERSION,
        "product": DISTRIBUTION_PRODUCT,
        "kind": "station-index",
        "channel": channel,
        "product_version": product_version,
        "compatible_core": compatible_core,
        "signing_key_id": signing_key_id,
        "created_epoch": created_epoch,
        "packs": entries,
    }
    signature = signing_private_key.sign(canonical_json(manifest))
    envelope: dict[str, object] = {
        "manifest": manifest,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    payload = canonical_json(envelope)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise StationBundleBuildError(f"station index already exists: {output}")
    with tempfile.NamedTemporaryFile(
        mode="xb",
        prefix=f".{output.name}.",
        suffix=".partial",
        dir=output.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if output.exists():
            raise StationBundleBuildError(f"station index already exists: {output}")
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return manifest


def build_station_bundle(
    *,
    output_dir: Path,
    captions_floor_root: Path,
    gemma4_12b_root: Path,
    gemma4_e4b_root: Path,
    translategemma_4b_root: Path,
    captions_large_v3_root: Path | None,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    compatible_core: str | None,
    channel: str,
    created_epoch: int,
) -> dict[str, object]:
    """Assemble + sign one complete station bundle: ``station-index.json``
    plus every named component pack, all landing flat in ``output_dir``
    (the exact shape a real ``$EXEDIR\\station`` side-load directory needs).

    Fails loud, before writing anything, if any REQUIRED pack artifact root
    is missing/empty/not-a-real-directory (never a partial bundle on disk --
    see the temp-dir-then-replace promotion at the end)."""

    if not signing_key_id or signing_key_id.strip() != signing_key_id:
        raise StationBundleBuildError("pack signing key id is invalid")
    compatible_core = compatible_core or product_version

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise StationBundleBuildError(
            f"refusing non-empty station bundle output directory: {output_dir}"
        )

    # Every required root is checked BEFORE any file is written -- a station
    # bundle missing one required component is worthless (validate_complete_
    # distribution/verify_distribution_bytes will reject it outright), so
    # failing here, loud and up front, naming exactly what is missing, beats
    # a partially-built bundle a release engineer has to notice is broken.
    component_roots: dict[str, Path] = {
        "captions-floor": _require_pack_root(
            captions_floor_root, component="captions-floor", required=True
        ),
        "summary-gemma4-12b": _require_pack_root(
            gemma4_12b_root, component="summary-gemma4-12b", required=True
        ),
        "summary-gemma4-e4b": _require_pack_root(
            gemma4_e4b_root, component="summary-gemma4-e4b", required=True
        ),
        "translation-translategemma-4b": _require_pack_root(
            translategemma_4b_root, component="translation-translategemma-4b", required=True
        ),
    }
    optional_large_v3_root = _require_pack_root(
        captions_large_v3_root, component="captions-large-v3", required=False
    )
    if optional_large_v3_root is not None:
        component_roots["captions-large-v3"] = optional_large_v3_root

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    try:
        packs: dict[str, Path] = {}

        core_sources = _core_placeholder_sources(temporary, product_version=product_version)
        core_output = temporary / "core.ccpack"
        build_native_pack(
            output=core_output,
            component="core",
            product_version=product_version,
            compatible_core=compatible_core,
            sources=core_sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={"payload": "placeholder-only; see NOTICE.txt"},
        )
        packs["core"] = core_output

        for component, root in component_roots.items():
            sources = _collect_tree_sources(root)
            output = temporary / f"{component}.ccpack"
            # Ollama-model components (summary-gemma4-12b/-e4b,
            # translation-translategemma-4b) are checked by
            # native_packs._validate_ollama_model_contract, which requires
            # model_name/manifest_sha256/ollama_runtime_version metadata --
            # a bare {"source_root": ...} (fine for captions-floor, which has
            # no such contract branch) fails that gate immediately with
            # "missing model_name metadata". See _ollama_model_pack_metadata.
            metadata = (
                _ollama_model_pack_metadata(component, root)
                if component in OLLAMA_MODEL_COMPONENTS
                else {"source_root": str(root)}
            )
            build_native_pack(
                output=output,
                component=component,
                product_version=product_version,
                compatible_core=compatible_core,
                sources=sources,
                signing_private_key=signing_private_key,
                signing_key_id=signing_key_id,
                metadata=metadata,
            )
            packs[component] = output

        missing_required = [
            component for component in REQUIRED_COMPONENTS if component not in packs
        ]
        if missing_required:
            # Defensive: _require_pack_root above already made this
            # unreachable for a correctly-wired caller, but a station bundle
            # missing a required pack is exactly the failure mode this
            # script exists to prevent, so it is checked again here rather
            # than trusted.
            raise StationBundleBuildError(
                "built station bundle pack set is incomplete: " + ", ".join(missing_required)
            )

        index_path = temporary / STATION_INDEX_FILENAME
        manifest = _build_station_index(
            output=index_path,
            channel=channel,
            product_version=product_version,
            compatible_core=compatible_core,
            signing_key_id=signing_key_id,
            created_epoch=created_epoch,
            packs=packs,
            signing_private_key=signing_private_key,
        )

        report_packs: dict[str, dict[str, object]] = {
            component: {
                "filename": packs[component].name,
                "bytes": packs[component].stat().st_size,
                "sha256": _sha256_file(packs[component]),
                "required": component in REQUIRED_COMPONENTS,
            }
            for component in packs
        }
        report: dict[str, object] = {
            "schema_version": 1,
            "product": DISTRIBUTION_PRODUCT,
            "product_version": product_version,
            "compatible_core": compatible_core,
            "channel": channel,
            "signing_key_id": signing_key_id,
            "created_epoch": created_epoch,
            "packs": report_packs,
            "total_pack_bytes": sum(int(item["bytes"]) for item in report_packs.values()),
            "station_index": index_path.name,
        }
        (temporary / "native-station-bundle-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        if output_dir.exists():
            output_dir.rmdir()
        temporary.replace(output_dir)
    except Exception:
        import shutil

        shutil.rmtree(temporary, ignore_errors=True)
        raise

    _ = manifest  # already verified by construction; kept for future use
    return {
        **report,
        "packs": {
            component: {
                **report_packs[component],
                "path": str(output_dir / report_packs[component]["filename"]),
            }
            for component in report_packs
        },
        "station_index": str(output_dir / index_path.name),
        "report": str(output_dir / "native-station-bundle-report.json"),
        "output_dir": str(output_dir),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help='the "station/" directory to build -- side-load this whole directory to '
        "$EXEDIR\\station next to the installer",
    )
    parser.add_argument("--captions-floor-root", required=True, type=Path)
    parser.add_argument("--gemma4-12b-root", required=True, type=Path)
    parser.add_argument("--gemma4-e4b-root", required=True, type=Path)
    parser.add_argument("--translategemma-4b-root", required=True, type=Path)
    parser.add_argument(
        "--captions-large-v3-root",
        type=Path,
        default=None,
        help="optional: the quality-tier caption pack. Absent means the built bundle "
        "carries no captions-large-v3 pack at all (a legitimate floor-only bundle).",
    )
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--compatible-core", default=None)
    parser.add_argument("--channel", default="beta")
    parser.add_argument("--created-epoch", type=int, default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--allow-development-key",
        action="store_true",
        help="explicitly allow a development-only trust root for non-release proof",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        require_allowed_signing_key(
            args.signing_key_id, allow_development_key=args.allow_development_key
        )
        key = load_ed25519_private_key(args.signing_private_key)
        result = build_station_bundle(
            output_dir=args.output_dir,
            captions_floor_root=args.captions_floor_root,
            gemma4_12b_root=args.gemma4_12b_root,
            gemma4_e4b_root=args.gemma4_e4b_root,
            translategemma_4b_root=args.translategemma_4b_root,
            captions_large_v3_root=args.captions_large_v3_root,
            signing_private_key=key,
            signing_key_id=args.signing_key_id,
            product_version=args.product_version,
            compatible_core=args.compatible_core,
            channel=args.channel,
            created_epoch=args.created_epoch
            if args.created_epoch is not None
            else int(time.time()),
        )
    except StationBundleBuildError as exc:
        print(f"build_native_station_bundle: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"station bundle report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

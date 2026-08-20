# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Guard production FFmpeg CLI call sites against the GPL-only libx264 name."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CIVICCAST_ROOT = _REPO_ROOT / "civiccast"

# The resolver interprets the legacy name immediately before selecting an
# eligible encoder. Tests live outside civiccast/.
_RESOLVER_FILE = Path("civiccast/stream/_ffmpeg.py")
_GSTREAMER_BRIDGE_FILE = Path("civiccast/egress/gst/bridge.py")
_GSTREAMER_LEGACY_MAP = "_FFMPEG_TO_GST_ENCODER"
#: The enrollment SURFACES plus the policy-test commentary that narrates them.
#: This set feeds the wording-drift guard below; the STRUCTURAL enrollment
#: GUI-catalog state is asserted separately by the acquisition catalog tests.
#: Private candidate sidecar staging is intentionally a different surface.
_FFMPEG_ENROLLMENT_WORDING_FILES = (
    Path("civiccast/apps/installer/src-tauri/src/acquisition_catalog.rs"),
    Path("civiccast/apps/installer/src/components-catalog.ts"),
)


def _libx264_literal_lines(
    source: str,
    *,
    allow_gstreamer_legacy_key: bool = False,
) -> list[int]:
    tree = ast.parse(source)
    allowed_nodes: set[int] = set()
    if allow_gstreamer_legacy_key:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            is_legacy_map = any(
                isinstance(target, ast.Name) and target.id == _GSTREAMER_LEGACY_MAP
                for target in node.targets
            )
            if is_legacy_map:
                allowed_nodes.update(
                    id(key)
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and key.value == "libx264"
                )
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and node.value == "libx264"
        and id(node) not in allowed_nodes
    )


def test_detector_flags_a_literal_encoder_argument() -> None:
    source = 'args = ["-c:v", "libx264", "output.ts"]\n'
    assert _libx264_literal_lines(source) == [1]


def test_gstreamer_legacy_mapping_exception_does_not_hide_cli_arguments() -> None:
    source = (
        '_FFMPEG_TO_GST_ENCODER = {"libx264": "openh264enc"}\n'
        'args = ["-c:v", "libx264", "output.ts"]\n'
    )
    assert _libx264_literal_lines(source, allow_gstreamer_legacy_key=True) == [2]


def test_no_production_ffmpeg_builder_carries_a_libx264_literal() -> None:
    offenders: list[str] = []
    for path in _CIVICCAST_ROOT.rglob("*.py"):
        relative = path.relative_to(_REPO_ROOT)
        if relative == _RESOLVER_FILE:
            continue
        for line in _libx264_literal_lines(
            path.read_text(encoding="utf-8"),
            allow_gstreamer_legacy_key=relative == _GSTREAMER_BRIDGE_FILE,
        ):
            offenders.append(f"{relative.as_posix()}:{line}")

    assert not offenders, (
        "production Python still contains libx264 literals outside the resolver "
        "and GStreamer legacy-name bridge: " + ", ".join(offenders)
    )


def test_public_gui_enrollment_wording_names_only_the_unpublished_pack_blocker() -> None:
    """Wording-drift guard, scoped to the public GUI acquisition surfaces:
    and their policy commentary never mention the retired libx264 blocker
    again and always name the unpublished-pack condition. It CANNOT prove the
    absence of an arbitrary differently-phrased blocker — that structural
    property is asserted by the Rust unit tests and the identity policy's
    DEFAULT_REQUIRED_COMPONENTS asserts (see _FFMPEG_ENROLLMENT_WORDING_FILES'
    comment). Terra round-2 Major 2 is answered by this division of labor."""
    obsolete_encoder_blockers: list[str] = []
    missing_unpublished_blockers: list[str] = []

    for relative in _FFMPEG_ENROLLMENT_WORDING_FILES:
        source = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        if "libx264" in source:
            obsolete_encoder_blockers.append(relative.as_posix())
        if "unpublished" not in source and "not published" not in source:
            missing_unpublished_blockers.append(relative.as_posix())

    assert not obsolete_encoder_blockers, (
        "FFmpeg pack enrollment wording still declares the repaired encoder "
        "call sites as a blocker: " + ", ".join(obsolete_encoder_blockers)
    )
    assert not missing_unpublished_blockers, (
        "FFmpeg pack enrollment wording must retain the unpublished-pack blocker: "
        + ", ".join(missing_unpublished_blockers)
    )

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Guard production FFmpeg CLI call sites against GPL-only encoder names.

Widened 2026-08-24 (S7 media-lifecycle-worker license audit): the sweep
below originally checked only the literal string "libx264". It walked the
whole ``civiccast/`` tree even then (``_CIVICCAST_ROOT.rglob("*.py")``, no
subdirectory scoping), so the gap was never which directories it covered --
it was which GPL encoder NAMES it recognized. A bare ``"libx265"`` literal
sat in ``civiccast/schedule/media_lifecycle_worker.py``'s default transcode
seed list, seeded for every validated asset by default, and this test
passed the whole time because it never looked for that name. Fixed by
generalizing the detector to a set of forbidden GPL encoder literals
(``_FORBIDDEN_GPL_ENCODER_LITERALS``) instead of one hard-coded string, and
proved with a planted-literal test
(``test_detector_flags_a_planted_libx265_literal``) so this class of gap
can't silently recur for the next GPL encoder name someone tries.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CIVICCAST_ROOT = _REPO_ROOT / "civiccast"

#: Every ffmpeg encoder name this repo's no-GPL posture forbids as a literal
#: CLI argument in production Python (ADR 0007's compliance section; the
#: native-ffmpeg-pack build's own ``gpl_negative_control`` check enforces
#: the shipped BINARY carries none of these, this test enforces the SOURCE
#: never asks for one by name). Extend this set, don't add a parallel
#: sweep, the next time a GPL encoder name shows up anywhere in the tree.
_FORBIDDEN_GPL_ENCODER_LITERALS: frozenset[str] = frozenset({"libx264", "libx265"})

# The resolver interprets the legacy "libx264" REQUEST name immediately
# before selecting an eligible (non-GPL-by-default) encoder -- see
# resolve_h264_encoder(). No equivalent resolver exists for libx265/HEVC
# anywhere in this tree (ADR 0007 amendment), so libx265 gets no exception
# here, resolver file included: only "libx264" is ever allowed through.
_RESOLVER_FILE = Path("civiccast/stream/_ffmpeg.py")
_RESOLVER_ALLOWED_LITERALS: frozenset[str] = frozenset({"libx264"})
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


def _gpl_encoder_literal_lines(
    source: str,
    *,
    in_resolver: bool = False,
    allow_gstreamer_legacy_key: bool = False,
) -> list[int]:
    """Line numbers of any forbidden GPL encoder literal, minus narrow exceptions.

    ``in_resolver`` allows ONLY the literals in ``_RESOLVER_ALLOWED_LITERALS``
    (today: just "libx264") -- a hypothetical future "libx265" in this same
    file would still be flagged, since no HEVC resolver exists to justify it.
    ``allow_gstreamer_legacy_key`` allows any forbidden literal used as a
    dict key of the GStreamer legacy-name translation map (a naming table,
    never a literal ffmpeg CLI argument).
    """
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
                    if isinstance(key, ast.Constant)
                    and key.value in _FORBIDDEN_GPL_ENCODER_LITERALS
                )
    resolver_allowed = _RESOLVER_ALLOWED_LITERALS if in_resolver else frozenset()
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and node.value in _FORBIDDEN_GPL_ENCODER_LITERALS
        and node.value not in resolver_allowed
        and id(node) not in allowed_nodes
    )


def test_detector_flags_a_literal_encoder_argument() -> None:
    source = 'args = ["-c:v", "libx264", "output.ts"]\n'
    assert _gpl_encoder_literal_lines(source) == [1]


def test_detector_flags_a_planted_libx265_literal() -> None:
    """Proves the widened sweep: a planted libx265 literal must be caught.

    This is the exact shape the real defect had --
    ``civiccast/schedule/media_lifecycle_worker.py``'s default transcode
    format table carried ``["-vf", "scale=-2:1080", "-c:v", "libx265", ...]``
    and the pre-widening detector (string-literal match on "libx264" only)
    never flagged it.
    """
    source = (
        "_FORMAT_FFMPEG_ARGS = {\n"
        '    "h265_1080p_8mbps": ["-vf", "scale=-2:1080", "-c:v", "libx265", "-b:v", "8M"],\n'
        "}\n"
    )
    assert _gpl_encoder_literal_lines(source) == [2]


def test_resolver_file_still_forbids_a_hypothetical_libx265_literal() -> None:
    """The resolver's exception is scoped to "libx264" only -- a stray
    libx265 literal there (no HEVC resolver exists to justify it) must
    still be flagged even with ``in_resolver=True``."""
    source = 'args = ["-c:v", "libx264", "-c:v", "libx265"]\n'
    assert _gpl_encoder_literal_lines(source, in_resolver=True) == [1]


def test_gstreamer_legacy_mapping_exception_does_not_hide_cli_arguments() -> None:
    source = (
        '_FFMPEG_TO_GST_ENCODER = {"libx264": "openh264enc"}\n'
        'args = ["-c:v", "libx264", "output.ts"]\n'
    )
    assert _gpl_encoder_literal_lines(source, allow_gstreamer_legacy_key=True) == [2]


def test_gstreamer_legacy_mapping_exception_covers_libx265_key_too() -> None:
    source = '_FFMPEG_TO_GST_ENCODER = {"libx265": "x265enc"}\n'
    assert _gpl_encoder_literal_lines(source, allow_gstreamer_legacy_key=True) == []


def test_no_production_ffmpeg_builder_carries_a_gpl_encoder_literal() -> None:
    offenders: list[str] = []
    for path in _CIVICCAST_ROOT.rglob("*.py"):
        relative = path.relative_to(_REPO_ROOT)
        for line in _gpl_encoder_literal_lines(
            path.read_text(encoding="utf-8"),
            in_resolver=relative == _RESOLVER_FILE,
            allow_gstreamer_legacy_key=relative == _GSTREAMER_BRIDGE_FILE,
        ):
            offenders.append(f"{relative.as_posix()}:{line}")

    assert not offenders, (
        "production Python still contains a forbidden GPL encoder literal "
        f"({sorted(_FORBIDDEN_GPL_ENCODER_LITERALS)}) outside the H.264 "
        "resolver's narrow exception and the GStreamer legacy-name bridge: " + ", ".join(offenders)
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

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""REAL junction/symlink flip tests in a temp dir (no elevation, no fakes).

``mklink /J`` needs no elevation on Windows; a POSIX symlink stands in on CI.
Either way the semantics the orchestrator depends on are proven for real here:
``current`` names a re-pointable target directory, the flip is reversible, and
removing the link NEVER deletes the target's files (the catastrophic-rmtree
guard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.native.upgrade import junction


def _tree(root: Path, name: str) -> Path:
    tree = root / "app" / name
    tree.mkdir(parents=True)
    (tree / "marker.txt").write_text(name, encoding="utf-8")
    return tree


def test_point_and_read_roundtrip(tmp_path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    t1 = _tree(root, "1.0")
    junction.point_current_at(root, t1)
    assert Path(junction.read_current_target(root)) == t1.resolve()


def test_read_before_any_flip_is_none(tmp_path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    assert junction.read_current_target(root) is None


def test_reflip_replaces_target(tmp_path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    t1 = _tree(root, "1.0")
    t2 = _tree(root, "1.1")
    junction.point_current_at(root, t1)
    junction.point_current_at(root, t2)
    assert Path(junction.read_current_target(root)) == t2.resolve()
    # Reversible: flip back.
    junction.point_current_at(root, t1)
    assert Path(junction.read_current_target(root)) == t1.resolve()


def test_current_link_reads_through_to_target_file(tmp_path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    t1 = _tree(root, "1.0")
    junction.point_current_at(root, t1)
    live = junction.current_link(root) / "marker.txt"
    assert live.read_text(encoding="utf-8") == "1.0"


def test_removing_link_never_deletes_target_files(tmp_path) -> None:
    # The catastrophic-rmtree guard: re-pointing removes the LINK, not the tree.
    root = tmp_path / "install"
    root.mkdir()
    t1 = _tree(root, "1.0")
    t2 = _tree(root, "1.1")
    junction.point_current_at(root, t1)
    junction.point_current_at(root, t2)  # this removes the old link
    assert (t1 / "marker.txt").exists()  # old tree's files survive intact
    assert t1.is_dir()


def test_point_at_missing_target_raises(tmp_path) -> None:
    root = tmp_path / "install"
    root.mkdir()
    with pytest.raises(RuntimeError, match="does not exist"):
        junction.point_current_at(root, root / "app" / "nonexistent")

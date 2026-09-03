# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for ``scripts/gate_a_expected_head.py`` (installer-path audit BL-10).

The point of this module is that it is a SECOND, independent derivation of
the repository's migration head. So the load-bearing test is the one that
asserts it agrees with :func:`civiccast.schema_check.expected_migration_head`
-- two implementations reading the same files by different means (a
standard-library AST walk vs. alembic's own ``ScriptDirectory``). That is a
real cross-check; one implementation compared against itself is the shape the
whole audit was about.

It also gives the repository the build-time single-head gate MN-07 says it
lacks: today a second head is noticed only at runtime, where
``check_schema_currency`` launders the resulting ``RuntimeError`` into
``state="unknown"``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "gate_a_expected_head.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_a_expected_head", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


geh = _load_module()


def test_agrees_with_alembics_own_head_resolution() -> None:
    """THE test. Two independent derivations of one fact must agree.

    If this ever fails, one of two genuinely important things is true: the
    migration graph has branched (MN-07), or the AST parser and alembic
    disagree about what the version locations are -- and either way the
    build-time head Gate A hands its judge would be wrong.
    """
    from civiccast.schema_check import expected_migration_head

    assert geh.compute_head(_REPO_ROOT) == expected_migration_head()


def test_the_graph_is_single_headed_and_has_no_dangling_parents() -> None:
    """<gate-a-audit-MN-07> The build-time gate the repo did not have.

    ``schema_check.expected_migration_head`` raises on more than one head,
    and ``check_schema_currency`` catches that and reports ``unknown`` -- so
    at runtime a branched graph degrades silently. Here it fails the build.
    """
    head = geh.compute_head(_REPO_ROOT)
    assert head and isinstance(head, str)


def test_reads_both_plain_and_annotated_assignment_shapes(tmp_path: Path) -> None:
    """Both shapes occur in this repository, and missing one is silent.

    Reading only ``ast.Assign`` lost every ``down_revision: str | None =
    "..."`` parent and reported 19 heads for a single-headed graph -- the
    exact near-miss this module exists to make impossible.
    """
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_base.py").write_text(
        'revision = "0001_base"\ndown_revision = None\n', encoding="utf-8"
    )
    (versions / "0002_annotated.py").write_text(
        'revision: str = "0002_annotated"\ndown_revision: str | None = "0001_base"\n',
        encoding="utf-8",
    )
    (tmp_path / "civiccast").mkdir()
    assert geh.compute_head(tmp_path) == "0002_annotated"


def test_merge_revisions_name_every_parent(tmp_path: Path) -> None:
    """A merge assigns a tuple; both parents must be consumed or the merge's
    own siblings look like heads."""
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text('revision = "a"\ndown_revision = None\n', encoding="utf-8")
    (versions / "b.py").write_text('revision = "b"\ndown_revision = "a"\n', encoding="utf-8")
    (versions / "c.py").write_text('revision = "c"\ndown_revision = "a"\n', encoding="utf-8")
    (versions / "m.py").write_text('revision = "m"\ndown_revision = ("b", "c")\n', encoding="utf-8")
    (tmp_path / "civiccast").mkdir()
    assert geh.compute_head(tmp_path) == "m"


def test_two_heads_raise_rather_than_picking_one(tmp_path: Path) -> None:
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text('revision = "a"\ndown_revision = None\n', encoding="utf-8")
    (versions / "b.py").write_text('revision = "b"\ndown_revision = "a"\n', encoding="utf-8")
    (versions / "c.py").write_text('revision = "c"\ndown_revision = "a"\n', encoding="utf-8")
    (tmp_path / "civiccast").mkdir()
    with pytest.raises(geh.MigrationGraphError, match="exactly one migration head"):
        geh.compute_head(tmp_path)


def test_a_dangling_parent_raises(tmp_path: Path) -> None:
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "b.py").write_text('revision = "b"\ndown_revision = "gone"\n', encoding="utf-8")
    (tmp_path / "civiccast").mkdir()
    with pytest.raises(geh.MigrationGraphError, match="does not exist"):
        geh.compute_head(tmp_path)


def test_duplicate_revision_ids_raise(tmp_path: Path) -> None:
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text('revision = "a"\ndown_revision = None\n', encoding="utf-8")
    (versions / "a_again.py").write_text('revision = "a"\ndown_revision = None\n', encoding="utf-8")
    (tmp_path / "civiccast").mkdir()
    with pytest.raises(geh.MigrationGraphError, match="duplicate migration revision"):
        geh.compute_head(tmp_path)


def test_cli_prints_the_head_and_exits_zero() -> None:
    """The CI job runs this as a subprocess, so the CLI contract is the one
    Gate A actually depends on."""
    from civiccast.schema_check import expected_migration_head

    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "--repo-root", str(_REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == expected_migration_head()


def test_cli_exits_nonzero_on_a_branched_graph(tmp_path: Path) -> None:
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "a.py").write_text('revision = "a"\ndown_revision = None\n', encoding="utf-8")
    (versions / "b.py").write_text('revision = "b"\ndown_revision = None\n', encoding="utf-8")
    (tmp_path / "civiccast").mkdir()
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "--repo-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "exactly one migration head" in proc.stderr

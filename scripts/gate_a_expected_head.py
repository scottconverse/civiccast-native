# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Derive the repository's single Alembic migration head from source text.

Why this exists (installer-path audit BL-10). Gate A's post-upgrade schema
guard compared two values that both came from ONE ``SchemaStatus`` object in
ONE process: ``/health``'s ``schema_db_revision`` and its
``schema_expected_head``. Because :func:`civiccast.schema_check.
evaluate_schema_currency` returns ``state="current"`` *if and only if* those
two are equal, and the harness only recorded a match when the body already
said ``current``, the guard was 1 whenever the station-up check passed --
always. It could not fail.

Closing that needs the expected head to come from an origin the station under
test cannot influence. This module is that origin: it reads the migration
files' own ``revision`` / ``down_revision`` literals with the standard library
only -- no alembic import, no database, no ``civiccast`` import, no installed
environment -- so a CI job can record the candidate's head at BUILD time and
hand the string to the gate as an input. The judge then compares the
database's own ``alembic_version`` row (read in the sandbox with ``psql``)
against THAT string, and the two sides of the comparison have genuinely
different provenance.

Being a second, independent derivation is also the point of
``tests/gate_a/test_gate_a_expected_head.py``: it asserts this module and
:func:`civiccast.schema_check.expected_migration_head` agree. Two
implementations reading the same files by different means is a real
cross-check; one implementation compared against itself is not.

Usage:
    python scripts/gate_a_expected_head.py [--repo-root PATH]

Prints the single head revision to stdout. Exits 1 (with the offending set on
stderr) when the graph does not have exactly one head -- which is also the
MN-07 build-time gate the repository previously lacked: a second head is
today only noticed at runtime, where ``check_schema_currency`` launders the
resulting ``RuntimeError`` into ``state="unknown"``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


class MigrationGraphError(RuntimeError):
    """The migration files do not form a single-headed, single-based graph."""


def _string_or_none(node: ast.AST) -> str | None:
    """Return a ``str`` literal's value, or ``None`` for ``None``/anything else.

    ``down_revision`` is idiomatically ``None`` on a base revision and a
    ``str`` elsewhere. Merge revisions use a tuple; those are handled by the
    caller, which needs every parent, not just one.
    """

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parents(node: ast.AST) -> list[str]:
    """Every parent revision a ``down_revision`` assignment names.

    A merge revision assigns a tuple/list of revision ids; an ordinary one
    assigns a single string; a base assigns ``None``. All three shapes appear
    in this repository's history (two historical merges), so all three are
    read rather than assumed.
    """

    if isinstance(node, ast.Tuple | ast.List):
        return [value for value in (_string_or_none(el) for el in node.elts) if value]
    single = _string_or_none(node)
    return [single] if single else []


def read_migration_graph(repo_root: Path) -> tuple[dict[str, list[str]], list[Path]]:
    """Parse every migration file under ``repo_root``; return revision -> parents.

    Version directories are discovered exactly the way
    :func:`civiccast.schema_check._alembic_runtime_paths` composes them for
    the running code -- the repo-root ``alembic/versions`` plus every
    per-module ``civiccast/*/migrations/versions`` -- so this walks the same
    file set alembic itself would, by a different route.
    """

    version_dirs = [repo_root / "alembic" / "versions"]
    version_dirs.extend(
        sorted(
            path
            for path in (repo_root / "civiccast").glob("*/migrations/versions")
            if path.is_dir()
        )
    )

    graph: dict[str, list[str]] = {}
    files: list[Path] = []
    for version_dir in version_dirs:
        if not version_dir.is_dir():
            continue
        for path in sorted(version_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:  # a migration that does not parse is a build break
                raise MigrationGraphError(f"{path} is not parseable Python: {exc}") from exc
            revision: str | None = None
            parents: list[str] = []
            for statement in module.body:
                # BOTH assignment shapes occur in this repository: the plain
                # `revision = "..."` alembic's own template emits, and the
                # annotated `down_revision: str | None = "..."` many of the
                # per-module migrations use. Reading only ast.Assign silently
                # lost every annotated parent and reported 19 heads for a
                # single-headed graph -- exactly the kind of quiet
                # near-miss this module exists to make impossible.
                if isinstance(statement, ast.Assign):
                    targets = [t.id for t in statement.targets if isinstance(t, ast.Name)]
                    value = statement.value
                elif isinstance(statement, ast.AnnAssign) and isinstance(
                    statement.target, ast.Name
                ):
                    targets = [statement.target.id]
                    value = statement.value
                else:
                    continue
                if value is None:  # a bare annotation, e.g. `down_revision: str`
                    continue
                if "revision" in targets:
                    revision = _string_or_none(value)
                if "down_revision" in targets:
                    parents = _parents(value)
            if revision is None:
                # Not a migration module (helpers occasionally live beside
                # them); skip rather than fail the whole derivation.
                continue
            if revision in graph:
                raise MigrationGraphError(
                    f"duplicate migration revision {revision!r} (second definition at {path})"
                )
            graph[revision] = parents
            files.append(path)
    return graph, files


def compute_head(repo_root: Path) -> str:
    """The single head revision, or raise :class:`MigrationGraphError`.

    A head is a revision no other revision names as a parent. Exactly one is
    required -- the same invariant :func:`civiccast.schema_check.
    expected_migration_head` enforces, asserted here at build time instead of
    at first boot, where the failure is laundered into ``state="unknown"``.
    """

    graph, files = read_migration_graph(repo_root)
    if not graph:
        raise MigrationGraphError(f"no migration files found under {repo_root}")

    referenced: set[str] = set()
    for parents in graph.values():
        referenced.update(parents)

    dangling = sorted(referenced - set(graph))
    if dangling:
        raise MigrationGraphError(
            f"{len(dangling)} migration parent(s) name a revision that does not exist: {dangling}"
        )

    heads = sorted(set(graph) - referenced)
    if len(heads) != 1:
        raise MigrationGraphError(
            f"expected exactly one migration head across {len(files)} files, found {heads!r}"
        )
    return heads[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root to derive the head from (default: this script's repo)",
    )
    args = parser.parse_args(argv)
    try:
        print(compute_head(args.repo_root))
    except MigrationGraphError as exc:
        print(f"gate_a_expected_head: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Verify CivicCast roadmap status against the repository — fail closed.

Reads ``docs/spec/3.0/ROADMAP.status.yaml`` (one row per build step 0-14 and per
spec section S1-S26) and checks each row's *asserted* status against
machine-checkable *evidence* that lives in the repo: Alembic migration revision
ids, module file paths, defined symbols, and test files. The single rule is

    actual >= asserted        (ordered  unbuilt < partial < built)

so the verifier catches BOTH a status claimed higher than the evidence supports
(a false "built") AND a regression (a built thing whose evidence later vanished).

It is deliberately fail-closed: an unresolved evidence pointer counts as absent,
and any structurally invalid manifest row is an error (exit 2), never a silent
pass. "Where are we?" becomes a command you can run, not a thing to remember.

Usage::

    python scripts/roadmap_status.py            # print the status table
    python scripts/roadmap_status.py --check     # ...and exit non-zero on any miss
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs" / "spec" / "3.0" / "ROADMAP.status.yaml"

STATUS_ORDER = {"unbuilt": 0, "partial": 1, "built": 2}
VALID_KINDS = {"build_step", "section"}
VALID_DISPOSITIONS = {"extend", "net-new", "optional", "v2"}
EVIDENCE_GROUPS = ("migrations", "modules", "symbols", "tests")
REQUIRED_KEYS = ("id", "kind", "status", "disposition")

# A literal "none" evidence entry is an explicit assertion of absence (e.g. an
# unbuilt net-new row that has no migration yet). It never counts as present and
# never counts toward the evidence total.
_ABSENT_SENTINELS = {"", "none"}


class ManifestError(ValueError):
    """The manifest is structurally invalid — fail closed (do not pass)."""


@dataclass(frozen=True)
class RowResult:
    """The verdict for one manifest row."""

    row_id: str
    asserted: str
    actual: str
    present: int
    total: int
    ok: bool
    detail: tuple[str, ...]


# --------------------------------------------------------------------------- #
# evidence resolvers — each returns True only on a confident match
# --------------------------------------------------------------------------- #


def _versions_files(repo: Path) -> list[Path]:
    """Every Alembic versions file — per-module dirs plus the central tree."""
    found = list(repo.glob("**/migrations/versions/*.py"))
    found.extend((repo / "alembic" / "versions").glob("*.py"))
    return found


def migration_exists(repo: Path, revision: str) -> bool:
    """True if some versions file declares exactly ``revision = "<revision>"``."""
    if revision in _ABSENT_SENTINELS:
        return False
    pattern = re.compile(
        r"^revision\s*=\s*[\"']" + re.escape(revision) + r"[\"']\s*$", re.MULTILINE
    )
    return any(pattern.search(path.read_text(encoding="utf-8")) for path in _versions_files(repo))


def file_exists(repo: Path, relpath: str) -> bool:
    """True if ``relpath`` resolves to a file inside the repo.

    Evidence may use a narrow glob when the literal filename contains a term
    that cannot appear in public status manifests.
    """
    if relpath in _ABSENT_SENTINELS:
        return False
    if any(char in relpath for char in "*?["):
        return any(path.is_file() for path in repo.glob(relpath))
    return (repo / relpath).is_file()


def symbol_defined(repo: Path, relpath: str, name: str) -> bool:
    """True if ``name`` is defined/exported in ``relpath`` (Python or TS/TSX)."""
    target = repo / relpath
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    escaped = re.escape(name)
    patterns = (
        rf"\b(?:def|class)\s+{escaped}\b",
        rf"\b(?:struct|enum|protocol|actor)\s+{escaped}\b",
        rf"\b(?:sub|function)\s+{escaped}\b",
        rf"\b(?:function|const|let|var)\s+{escaped}\b",
        rf"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|const|class)\s+{escaped}\b",
        rf"^\s*{escaped}\s*[:=]",
    )
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def has_test(repo: Path, relpath: str) -> bool:
    """True if ``relpath`` is a test file, or a dir containing test files."""
    if relpath in _ABSENT_SENTINELS:
        return False
    target = repo / relpath
    if target.is_file():
        return True
    if target.is_dir():
        return (
            any(target.glob("**/test_*.py"))
            or any(target.glob("**/*.spec.ts"))
            or any(target.glob("**/*.test.ts"))
        )
    return False


# --------------------------------------------------------------------------- #
# manifest validation + row evaluation
# --------------------------------------------------------------------------- #


def validate_row(row: object) -> None:
    """Raise :class:`ManifestError` unless ``row`` is a well-formed entry."""
    if not isinstance(row, dict):
        raise ManifestError(f"row is not a mapping: {row!r}")
    for key in REQUIRED_KEYS:
        if key not in row:
            raise ManifestError(f"row missing required key {key!r}: {row.get('id', row)!r}")
    if row["status"] not in STATUS_ORDER:
        raise ManifestError(f"row {row['id']!r}: invalid status {row['status']!r}")
    if row["kind"] not in VALID_KINDS:
        raise ManifestError(f"row {row['id']!r}: invalid kind {row['kind']!r}")
    if row["disposition"] not in VALID_DISPOSITIONS:
        raise ManifestError(f"row {row['id']!r}: invalid disposition {row['disposition']!r}")
    evidence = row.get("evidence", {})
    if not isinstance(evidence, dict):
        raise ManifestError(f"row {row['id']!r}: evidence is not a mapping")
    unknown = set(evidence) - set(EVIDENCE_GROUPS)
    if unknown:
        raise ManifestError(f"row {row['id']!r}: unknown evidence groups {sorted(unknown)}")
    for sym in evidence.get("symbols", []):
        if not isinstance(sym, dict) or "file" not in sym or "name" not in sym:
            raise ManifestError(f"row {row['id']!r}: symbol entry needs file+name: {sym!r}")


def _evidence_items(repo: Path, evidence: dict) -> list[tuple[str, bool]]:
    """Flatten a row's evidence into ``(label, present)`` pairs, skipping sentinels."""
    items: list[tuple[str, bool]] = []
    for rev in evidence.get("migrations", []):
        if rev not in _ABSENT_SENTINELS:
            items.append((f"migration {rev}", migration_exists(repo, rev)))
    for mod in evidence.get("modules", []):
        if mod not in _ABSENT_SENTINELS:
            items.append((f"module {mod}", file_exists(repo, mod)))
    for sym in evidence.get("symbols", []):
        label = f"symbol {sym['name']} in {sym['file']}"
        items.append((label, symbol_defined(repo, sym["file"], sym["name"])))
    for test in evidence.get("tests", []):
        if test not in _ABSENT_SENTINELS:
            items.append((f"test {test}", has_test(repo, test)))
    return items


def evaluate_row(repo: Path, row: object) -> RowResult:
    """Validate ``row`` and compute its verdict against the repo."""
    validate_row(row)
    assert isinstance(row, dict)  # narrowed by validate_row
    items = _evidence_items(repo, row.get("evidence", {}))
    total = len(items)
    present = sum(1 for _, ok in items if ok)
    if total and present == total:
        actual = "built"
    elif present == 0:
        actual = "unbuilt"
    else:
        actual = "partial"
    asserted = row["status"]
    detail = tuple(f"{'OK ' if ok else 'XX '}{label}" for label, ok in items)
    return RowResult(
        row_id=row["id"],
        asserted=asserted,
        actual=actual,
        present=present,
        total=total,
        ok=STATUS_ORDER[actual] >= STATUS_ORDER[asserted],
        detail=detail,
    )


def verify(repo: Path, rows: list) -> tuple[bool, list[RowResult]]:
    """Evaluate every row; return ``(all_ok, results)``. Raises on malformed rows."""
    results = [evaluate_row(repo, row) for row in rows]
    return all(r.ok for r in results), results


def parse_manifest(data: object) -> list:
    """Return the validated ``rows`` list from parsed manifest ``data``."""
    if not isinstance(data, dict) or "rows" not in data:
        raise ManifestError("manifest must be a mapping with a 'rows' key")
    rows = data["rows"]
    if not isinstance(rows, list) or not rows:
        raise ManifestError("manifest 'rows' must be a non-empty list")
    ids = [r["id"] for r in rows if isinstance(r, dict) and "id" in r]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ManifestError(f"duplicate row ids: {duplicates}")
    return rows


def load_manifest(path: Path) -> list:
    """Load + validate the manifest at ``path`` (YAML)."""
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    import yaml  # lazy: only the CLI path needs a YAML parser

    return parse_manifest(yaml.safe_load(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# rendering + CLI
# --------------------------------------------------------------------------- #


def render_table(results: list[RowResult]) -> str:
    """A scannable status table; failing rows carry their missing evidence."""
    width = max((len(r.row_id) for r in results), default=2)
    lines = [f"{'ID'.ljust(width)}  ASSERTED  ACTUAL    EVID   RESULT"]
    for r in results:
        verdict = "ok" if r.ok else "FAIL"
        lines.append(
            f"{r.row_id.ljust(width)}  {r.asserted.ljust(8)}  "
            f"{r.actual.ljust(8)}  {r.present}/{r.total}".ljust(width + 32)
            + f"  {verdict}"
        )
        if not r.ok:
            lines.extend(f"      - {d}" for d in r.detail if d.startswith("XX "))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify CivicCast roadmap status.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any row's actual status is below its asserted status",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_manifest(args.manifest)
        _all_ok, results = verify(args.repo, rows)
    except ManifestError as exc:
        print(f"ROADMAP MANIFEST ERROR: {exc}", file=sys.stderr)
        return 2

    print(render_table(results))
    failed = [r.row_id for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} row(s) below asserted status: {', '.join(failed)}", file=sys.stderr)
        if args.check:
            return 1
    else:
        print(f"\nAll {len(results)} rows verified (actual >= asserted).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

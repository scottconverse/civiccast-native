# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: nothing in the shipped native payload may depend on ``psycopg2``.

Chain K/K1. Real-hardware R7 (2026-08-01, request 0053b) rolled the native
installer's upgrade back with ``No module named 'psycopg2'`` -- the fourth
recorded instance of the same defect class (Sandbox runs 13, 16, 19, then R7).
Each previous fix normalized ONE newly-discovered call site and left the class
open. This module closes the class with two structural guards over the
ACTUAL shipped set:

1. **Dependency guard.** The pack build's own dependency source
   (``scripts/build_native_app_payload.py``'s ``APP_REQUIREMENTS_FILE``, i.e.
   the hash-pinned ``requirements-native-app.txt``) must pin psycopg v3 and
   must not pin psycopg2 in any spelling. Read from the build module's own
   constant rather than a path literal, so a relocation of the lock cannot
   leave this guard silently pointing at a file that no longer ships.
2. **Call-site guard.** No module inside the shipped ``civiccast`` wheel may
   ``import psycopg2``, and every ``create_engine``/``make_url`` call in that
   wheel must build its URL through
   :func:`civiccast.db.url.normalize_database_url` (or from a literal whose
   scheme already names a driver, e.g. the sqlite lanes). AST-based, so a
   comment mentioning psycopg2 -- of which this tree has many -- is never
   mistaken for a dependency.

Guard 2 is the one that would have caught R7: no shipped module has EVER
contained a literal ``import psycopg2``. The dependency is created implicitly
by SQLAlchemy's default dialect selection for a driver-less ``postgresql://``
scheme, at engine construction. A guard that only looked for the import
statement would have passed on every one of the four failures.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "civiccast"

#: Callables whose first positional argument is a DATABASE_URL that SQLAlchemy
#: resolves a dialect from. ``make_url`` is included because it is the other
#: entry point that parses a scheme into a driver name.
_URL_CONSUMING_CALLS = {"create_engine", "_create_engine", "make_url"}

#: The normalizer every Postgres URL in the shipped wheel must pass through.
_NORMALIZER = "normalize_database_url"

#: The module that DEFINES the normalizer. Its own ``make_url`` call is how
#: normalization is implemented, so it is the one module the call-site guard
#: cannot apply to. Named as a single path, not an open allowlist.
_NORMALIZER_MODULE = "civiccast/db/url.py"

#: Schemes that already name a driver (or are not Postgres at all) and so need
#: no normalization when passed as a literal.
_SAFE_LITERAL_SCHEMES = ("sqlite:", "postgresql+")


def _load_payload_builder():
    """Import ``scripts/build_native_app_payload.py`` by path.

    ``scripts/`` is not an importable package, so this is loaded through
    importlib rather than a plain import -- the point is to read the BUILD's
    own constant, not to re-declare it here.
    """

    module_path = REPO_ROOT / "scripts" / "build_native_app_payload.py"
    spec = importlib.util.spec_from_file_location("_civiccast_payload_builder", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pinned_distributions(requirements_file: Path) -> set[str]:
    """Distribution names pinned in a ``uv pip compile`` hash-pinned lock."""

    names: set[str] = set()
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def _shipped_python_modules() -> list[Path]:
    """Every ``.py`` file inside the shipped ``civiccast`` package.

    The payload builder installs the ``civiccast`` wheel into
    ``<root>\\runtime``; the wheel's content is this package directory, so the
    package tree IS the shipped module set. Test/build directories live
    outside it and are correctly excluded.
    """

    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_pack_dependency_source_pins_psycopg_v3_and_never_psycopg2() -> None:
    """Derived from the pack build's own ``APP_REQUIREMENTS_FILE`` constant."""

    builder = _load_payload_builder()
    requirements_file = Path(builder.APP_REQUIREMENTS_FILE)
    assert requirements_file.is_file(), (
        f"the pack build's dependency source does not exist: {requirements_file}"
    )

    pinned = _pinned_distributions(requirements_file)
    assert "psycopg" in pinned, (
        "the shipped payload must pin psycopg v3 (ADR 0008) -- if this ever "
        "fails, the driver every normalized URL names is not in the wheel set"
    )
    offenders = sorted(name for name in pinned if name.startswith("psycopg2"))
    assert offenders == [], (
        f"{requirements_file.name} pins a psycopg2 distribution: {offenders}. "
        "ADR 0008 ships psycopg v3 only; adding psycopg2 would hide the "
        "unnormalized-URL defect class instead of fixing it."
    )


@pytest.mark.parametrize("module_path", _shipped_python_modules(), ids=_relative)
def test_shipped_module_never_imports_psycopg2(module_path: Path) -> None:
    """AST-checked: no ``import psycopg2`` / ``from psycopg2 import ...``."""

    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "psycopg2", (
                    f"{_relative(module_path)}:{node.lineno} imports psycopg2, "
                    "which the shipped payload does not contain (ADR 0008)"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "psycopg2", (
                f"{_relative(module_path)}:{node.lineno} imports from psycopg2, "
                "which the shipped payload does not contain (ADR 0008)"
            )


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_safe_literal(argument: ast.expr) -> bool:
    """A string/f-string literal whose scheme already names a driver, or is
    not Postgres at all (``sqlite:``, ``postgresql+``)."""

    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value.startswith(_SAFE_LITERAL_SCHEMES)
    if isinstance(argument, ast.JoinedStr):
        first = argument.values[0] if argument.values else None
        return (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.startswith(_SAFE_LITERAL_SCHEMES)
        )
    return False


def _expression_is_normalized(argument: ast.expr, normalized_names: set[str]) -> bool:
    """Is this URL expression safe from SQLAlchemy's default dialect selection?

    Safe forms:

    * a call to ``normalize_database_url(...)``, or to a helper whose name ends
      in ``_engine_url`` (this tree's convention for "returns a URL this
      module's own SQLAlchemy reads may connect through" --
      ``civiccast.dr.restore_drill._verification_engine_url``);
    * a safe literal (see :func:`_is_safe_literal`);
    * a name already known-normalized in the enclosing function;
    * anything DERIVED from one of the above -- a call with a normalized
      argument (``_with_database_name(verify_source_url, ...)`` only swaps the
      database-name component and keeps the scheme), or an ``or`` fallback
      whose every operand is normalized.
    """

    if _is_safe_literal(argument):
        return True
    if isinstance(argument, ast.Name):
        return argument.id in normalized_names
    if isinstance(argument, ast.Call):
        name = _call_name(argument)
        if name == _NORMALIZER or (name is not None and name.endswith("_engine_url")):
            return True
        return any(
            _expression_is_normalized(child, normalized_names)
            for child in [*argument.args, *(kw.value for kw in argument.keywords)]
        )
    if isinstance(argument, ast.BoolOp):
        return all(_expression_is_normalized(value, normalized_names) for value in argument.values)
    return False


def _normalized_names_in(scope: ast.AST) -> set[str]:
    """Names assigned a normalized URL anywhere in ``scope``.

    Iterated to a fixpoint so a chain of derivations
    (``a = normalize(...)`` -> ``b = _with_database_name(a, ...)``) is followed
    regardless of statement order.
    """

    assignments: list[tuple[str, ast.expr]] = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.append((target.id, node.value))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.append((node.target.id, node.value))

    normalized: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, value in assignments:
            if name not in normalized and _expression_is_normalized(value, normalized):
                normalized.add(name)
                changed = True
    return normalized


class _UrlCallAuditor(ast.NodeVisitor):
    """Collect engine/URL constructions built on an unnormalized value.

    Scope-aware in two ways that keep the guard honest rather than merely
    quiet:

    * per-function normalized-name sets (so a variable that provably holds a
      normalized URL is accepted, and a function parameter is not);
    * an ``if ... sqlite ...`` branch suppresses the check inside that branch
      only -- the sqlite lanes in ``civiccast/app.py`` and ``civiccast/cli.py``
      construct their engines under exactly that test, and a sqlite URL can
      never resolve to a Postgres dialect.
    """

    def __init__(self) -> None:
        self.offenders: list[str] = []
        self._normalized: set[str] = set()
        self._sqlite_guarded = False

    def _visit_scope(self, node: ast.AST) -> None:
        saved = self._normalized
        self._normalized = saved | _normalized_names_in(node)
        self.generic_visit(node)
        self._normalized = saved

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope
    visit_Module = _visit_scope

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        saved = self._sqlite_guarded
        if "sqlite" in ast.unparse(node.test).lower():
            self._sqlite_guarded = True
        for statement in node.body:
            self.visit(statement)
        self._sqlite_guarded = saved
        for statement in node.orelse:
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            not self._sqlite_guarded
            and _call_name(node) in _URL_CONSUMING_CALLS
            and node.args
            and not _expression_is_normalized(node.args[0], self._normalized)
        ):
            self.offenders.append(f"line {node.lineno}: {ast.unparse(node.args[0])}")
        self.generic_visit(node)


@pytest.mark.parametrize("module_path", _shipped_python_modules(), ids=_relative)
def test_shipped_module_never_builds_an_engine_on_an_unnormalized_url(
    module_path: Path,
) -> None:
    """Every URL the shipped wheel hands SQLAlchemy must name its driver.

    This is the guard that fails on the R7 defect: ``create_engine(
    verify_source_url)`` in ``civiccast/dr/restore_drill.py``, reached from D3
    step 3's pre-upgrade restore-drill spot check.
    """

    if _relative(module_path) == _NORMALIZER_MODULE:
        pytest.skip(
            f"{_NORMALIZER_MODULE} IS the normalizer -- its own make_url() call is "
            "how normalization is implemented, so it cannot be required to call "
            "itself first"
        )

    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    auditor = _UrlCallAuditor()
    auditor.visit(tree)
    offenders = auditor.offenders

    assert offenders == [], (
        f"{_relative(module_path)} builds a SQLAlchemy engine/URL from a value "
        "that is not passed through civiccast.db.url.normalize_database_url: "
        + "; ".join(offenders)
        + ". A driver-less `postgresql://` resolves to the psycopg2 dialect, "
        "which this product never ships (ADR 0008) -- that is the exact defect "
        "that rolled back the R7 install."
    )

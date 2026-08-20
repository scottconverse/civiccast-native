# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""SEC-1 CI policy lint: every ``/api/staff`` mutation route must carry a role marker.

Background: the SEC-1 audit found 24 ``/api/staff`` POST/PUT/PATCH/DELETE
routes reachable by any authenticated staff token regardless of product
role -- e.g. a ``records_clerk`` token could drive
``/api/staff/facility/router-take-plan`` (AV routing) or
``/api/staff/installer/actions`` (reset/uninstall). Those 24 routes were
fixed by adding ``Depends(require_any_role(...))`` in the same style
already used across the router modules.

This test is the CI guardrail that keeps that class of gap from
reappearing: it AST-walks every module under the repo (mirroring the
audit's enumerator script) for FastAPI mutating-route decorators, resolves
each route's mounted path from its router's ``prefix=``, and asserts that
every route whose resolved path starts with ``/api/staff`` carries a
role-enforcement marker in one of the three places FastAPI allows it:

* the route decorator's ``dependencies=`` kwarg,
* the owning router's ``APIRouter(..., dependencies=[...])`` kwarg, or
* a function-argument ``Depends(...)`` default.

Non-vacuity: ``test_discovery_finds_expected_route_volume`` pins a floor on
how many mutation routes discovery must find, so a refactor that silently
breaks the AST pattern (renamed decorator shape, a different routing
library, etc.) fails loud instead of leaving this test vacuously green.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MUTATING_METHODS = {"post", "put", "patch", "delete"}
ROLE_MARKERS = ("require_any_role", "require_role", "rolechecker", "requires_role")

# Directories excluded from the AST walk -- matches the SEC-1 audit's
# enumerator exactly (test suites, caches, and Alembic migrations are not
# FastAPI route modules).
_SKIP_PARTS = {"tests", "test", "__pycache__", "alembic"}

# Explicit allowlist for intentional exceptions to "every /api/staff
# mutation route requires a role marker". Empty at introduction -- SEC-1
# closed every known gap in the release-branch inventory. Add an entry
# here ONLY with a comment explaining why the specific route cannot carry
# require_any_role (e.g. a different, equally strong auth model), the same
# way the 15 out-of-scope non-staff routes (setup nonce-gated, public
# contribute/subscribe, Stripe webhook, AP inbox) are handled by simply
# not being under /api/staff.
ALLOWED_UNGUARDED_STAFF_MUTATION_ROUTES: frozenset[tuple[str, str]] = frozenset()


def _src(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def _has_role_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ROLE_MARKERS)


def _iter_candidate_files() -> list[Path]:
    return [p for p in REPO_ROOT.rglob("*.py") if not (set(p.parts) & _SKIP_PARTS)]


def _discover_mutation_routes() -> list[dict[str, object]]:
    """AST-walk the repo for mutating FastAPI route decorators.

    For each ``*.py`` file (outside tests/caches/alembic), records every
    ``APIRouter(prefix=..., dependencies=...)`` assignment, then every
    ``@<router_var>.<verb>(...)``-decorated function whose verb is a
    mutating HTTP method. Each discovered route records its resolved path
    (router prefix + literal path argument) and whether a role-enforcement
    dependency appears in the decorator's ``dependencies=``, the owning
    router's ``dependencies=``, or a function-argument ``Depends(...)``
    default.
    """

    rows: list[dict[str, object]] = []

    for py in _iter_candidate_files():
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        router_info: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            callee = _src(node.value.func)
            if not callee.endswith("APIRouter"):
                continue
            prefix = ""
            router_deps = ""
            for kw in node.value.keywords:
                if kw.arg == "prefix":
                    prefix = _src(kw.value).strip("'\"")
                if kw.arg == "dependencies":
                    router_deps = _src(kw.value)
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    router_info[tgt.id] = (prefix, router_deps)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                method = dec.func.attr.lower()
                if method not in MUTATING_METHODS:
                    continue
                router_var = _src(dec.func.value)
                path_arg = _src(dec.args[0]).strip("'\"") if dec.args else ""
                prefix, router_deps = router_info.get(router_var, ("", ""))
                deco_deps = ""
                for kw in dec.keywords:
                    if kw.arg == "dependencies":
                        deco_deps = _src(kw.value)
                fn_deps: list[str] = []
                args = node.args
                defaults = list(args.defaults) + list(args.kw_defaults or [])
                for d in defaults:
                    if d is not None and "Depends" in _src(d):
                        fn_deps.append(_src(d))
                all_dep_text = " ".join((deco_deps, router_deps, *fn_deps))
                rows.append(
                    {
                        "file": str(py.relative_to(REPO_ROOT)),
                        "line": dec.lineno,
                        "method": method.upper(),
                        "path": (prefix + path_arg) or path_arg,
                        "has_role_check": _has_role_marker(all_dep_text),
                    }
                )

    return rows


def test_discovery_finds_expected_route_volume() -> None:
    """Non-vacuity guard: AST discovery must keep finding routes at scale.

    Pinned to the SEC-1 audit's baseline (209 mutation routes repo-wide).
    A drop below this floor means the discovery pattern broke -- not that
    the codebase shrank -- and the guarantee below would otherwise pass
    empty and silent.
    """

    rows = _discover_mutation_routes()
    assert len(rows) >= 200, (
        f"AST route discovery only found {len(rows)} mutation routes; expected >= 200. "
        "This usually means the discovery pattern (APIRouter/@router.<verb> decorator "
        "shape) changed and the policy test below is now vacuous."
    )


def test_every_staff_mutation_route_has_a_role_marker() -> None:
    rows = _discover_mutation_routes()
    staff_mutation_routes = [r for r in rows if str(r["path"]).startswith("/api/staff")]

    assert staff_mutation_routes, "Expected to discover /api/staff mutation routes."

    unguarded = [
        r
        for r in staff_mutation_routes
        if not r["has_role_check"]
        and (str(r["method"]), str(r["path"])) not in ALLOWED_UNGUARDED_STAFF_MUTATION_ROUTES
    ]

    assert not unguarded, (
        "Unguarded /api/staff mutation route(s) found -- add "
        + (
            "Depends(require_any_role(...)) at the decorator, router, or function-arg "
            "level, or add an explained entry to ALLOWED_UNGUARDED_STAFF_MUTATION_ROUTES:\n"
        )
        + "\n".join(f"  {r['method']} {r['path']} ({r['file']}:{r['line']})" for r in unguarded)
    )

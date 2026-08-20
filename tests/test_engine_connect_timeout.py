# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""PE-2026-07-22-1 item 2: every production Postgres engine builder must bound connect time.

``civiccast/db/session.py`` bounds connect time via ``connect_options()``, but the
memoized ``get_engine()`` that uses it is not on the path any long-running worker or
boot sequence takes -- those build their own engine. The original fix reached only two
of the real builders (``civiccast.app._create_database_engine`` and
``civiccast.cli._bind_egress_database``); an adversarial review found four more that
still built a Postgres engine with no ``connect_args`` and would hang on an unreachable
database -- including ``civiccast.live.finalization_worker`` and
``civiccast.captions.tap_worker``, the exact long-running-worker class the incident
(a 6m36s hang) was about.

Two kinds of test guard the fix:

* the two ``test_*_builder_bounds_*`` tests below exercise the two builders that are
  cleanly callable, monkeypatching ``create_engine`` to capture the kwargs actually
  passed to the driver -- the real behavioural proof;
* ``test_no_unbounded_postgres_engine_builder`` statically walks every
  ``create_engine(...)`` call in ``civiccast/`` and asserts that any call whose first
  argument is a ``database_url``-shaped variable either spreads ``connect_options`` or
  lives on a sqlite-only path -- the post-condition the incident's safety claim really
  rests on, and a regression guard so a seventh unbounded builder cannot be added
  silently.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


class _FakeEngine:
    """Stand-in returned by the monkeypatched create_engine in the builder tests.

    Carries a no-op ``dispose()`` so that even if a fake engine ever reached the
    process-global engine slot, a later test's ``reset_engine()`` teardown would
    not crash with ``AttributeError: 'object' object has no attribute 'dispose'``.
    The autouse fixture below is the primary guard; this is the backstop.
    """

    def dispose(self) -> None:  # pragma: no cover - defensive no-op
        return None


@pytest.fixture(autouse=True)
def _no_engine_leak() -> Iterator[None]:
    """Guarantee these tests leave no engine in the process-global slot.

    The builder tests monkeypatch ``create_engine`` to return a stand-in. If any
    path bound that stand-in as the global engine, an unrelated later test's
    ``reset_engine()`` teardown would call ``.dispose()`` on it. Clearing the
    slot directly (not via ``reset_engine``, which would itself dispose) after
    each test removes that cross-test coupling.
    """

    yield
    import civiccast.db.session as _session

    _session._engine = None
    _session._session_factory = None


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CIVICCAST_ROOT = _REPO_ROOT / "civiccast"
# session.py DEFINES connect_options and uses it; it is not an unbounded builder.
_ALLOWED_UNSPREAD = {Path("db") / "session.py"}
# SQLAlchemy engine-builder APIs. engine_from_config is how alembic/env.py builds
# the migration engine -- a real production Postgres builder the create_engine-only
# guard was blind to. _create_engine is the alias dr/backup.py imports
# (``from sqlalchemy import create_engine as _create_engine``); including it here
# means an aliased import cannot slip an unbounded builder past the guard.
_BUILDER_NAMES = {"create_engine", "_create_engine", "engine_from_config"}
# Real Postgres builders that live outside the civiccast/ package tree and so are
# not reached by rglob under _CIVICCAST_ROOT, but must still be bounded.
_EXTRA_SCANNED_FILES = (_REPO_ROOT / "alembic" / "env.py",)


def test_connect_options_explicit_timeout_overrides_env_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A site-local ``timeout_seconds`` must win over the env override.

    The native upgrade reachability probe's 5 s bound is load-bearing
    (BLOCKER #51 timing); if global tuning could loosen it, the probe's
    timing contract would drift silently.
    """

    from civiccast.db import connect_options

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "30")
    assert connect_options("postgresql://h/db", timeout_seconds=5) == {
        "connect_args": {"connect_timeout": 5}
    }
    # Without the explicit bound the env override still governs.
    assert connect_options("postgresql://h/db") == {"connect_args": {"connect_timeout": 30}}
    # SQLite stays exempt regardless of any bound.
    assert connect_options("sqlite:///f.db", timeout_seconds=5) == {}


def test_app_engine_builder_bounds_postgres_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """civiccast.app._create_database_engine passes a bounded connect_timeout."""

    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeEngine()

    import civiccast.app as app_module

    monkeypatch.setattr(app_module, "create_engine", fake_create_engine)

    app_module._create_database_engine("postgresql+psycopg://u:p@127.0.0.1:1/db")

    connect_args = captured["kwargs"].get("connect_args")
    assert connect_args is not None, (
        "civiccast.app._create_database_engine built a Postgres engine with no "
        "connect_args -- an unreachable server can stall the caller for the "
        "driver's own default timeout instead of the documented bound."
    )
    timeout = connect_args.get("connect_timeout")
    assert isinstance(timeout, int) and 0 < timeout <= 10


def test_cli_egress_engine_builder_bounds_postgres_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """civiccast.cli._bind_egress_database passes a bounded connect_timeout."""

    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeEngine()

    def fake_bind_engine(engine: object) -> None:
        captured["bound_engine"] = engine

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)
    monkeypatch.setattr("civiccast.db.bind_engine", fake_bind_engine)

    import civiccast.cli as cli_module

    cli_module._bind_egress_database("postgresql+psycopg://u:p@127.0.0.1:1/db")

    connect_args = captured["kwargs"].get("connect_args")
    assert connect_args is not None, (
        "civiccast.cli._bind_egress_database built a Postgres engine with no "
        "connect_args -- the CLI-owned egress worker can stall against an "
        "unreachable Postgres for the driver's own default timeout instead "
        "of the documented bound."
    )
    timeout = connect_args.get("connect_timeout")
    assert isinstance(timeout, int) and 0 < timeout <= 10


def _spreads_connect_options(call: ast.Call) -> bool:
    """True if the create_engine call spreads ``**connect_options(...)``."""

    for kw in call.keywords:
        # dict unpacking (**something) is a keyword with arg=None
        if kw.arg is None and isinstance(kw.value, ast.Call):
            func = kw.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "connect_options":
                return True
    return False


def _first_arg_is_sqlite_literal(call: ast.Call) -> bool:
    """True if the first arg is a hardcoded sqlite URL literal.

    ``create_engine("sqlite:///...")`` (or an f-string sqlite path) has no
    network connect phase and needs no bound. Anything else -- a variable, a
    subscript, an attribute, a keyword ``url=`` -- is treated as a potential
    runtime database URL and is NOT exempt on this ground.
    """

    args = list(call.args)
    if not args:
        return False
    first = args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.startswith("sqlite")
    if isinstance(first, ast.JoinedStr):  # f"sqlite:///{path}"
        head = first.values[0] if first.values else None
        return (
            isinstance(head, ast.Constant)
            and isinstance(head.value, str)
            and head.value.startswith("sqlite")
        )
    return False


def _is_sqlite_guard(test: ast.expr) -> bool:
    """True if an ``if`` test is ``<x>.startswith("sqlite")``.

    The sqlite branch of a builder is not a Postgres builder: sqlite is a local
    file with no connect phase, so it is exempt from the connect-timeout rule
    even though it also takes ``database_url``.
    """

    return _sqlite_guard_var(test) is not None


def _sqlite_guard_var(test: ast.expr) -> str | None:
    """The variable name in an ``<name>.startswith("sqlite")`` test, else None.

    Returns the guarded variable so the exemption can require it to be the SAME
    variable passed to the nested builder. An adversarial review showed that
    exempting on the mere presence of a sqlite-guarded ``if`` -- without checking
    the guarded variable matched the builder's URL argument -- let a decoy guard
    (``if decoy.startswith("sqlite"):`` around ``create_engine(database_url)``)
    slip an unbounded Postgres builder past the check.
    """

    if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)):
        return None
    if test.func.attr != "startswith":
        return None
    if not any(isinstance(a, ast.Constant) and a.value == "sqlite" for a in test.args):
        return None
    obj = test.func.value
    return obj.id if isinstance(obj, ast.Name) else None


def _first_arg_name(call: ast.Call) -> str | None:
    """The name of the builder's first positional argument, if it is a bare Name."""

    if call.args and isinstance(call.args[0], ast.Name):
        return call.args[0].id
    return None


def _sqlite_exempt_call_lines(tree: ast.Module) -> set[int]:
    """Lines of builder calls exempt because they are genuinely sqlite-guarded.

    A call is exempt only when it sits inside ``if <var>.startswith("sqlite")``
    AND its own first positional argument is that SAME ``<var>`` -- so the branch
    that runs it truly only runs for a sqlite URL. A guard on any other variable
    does not exempt it.
    """

    exempt: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        guard_var = _sqlite_guard_var(node.test)
        if guard_var is None:
            continue
        for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(inner, ast.Call):
                f = inner.func
                fn = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if fn in _BUILDER_NAMES and _first_arg_name(inner) == guard_var:
                    exempt.add(inner.lineno)
    return exempt


def _unbounded_create_engine_lines(source: str) -> list[int]:
    """Line numbers of create_engine calls in ``source`` that are not provably safe.

    A call is safe iff it spreads ``connect_options(...)``, its first argument is
    a hardcoded ``sqlite`` URL literal, or it is inside an
    ``if <x>.startswith("sqlite")`` branch. Everything else is reported.
    """

    tree = ast.parse(source)
    sqlite_exempt = _sqlite_exempt_call_lines(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if fname not in _BUILDER_NAMES:
            continue
        if _spreads_connect_options(node):
            continue
        if _first_arg_is_sqlite_literal(node):
            continue
        if node.lineno in sqlite_exempt:
            continue
        lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "snippet",
    [
        "create_engine(database_url, future=True)",  # canonical positional
        "create_engine(url=database_url, future=True)",  # keyword form
        'create_engine(os.environ["DATABASE_URL"], future=True)',  # subscript
        "create_engine(config.database_url, future=True)",  # attribute
        "create_engine(dsn, future=True)",  # unconventionally-named variable
        'engine_from_config(section, prefix="sqlalchemy.")',  # alembic's builder API
    ],
    ids=["positional", "keyword", "subscript", "attribute", "odd-name", "engine_from_config"],
)
def test_guard_catches_every_unbounded_builder_idiom(snippet: str) -> None:
    """The guard flags an unbounded builder however its URL argument is written.

    An earlier version keyed on a bare ``ast.Name`` named url/database and missed
    the keyword/subscript/attribute/odd-name forms an adversarial review found.
    """

    assert _unbounded_create_engine_lines(snippet) == [1], (
        f"guard failed to flag an unbounded builder written as: {snippet}"
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "create_engine(database_url, **connect_options(database_url))",  # spread
        'create_engine("sqlite:///x.db")',  # sqlite literal
        'create_engine(f"sqlite:///{path}")',  # sqlite f-string
        'if url.startswith("sqlite"):\n    create_engine(url, future=True)',  # guarded
        'engine_from_config(section, prefix="sqlalchemy.", **connect_options(url))',  # bounded
    ],
    ids=[
        "spread",
        "sqlite-literal",
        "sqlite-fstring",
        "sqlite-guard",
        "engine_from_config-bounded",
    ],
)
def test_guard_exempts_the_provably_safe_forms(snippet: str) -> None:
    """The guard does not false-positive on a bounded or genuinely-sqlite builder."""

    assert _unbounded_create_engine_lines(snippet) == []


def test_guard_rejects_a_decoy_sqlite_guard() -> None:
    """A sqlite guard on a DIFFERENT variable does not exempt a real builder.

    The exact bypass an adversarial review constructed: an always-true / unrelated
    ``if decoy.startswith("sqlite")`` wrapper around ``create_engine(database_url)``.
    The branch runs for a real Postgres URL, so the builder must still be flagged.
    """

    decoy = (
        "def build(database_url):\n"
        '    decoy = "sqlite"\n'
        '    if decoy.startswith("sqlite"):\n'
        "        create_engine(database_url, future=True)\n"
    )
    # create_engine is on line 4 of the snippet.
    assert _unbounded_create_engine_lines(decoy) == [4]


def test_guard_exempts_a_genuine_sqlite_branch() -> None:
    """The real idiom -- guard and builder on the SAME variable -- stays exempt."""

    genuine = (
        "def build(database_url):\n"
        '    if database_url.startswith("sqlite"):\n'
        "        create_engine(database_url, future=True)\n"
    )
    assert _unbounded_create_engine_lines(genuine) == []


def test_no_unbounded_postgres_engine_builder() -> None:
    """No ``create_engine`` in civiccast/ builds a runtime DB engine unbounded.

    FAILS if any ``create_engine(...)`` call is not provably safe. The rule is
    default-suspect so it does not depend on recognising the URL argument's
    shape: a call is exempt ONLY if it spreads ``connect_options(...)``, its
    first argument is a hardcoded ``sqlite`` URL literal, or it sits inside an
    ``if <x>.startswith("sqlite")`` branch. Every other form -- a positional
    variable, ``url=``keyword, ``os.environ[...]`` subscript, ``config.x``
    attribute, or an oddly-named local -- is an offender.

    This is deliberately broader than "first arg named database_url": an earlier
    version keyed on a bare ``ast.Name`` whose id contained "url"/"database",
    and an adversarial review showed a seventh builder written with any of four
    ordinary idioms would slip past. This is the post-condition the incident's
    "unreachable Postgres fails fast" claim rests on, and a real regression
    guard against the next unbounded builder however it is written.
    """

    scanned = [
        (py, py.relative_to(_CIVICCAST_ROOT))
        for py in _CIVICCAST_ROOT.rglob("*.py")
        if py.relative_to(_CIVICCAST_ROOT) not in _ALLOWED_UNSPREAD
    ]
    scanned += [(extra, extra.relative_to(_REPO_ROOT)) for extra in _EXTRA_SCANNED_FILES]

    offenders: list[str] = []
    for py, rel in scanned:
        for lineno in _unbounded_create_engine_lines(py.read_text(encoding="utf-8")):
            offenders.append(f"{rel!s}:{lineno}")

    assert not offenders, (
        "these create_engine(...) calls may build a Postgres engine with no "
        "bounded connect timeout (add **connect_options(database_url), or if it "
        "is genuinely sqlite-only, guard it with startswith('sqlite')): " + ", ".join(offenders)
    )

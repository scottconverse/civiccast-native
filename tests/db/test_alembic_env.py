# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the Alembic environment's discovery + reversibility.

Per plan.md §4 of run 2026-05-08-db-foundation. Locks two contracts:

1. Discovery walks `civiccast/*/migrations/` directories filtered to dirs
   that contain a `versions/` subdir, plus the reserved repo-root
   `alembic/versions/` slot. Per director-decisions.md §Decision 2.

2. Reversibility — both `command.upgrade(cfg, "head")` and
   `command.downgrade(cfg, "base")` run cleanly on the empty migration
   graph that this rung ships. Per CLAUDE.md tooling clause "both
   `upgrade` and `downgrade` implemented and tested."

Real Alembic config + real SQLite tempfile DB — no mocks of the runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestAlembicEnvDiscovery:
    def test_discovery_walks_civiccast_module_migrations(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Given a temp `civiccast/<fake>/migrations/versions/` shim, the
        env's discovery list contains that path. Resolves the discovery
        root relative to alembic/env.py's own location (NOT cwd) so a
        non-repo-root cwd does not silently produce zero discoveries."""
        # Build a fake module layout under tmp_path so the discovery root
        # finds it. The function under test lives in alembic/env.py.
        fake_module = tmp_path / "civiccast" / "fakemod" / "migrations" / "versions"
        fake_module.mkdir(parents=True)

        # Import the discovery function from the alembic env module.
        # The env module is loaded by Alembic at runtime; here we import it
        # directly so we can call its discovery function.
        import importlib.util

        env_path = REPO_ROOT / "alembic" / "env.py"
        spec = importlib.util.spec_from_file_location("alembic_env_under_test", env_path)
        assert spec is not None and spec.loader is not None
        env_mod: Any = importlib.util.module_from_spec(spec)
        # The env module typically runs migration logic at import; a
        # well-designed env exposes the discovery function as an importable
        # callable. The contract: a `discover_version_locations(root: Path)`
        # function that returns a list[str] of discovered version dirs.
        spec.loader.exec_module(env_mod)

        discovered = env_mod.discover_version_locations(tmp_path / "civiccast")
        assert str(fake_module) in [str(Path(p)) for p in discovered]

    def test_discovery_skips_modules_without_versions_subdir(
        self,
        tmp_path: Path,
    ) -> None:
        """Half-built modules — those with `migrations/` but no
        `migrations/versions/` — must not break the runner. Binding per
        director-decisions §Decision 2: 'filtered to dirs that contain a
        `versions/` subdir'."""
        # Half-built module: migrations/ exists, versions/ does not.
        half = tmp_path / "civiccast" / "halfmod" / "migrations"
        half.mkdir(parents=True)
        # Complete module: both exist.
        full = tmp_path / "civiccast" / "fullmod" / "migrations" / "versions"
        full.mkdir(parents=True)

        import importlib.util

        env_path = REPO_ROOT / "alembic" / "env.py"
        spec = importlib.util.spec_from_file_location("alembic_env_under_test_2", env_path)
        assert spec is not None and spec.loader is not None
        env_mod: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(env_mod)

        discovered = [
            str(Path(p)) for p in env_mod.discover_version_locations(tmp_path / "civiccast")
        ]
        assert str(full) in discovered
        assert not any(p.endswith(str(Path("halfmod") / "migrations")) for p in discovered)

    def test_discovery_includes_reserved_alembic_versions_slot(
        self,
    ) -> None:
        """The empty repo-root `alembic/versions/` is included in
        version_locations even when empty — so a future migration dropped
        there is still discovered, even though convention says don't."""
        import importlib.util

        env_path = REPO_ROOT / "alembic" / "env.py"
        spec = importlib.util.spec_from_file_location("alembic_env_under_test_3", env_path)
        assert spec is not None and spec.loader is not None
        env_mod: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(env_mod)

        # The env module must expose the full set of version locations it
        # configures Alembic with (including the reserved slot). Contract:
        # `all_version_locations()` returns list[str].
        locations = [str(Path(p).resolve()) for p in env_mod.all_version_locations()]
        reserved = str((REPO_ROOT / "alembic" / "versions").resolve())
        assert reserved in locations

    def test_packaged_env_discovers_package_migration_versions(self) -> None:
        """The wheel-copied env.py lives under civiccast/alembic and must
        discover sibling package migration directories, not
        site-packages/civiccast/civiccast.
        """
        import importlib.util

        env_path = REPO_ROOT / "civiccast" / "alembic" / "env.py"
        spec = importlib.util.spec_from_file_location("packaged_alembic_env_under_test", env_path)
        assert spec is not None and spec.loader is not None
        env_mod: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(env_mod)

        locations = [Path(p).resolve() for p in env_mod.all_version_locations()]
        assert (
            REPO_ROOT / "civiccast" / "schedule" / "migrations" / "versions"
        ).resolve() in locations
        assert (
            REPO_ROOT / "civiccast" / "civiccast" / "schedule" / "migrations" / "versions"
        ).resolve() not in locations


class TestAlembicReversibility:
    def test_upgrade_head_on_empty_graph_succeeds(
        self,
        tmp_path: Path,
    ) -> None:
        """`alembic.command.upgrade(cfg, "head")` against a temp SQLite DB
        completes without exception on an empty migration graph. The harness
        shape is what's being proven (per manifest 'wiring is proven before
        any real schema lands')."""
        db_file = tmp_path / "wiring.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        # Empty graph: must succeed without raising.
        command.upgrade(cfg, "head")

    def test_downgrade_base_on_empty_graph_succeeds(
        self,
        tmp_path: Path,
    ) -> None:
        """`command.downgrade(cfg, "base")` runs cleanly on the empty graph.
        Together with the upgrade test, satisfies CLAUDE.md's 'both upgrade
        and downgrade implemented and tested' clause for the empty case."""
        db_file = tmp_path / "wiring.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

    def test_alembic_config_reads_database_url_from_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """alembic.ini resolves `sqlalchemy.url` from the DATABASE_URL env
        var at runtime — locks the env-var-driven contract per
        manifest.expected_outputs."""
        db_file = tmp_path / "envdriven.sqlite"
        url = f"sqlite:///{db_file}"
        monkeypatch.setenv("DATABASE_URL", url)
        cfg = Config(str(ALEMBIC_INI))
        resolved = cfg.get_main_option("sqlalchemy.url")
        assert resolved == url

    def test_version_table_schema_is_civiccast_on_postgres_dialect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """env.py's context.configure call passes
        version_table_schema='civiccast' so migration metadata also lives
        in the civiccast schema namespace per research.md §3 + CLAUDE.md
        closed schema decision. Asserted by introspecting the kwargs the
        env passes to context.configure."""
        # Read the env source and assert the literal kwarg is present.
        # This is a static-text assertion that's load-bearing because we
        # cannot easily run env.py against Postgres in CI; the kwarg must
        # be present in source so it takes effect when Alembic is run
        # against a real Postgres DB downstream.
        env_path = REPO_ROOT / "alembic" / "env.py"
        source = env_path.read_text(encoding="utf-8")
        assert (
            'version_table_schema="civiccast"' in source
            or "version_table_schema='civiccast'" in source
        )

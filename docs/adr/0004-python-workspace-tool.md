# ADR 0004 — Python workspace tool: uv

**Status:** Accepted
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** Day 0 bootstrap / 0.1 — Foundation
**Related spec section:** §5.2 Tooling, §8 Module catalog
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

CivicCast is a monorepo (per the closed repo-layout decision in CLAUDE.md) with ~19 Python modules under the `civiccast.*` namespace, each with its own dependencies, test suite, and Alembic migration directory. Two related concerns drive the workspace-tool decision:

1. **Workspace coordination.** The repo needs a tool that resolves dependencies across all member packages consistently, produces a single deterministic lock file, manages a shared development virtual environment, and handles the cross-module dependency graph (e.g., `civiccast-captions` depends on `civiccast.platform`).
2. **Developer ergonomics.** First-time setup must be fast — both for new contributors and for the autonomous coding agent that will spend hours per rung in the dependency-resolution / install / test loop. A tool that takes minutes per `pip install` adds up across thousands of iterations.

Three candidates were realistic:

- **uv** — Astral's Rust-based Python package manager and workspace tool, released 2024, rapidly adopted in the Python ecosystem during 2025.
- **hatch** — PyPA-affiliated, mature, the Python community's previous default for new monorepos.
- **Poetry** — Mature, broadly known, but its workspace support is non-PEP-standard and slower than the alternatives.

## Decision

**CivicCast uses uv as its Python workspace tool.** Workspace members are declared in the root `pyproject.toml`'s `[tool.uv.workspace]` section. Development dependencies are declared in `[tool.uv]` `dev-dependencies`. The lock file is `uv.lock` at the repo root, committed alongside `pyproject.toml`. CI runs `uv sync --frozen` to install from the locked manifest.

## Alternatives considered

**Option A — uv.** Rust-based, dramatically faster than pip / Poetry / hatch (10-100x on typical operations). PEP 621 / PEP 660 compliant. First-class workspace support: `[tool.uv.workspace]` declares member packages; cross-package dependency resolution is automatic. Single tool covers virtual environment creation, dependency installation, lock file management, and Python-version pinning. Active upstream (Astral, also the maintainers of ruff). Cross-platform: Linux, macOS, Windows. This was selected.

**Option B — hatch.** PyPA-affiliated, mature, and the Python community's previous default for new monorepos. Standardized environment management via `[tool.hatch.envs.*]`. Rejected because (a) hatch's environment model is a non-standard layer above standard Python venvs, which adds a concept boundary contributors must learn, and (b) hatch is slower than uv on the dependency resolution and install paths that dominate the autonomous agent's loop. The workspace coordination story is also less mature than uv's; cross-package dependency edits require more boilerplate.

**Option C — Poetry.** Mature, broadly known. Rejected because Poetry's workspace / monorepo story is non-PEP-standard (`pyproject.toml` extensions that don't follow PEP 621) and Poetry's dependency resolver is the slowest of the three. The primary advantage — "everyone already knows it" — is offset by uv's documentation quality and its design's similarity to standard `pip` / venv workflows for newcomers.

**Option D — pip + venv with manual coordination.** Rejected as primary because there's no canonical workspace coordination layer; each module's environment management would need bespoke scripts. uv (or hatch) provides a real workspace primitive that pip + venv do not.

## Consequences

### Positive

- **Speed compounds across the agent's loop.** uv's order-of-magnitude faster install means thousands of iterations across the release ladder finish in materially less wall-clock time and consume less CI compute.
- **Single tool replaces five.** uv covers what would otherwise be `pip`, `pip-tools`, `virtualenv`, `pyenv`, and a workspace coordination layer. Less to install on developer machines; less to verify in `civiccast doctor`.
- **PEP-compliant `pyproject.toml`.** Standard fields (`[project]`, `[build-system]`) work as documented; uv-specific configuration lives under `[tool.uv]`. No fork or quasi-fork of the manifest format.
- **Pairs naturally with ruff.** ruff is also from Astral; both tools share a Rust core and similar performance posture. Toolchain coherence.
- **Cross-platform parity.** uv works identically on Windows (the development host per ADR 0003), Linux (deployment), macOS (secondary target), and inside WSL2.
- **Lock file determinism.** `uv.lock` is content-addressable and reproducible; CI runs `uv sync --frozen` so dependency drift is impossible without an explicit lock-file update.

### Negative

- **Newer than the alternatives.** uv hit 1.0 in 2024 and matured rapidly through 2025. The "everyone knows Poetry" appeal is real for some contributors. Mitigation: the CONTRIBUTING.md walkthrough covers the uv-specific commands a contributor needs (`uv sync`, `uv add`, `uv run`).
- **Single-vendor dependency on Astral.** uv and ruff both come from the same maintainer. If Astral pivots or slows, both tools are affected at once. Mitigation: uv is permissively licensed (Apache 2.0 / MIT), the codebase is OSS, and the community could fork. The lock-in is bounded.

### Risks

- **Format drift between uv versions.** uv's manifest extensions (`[tool.uv.workspace]`, `[tool.uv]`) could change between minor releases. Mitigation: pin uv version in CI; bump on a deliberate cadence with a CHANGELOG entry.
- **Build-backend interaction.** uv handles installation; the build backend (`hatchling` per `pyproject.toml`) handles wheel creation. The combination works today; future uv changes to its build-isolation model could affect this. Mitigation: the integration is exercised on every CI run.

## Compliance

- The root `pyproject.toml` is the canonical workspace manifest. Every member module under `[tool.uv.workspace] members` exists as a directory with its own `pyproject.toml`.
- `uv.lock` is committed and updated by `uv lock` after any dependency change. CI runs `uv sync --frozen`; a stale lock file fails the lint job.
- `civiccast doctor` (Sprint 0.1) reports the detected uv version and verifies the workspace can be synced.
- The pre-commit hook config (`.pre-commit-config.yaml`) does not depend on uv being installed globally — pre-commit manages its own environments — but contributors run pre-commit via `uv run pre-commit ...` to avoid version drift.

## References

- CivicCastUnifiedSpec-v2.md §5.2 Tooling
- CivicCast-ReleasePlan-0.1-to-1.0.md — rung 0.1 Foundation scope
- [uv documentation](https://docs.astral.sh/uv/)
- [uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)
- [PEP 621 — pyproject.toml project metadata](https://peps.python.org/pep-0621/)
- ADR 0003 — Project development hardware and primary deployment OS target

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*

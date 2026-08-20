# ADR 0005 — Sprint 0.1 framework stack: Typer, nvidia-ml-py, Pandoc

**Status:** Accepted
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** 0.1 — Foundation
**Related spec section:** §5.1 Backend stack, §5.4 API conventions, §7.7 Hardware tier decision tree, §8.1 civiccast (umbrella & shell), §8.20 civiccast-docs
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

Spec §5.1 already names FastAPI + Uvicorn for the HTTP surface and psutil for hardware probing. ADR 0001 covers NATS JetStream; ADR 0002 covers the Whisper runtime; ADR 0004 covers uv as the workspace tool. Three implementation choices remain unspecified that Sprint 0.1 needs to make before code lands:

1. **CLI framework** for the `civiccast` command line. Spec §8.1 enumerates the CLI's eventual subcommands (`doctor`, `model download`, `backup`, `restore`, `schedule diff`, `soak run`, `syndicate test`, `archive verify`, `subscribe send-test`) and notes "operators rarely use the CLI; integrators and automation pipelines use it heavily." That implies typed subcommands, predictable exit codes, machine-friendly output modes, and rich help. Two realistic candidates: Typer and Click.

2. **GPU/VRAM probe library.** psutil handles CPU/RAM/disk but does not probe GPU. The Tier 1 reference build (§10.2) and ADR 0003's PowerSpec G730 both use NVIDIA hardware; the tier decision tree in §7.7 keys on VRAM ≥ 8GB / ≥ 16GB / ≥ 24GB thresholds, so VRAM detection is required. NVIDIA's official Python binding is `nvidia-ml-py` (imports as `pynvml`); third-party alternatives (`gpustat`, `GPUtil`) wrap nvidia-smi or NVML but add layers of indirection.

3. **Pandoc setup** for the USER-MANUAL.md → PDF/DOCX rendering pipeline. The Day 0 plan flagged this as a Sprint 0.1 deliverable. Pandoc's version, the LaTeX engine choice (xelatex vs pdflatex), and the manual stylesheet need a documented baseline so CI and operator-run renders produce identical output.

These three decisions are tactical and tightly scoped to Sprint 0.1's scope; bundling them into one ADR rather than three keeps the ADR overhead proportional to the work. If any of them later proves load-bearing enough to warrant its own decision history, the scoped ADR can be extracted by a superseding ADR for that one item.

## Decision

CivicCast Sprint 0.1 adopts:

1. **Typer** as the CLI framework. The umbrella package's `civiccast` entry point is a Typer app; subcommands are added incrementally as rungs deliver them.
2. **`nvidia-ml-py`** (importing as `pynvml`) as the GPU/VRAM probe library, accessed only through `civiccast.platform.hardware`. Non-NVIDIA hardware degrades gracefully to "no GPU detected" rather than failing the probe.
3. **Pandoc 3.1+ with xelatex** as the documentation renderer. The CI image installs `pandoc`, `texlive-latex-base`, `texlive-fonts-recommended`, `texlive-latex-recommended`, `texlive-latex-extra`, `texlive-xetex`, and `texlive-fonts-extra`. The renderer entry point is `scripts/render-user-manual.sh` which produces both `USER-MANUAL.pdf` and `USER-MANUAL.docx` from `docs/USER-MANUAL.md`.

## Alternatives considered

### CLI framework

**Option A — Typer.** Typer is built on top of Click by Sebastián Ramírez (the maintainer of FastAPI). Subcommands and arguments are declared via Python type hints, matching CivicCast's `mypy --strict` posture. Excellent generated help, shell completion, and rich-text output. Used in many modern Python CLIs. **Selected.**

**Option B — Click.** The mature, widely-used standard underlying many Python CLIs (including pip and poetry). Decorator-based argument declarations. Rejected because (a) Click's decorator API does not lean on type hints — it requires a parallel set of decorators for each argument's type, which adds boilerplate that mypy doesn't help with; (b) Typer wraps Click and keeps Click's escape hatches available where the typed API is too constraining, so we get the maturity of Click underneath without losing it.

**Option C — argparse / standard library.** Zero dependencies. Rejected for ergonomics: argparse subcommands and rich help are workable but verbose, and the CLI surface in §8.1 is already large enough that argparse's overhead would exceed any "fewer dependencies" benefit.

### GPU / VRAM probe library

**Option A — `nvidia-ml-py` (NVIDIA's official binding).** Maintained directly by NVIDIA. Wraps NVML (the NVIDIA Management Library) without an intermediate process call. Returns structured data (handle, memory info, utilization, name) directly. PyPI name `nvidia-ml-py`; import name `pynvml`. **Selected.**

**Option B — `gpustat` / `GPUtil`.** Both wrap `nvidia-smi` invocations and parse the text output. Rejected because (a) shelling out to `nvidia-smi` is slower and less reliable than NVML directly, especially in containerized or WSL2 environments where the binary path may differ; (b) text-output parsing breaks across nvidia-smi version changes; (c) nvidia-ml-py is NVIDIA's canonical Python binding — using a wrapper around the CLI tool is the wrong layer.

**Option C — Roll our own NVML wrapper via ctypes.** Rejected as unjustified work — nvidia-ml-py is already the wrapper.

**Option D — Skip GPU detection in Sprint 0.1.** Rejected: spec §7.7 (hardware tier decision tree) keys on GPU presence and VRAM thresholds. The doctor CLI and the installer's tier recommendation both need GPU/VRAM data starting from Sprint 0.1's `civiccast doctor`.

### Documentation renderer

**Option A — Pandoc with xelatex.** Pandoc converts Markdown to PDF and DOCX from the same source. xelatex (vs pdflatex) handles modern font selection and Unicode cleanly, which matters for CivicCast's eventual multilingual documentation work. Pandoc is what CLAUDE.md's tooling section already names. **Selected.**

**Option B — MkDocs Material → PDF plugin.** MkDocs Material is already named in CLAUDE.md as the docs-site renderer. Its `mkdocs-pdf-export-plugin` could produce the PDF as well. Rejected because (a) the docs site and the user manual are different artifacts with different audiences (operator-facing reference vs operator-facing handbook); (b) the user manual is required to render via Pandoc per the Day 0 plan and per §4.4 documentation non-negotiables; (c) MkDocs Material's PDF output is acceptable but Pandoc's typographic control is better for the printed-handbook use case.

**Option C — wkhtmltopdf or weasyprint.** Pure-CSS HTML → PDF approach. Rejected for typographic quality and Unicode handling on community-org hardware where xelatex still produces better output for prose-heavy documents.

## Consequences

### Positive

- Typer's typed-API matches mypy strict and FastAPI's typed Pydantic models — the CLI and the API can share data types via a single Pydantic model module without translation.
- nvidia-ml-py as the canonical GPU probe means `civiccast doctor` and the Sprint 0.1 `/api/hardware` endpoint return identical data structures from the same code path, no shell-out latency.
- Pandoc + xelatex matches the CivicCast audience's eventual multilingual documentation needs (school boards in bilingual districts, HOAs in dual-language communities) without retooling.
- All three picks are well-supported, broadly used, and have low maintenance risk.

### Negative

- Typer adds Click as a transitive dependency (already a transitive dependency of pip and many other tools — no realistic operational overhead).
- nvidia-ml-py is a ~5MB Python wheel that vendors NVML headers; this is fine on Linux/WSL2 with NVIDIA hardware, gracefully no-ops on AMD/Intel GPUs and Apple Silicon (no NVIDIA driver, returns "no GPU detected"). Does not support AMD ROCm or Apple Metal — those operators will see GPU=none even with capable hardware. This is consistent with ADR 0003's NVIDIA-first reference platform; AMD/Apple GPU probing is post-1.0 work.
- Pandoc + texlive is a heavy CI dependency (~500MB install). The `ci-docs` workflow already pays this cost; no additional CI surface.

### Risks

- **nvidia-ml-py initialization on WSL2 without NVIDIA driver passthrough.** If a WSL2 environment lacks the Windows NVIDIA driver, NVML init raises. Mitigation: `civiccast.platform.hardware` catches NVML errors and reports GPU=none rather than crashing the probe. The doctor CLI's output makes the no-GPU fallback explicit so operators understand they're seeing a degraded probe.
- **Typer major version bumps.** Typer 0.x is stable enough that we are accepting it; the `>=0.12` floor pins the modern decorator API. A future Typer 1.0 may break compatibility. Mitigation: pin Typer in `pyproject.toml`'s direct dependencies; bump deliberately.
- **Pandoc / xelatex font fallback.** xelatex needs fonts present on the system. Mitigation: `texlive-fonts-recommended` + `texlive-fonts-extra` in CI cover the default font stack; the user manual's stylesheet uses a small, deliberate font palette to avoid edge cases.

## Compliance

- The umbrella package declares Typer, FastAPI, Uvicorn, psutil, and nvidia-ml-py as direct dependencies in `pyproject.toml`'s `[project.dependencies]`. Lock file commits the resolved tree.
- `civiccast.platform.hardware` is the only module that imports `pynvml`. Lint rule (Sprint 0.1 or 0.2) flags direct `pynvml` imports anywhere else.
- The `civiccast` CLI's entry point is `civiccast.cli:app` declared in `[project.scripts]`. New subcommands are added by registering Typer sub-apps under the umbrella app.
- The Pandoc render baseline lives in `scripts/render-user-manual.sh`; CI runs the same script to keep CI and operator-run renders byte-identical. The script is referenced from `ci-docs.yml` once `USER-MANUAL.md` lands in this rung.

## References

- CivicCastUnifiedSpec-v2.md §5.1 Backend stack
- CivicCastUnifiedSpec-v2.md §5.4 API conventions
- CivicCastUnifiedSpec-v2.md §7.7 Hardware tier decision tree
- CivicCastUnifiedSpec-v2.md §8.1 civiccast (umbrella & shell)
- CivicCastUnifiedSpec-v2.md §8.20 civiccast-docs
- [Typer documentation](https://typer.tiangolo.com/)
- [nvidia-ml-py on PyPI](https://pypi.org/project/nvidia-ml-py/)
- [Pandoc User's Guide](https://pandoc.org/MANUAL.html)
- ADR 0003 — Project development hardware and primary deployment OS target
- ADR 0004 — Python workspace tool: uv

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*

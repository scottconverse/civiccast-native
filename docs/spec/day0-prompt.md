# Day 0 Bootstrap Prompt for Claude Code (Cowork)

> Paste the section below into Claude Code. The prompt assumes you've moved or symlinked the four canonical docs (`CLAUDE.md`, `CivicCastUnifiedSpec-v2.md`, `CivicCast-ReleasePlan-0.1-to-1.0.md`, and the four template files) into the working directory you launch Claude Code from, OR that you've given Claude Code their absolute paths in the workspace folder `C:\Users\scott\OneDrive\Desktop\Claude\CivicCast\`.

---

## The prompt

You are working on CivicCast, an open-source civic broadcast platform. We have not started any code yet. Today's job is **Day 0 bootstrap** — everything that has to happen before Sprint 0.1 can begin. You will not write production code today. You will set up the project infrastructure, validate prerequisites, walk me through two real-world decisions, and stop at the door of Sprint 0.1.

### Read these first, in this order

The four canonical project docs live at `C:\Users\scott\OneDrive\Desktop\Claude\CivicCast\` (Windows) or wherever I've placed them in your working directory. Read them in this order, end-to-end:

1. **`CLAUDE.md`** — project orientation. Closed architectural decisions, layered audit pattern, role posture, what you never do.
2. **`CivicCastUnifiedSpec-v2.md`** — the canonical product spec. Skim end-to-end; deep-read §1–§4, §8, §10, §17.2, §17.3, §22.
3. **`CivicCast-ReleasePlan-0.1-to-1.0.md`** — the release ladder. Deep-read the 0.1 rung, "Architecture decisions baked in," "Calibration gates," and "What to do right now (Sprint 0.1, day 1)."
4. **The four templates** — `CivicCast-CarefulCoding-Template.md`, `CivicCast-Checkpoint-Template.md`, `CivicCast-VerificationLog-Template.md`, `CivicCast-ADR-Template.md`. Skim — you will use these as the working artifacts.

After reading, summarize back to me in 5–8 sentences: what is CivicCast, what does Sprint 0.1 deliver, what's the layered audit pattern, what are the closed architectural decisions. If your summary contains anything that contradicts the docs, stop and ask before proceeding.

### Day 0 plan (do these in order)

#### Phase 1 — Name availability and trademark check (~15 min)

Before we commit to "CivicCast" as the project name on GitHub, the domain, and the eventual trademark, verify it's actually available. Use web search (you have WebSearch / WebFetch). Check:

- **USPTO TESS** at `https://tmsearch.uspto.gov/` — search for the literal string "CivicCast" across active and dead trademarks. Also check related stems: "CivicCast Network", "CivicCast Foundation", and the obvious near-misses. Surface any registrations or pending applications you find.
- **GitHub org name** — check whether `https://github.com/CivicCast` is available as an org (it should 404 if available, or show an existing org if taken).
- **Domain availability** — check `civiccast.org`, `civiccast.com`, `civiccast.net`, `civiccast.io`. WHOIS lookup or any registrar's availability check is fine.
- **PyPI namespace** — `https://pypi.org/project/civiccast/` and `https://pypi.org/project/civiccast-stream/` and one or two other module names from the spec's §8 module catalog. 404 = available.
- **npm namespace** — `https://www.npmjs.com/package/@civiccast/design-tokens` and similar.
- **Quick Google search** for "CivicCast" to surface any existing civic-tech project, podcast, product, or startup using the name in context that wouldn't show up in a registry.

Produce a short report:

- "CivicCast" name is: **clear** / **partially clear (specifics)** / **conflicted (specifics)**
- Recommended next step: proceed with "CivicCast" / proceed with caveats / consider an alternative name

If the name is conflicted, propose 3–5 alternative names that fit the project's positioning (open-source, civic broadcast, public-good infrastructure) and let me pick. Do not silently change the project name in any of the canonical docs without my explicit go-ahead.

#### Phase 2 — Development hardware decision (~10 min)

Walk me through the dev-and-test hardware decision. We discussed this previously; the options are:

- **Stay on the current Beelink (Windows 11, Ryzen 7 5800H, 32GB, integrated AMD Radeon).** Works for Sprints 0.1–0.4 via WSL2; fails at 0.5 onward (no NVIDIA GPU, AMD iGPU not supported by ROCm production path). Free.
- **16GB base M4 Mac mini (~$599–$799).** Workable through 0.10. Memory ceiling tight for AI workloads; below the spec's documented Apple Silicon floor (M4 Pro 48GB). 1.0 validation needs a separate machine.
- **24GB M4 Pro Mac mini (~$1,399).** Comfortably above AI working set; M4 Pro's 273GB/s memory bandwidth handles Whisper + Gemma cleanly. Just below the spec's 48GB floor — small footnote-update issue.
- **Linux build per spec (~$2,520).** Ryzen 7 7700, RTX 4060 8GB, ECC RAM, ZFS storage. The canonical reference target. Two-week parts-sourcing lead time.
- **Cloud GPU for AI rungs only (~$0.30–$0.50/hr).** Develop locally on whatever, rent an RTX 4090 on RunPod / Lambda for the AI rungs. ~$200–$400 total through 1.0.

Ask me which option I'm picking. Once I've picked, draft **ADR 0003 — Project development and validation hardware** at `docs/adr/0003-project-hardware.md` capturing the decision, the rejected alternatives, and the implications for which rungs need what hardware. Do not commit it yet — hold for the repo-init step.

#### Phase 3 — Local environment readiness check (~10 min)

Before creating the repo, verify the dev environment has what Sprint 0.1 needs. Run these checks and report what's installed and what's missing:

- `git --version` (need 2.40+ for sane defaults)
- `gh --version` (GitHub CLI; we'll use it to create the repo if authenticated)
- `gh auth status` (is `gh` authenticated to my GitHub personal account?)
- `python --version` (need 3.12+)
- `node --version` (need 20+ for the frontend toolchain)
- `nats-server --version` (NATS, per ADR 0001)
- `docker --version` (for testcontainers and the eventual container image)
- `pandoc --version` (for USER-MANUAL PDF/DOCX render — Sprint 0.1 ADR will pin the version)
- A working PostgreSQL 17 install reachable on `localhost:5432` (or a Docker container ready to run one)
- `ffmpeg -version` (used by `civiccast-stream` from rung 0.2)

For anything missing, give me the install command for my OS (Windows + WSL2; I'm in Ubuntu 24.04 inside WSL2 unless I tell you otherwise). Do not install anything yourself without asking — I'll run installs after you list them.

#### Phase 4 — Repo initialization (~20 min)

Once name check, hardware decision, and environment are clear, create the local repo:

1. **Pick a parent directory** with me — recommend `~/Code/civiccast` if `~/Code` exists, else ask. Do not silently put it somewhere unexpected.
2. **`git init`** the new directory. Create the monorepo structure per CLAUDE.md's repo-layout decision: top-level subdirs for each module the spec's §8 names (`civiccast/stream/`, `civiccast/captions/`, `civiccast/archive/`, etc.) as Python namespace packages. Plus `docs/` (with `adr/`, `templates/`, `releases/`, `spec/`), `tests/`, `scripts/`, `.github/` (with `workflows/`, issue and PR templates).
3. **Move (copy in) the four canonical docs** to their permanent locations:
   - `CLAUDE.md` → repo root
   - `CivicCastUnifiedSpec-v2.md` → `docs/spec/spec.md`
   - `CivicCast-ReleasePlan-0.1-to-1.0.md` → `docs/spec/release-plan.md`
   - `CivicCast-CarefulCoding-Template.md` → `docs/templates/careful-coding.md`
   - `CivicCast-Checkpoint-Template.md` → `docs/templates/checkpoint.md`
   - `CivicCast-VerificationLog-Template.md` → `docs/templates/verification-log.md`
   - `CivicCast-ADR-Template.md` → `docs/adr/0000-template.md`
   - The proposed ADR 0003 (hardware) → `docs/adr/0003-project-hardware.md` (after I approve it)
4. **Author the spec-required documentation artifacts** (per spec §4.4): `README.md` (skeleton with project pitch + pointers to spec/release plan/CLAUDE.md), `CHANGELOG.md` (Keep a Changelog format, currently empty), `CONTRIBUTING.md` (DCO sign-off requirement, Conventional Commits, link to release plan for what to work on), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md` (private disclosure to my email until a security WG exists), `SUPPORT.md` (pointer to issue tracker), `LICENSE` (Apache 2.0), `LICENSE-CODE` (Apache 2.0 again, for clarity), `LICENSE-DOCS` (CC BY 4.0).
5. **`.gitignore`** for Python + Node + macOS + Windows + Linux + IDE + secrets.
6. **`pyproject.toml`** at root with workspace tool (recommend `uv` workspaces or `hatch` — pick one and ADR-record it as ADR 0004, or surface the pick to me first), ruff config, mypy strict config, pytest config.
7. **`.pre-commit-config.yaml`** with ruff, ruff-format, mypy, trailing-whitespace, end-of-file-fixer, conventional-commit-message check.
8. **`.github/workflows/`**:
   - `ci-lint.yml` — ruff + mypy on every PR
   - `ci-test.yml` — pytest scaffolding (placeholder; full suite as modules land)
   - `ci-a11y.yml` — axe-core/playwright placeholder for the public portal (kicks in at rung 0.2)
   - `ci-docs.yml` — Pandoc PDF/DOCX render check on USER-MANUAL.md (placeholder until USER-MANUAL exists)
9. **GitHub issue templates**: bug report, feature request, security report, RFC.
10. **GitHub PR template**: Conventional Commit verification, DCO sign-off check, verification log section pointer.
11. **Initial commit** with message `chore: initial bootstrap of CivicCast repo` and DCO sign-off (`Signed-off-by: Scott Converse <sconverse@gmail.com>`). Run the per-commit careful-coding loop on this commit (yes, even bootstrap — set the discipline from commit zero).

#### Phase 5 — GitHub setup (~10 min)

For now: my personal GitHub account, private repo. We'll move to a public `CivicCast` org at or near 1.0 release.

1. Confirm `gh auth status` showed authenticated. If not, walk me through `gh auth login`.
2. Create the private repo: `gh repo create civiccast --private --source=. --description "CivicCast — open-source civic broadcast platform (private development phase)" --remote=origin`
3. Push the initial commit: `git push -u origin main`
4. Verify the repo on GitHub by opening the URL: `gh repo view --web`
5. Set up branch protection on `main`: require PR reviews, require CI passing, no direct pushes. Use `gh api` calls if needed; surface the JSON to me before applying.

If `gh` is not authenticated or fails, give me the equivalent web-UI steps and pause.

#### Phase 6 — ADR 0001 and ADR 0002 first drafts (~15 min)

These are the resolved-decisions ADRs that the release plan calls for in Sprint 0.1, day 1. Drafting them now (Day 0) means Sprint 0.1 can begin clean.

1. **ADR 0001 — Messaging substrate: NATS JetStream** at `docs/adr/0001-messaging-substrate.md`. Use the ADR template at `docs/adr/0000-template.md`. Pull the rationale from the release plan's "Architecture decisions baked in" section and from the spec's §5.1. Status: Accepted. Date: today. Reference release plan and spec §22.
2. **ADR 0002 — Canonical Whisper runtime: faster-whisper** at `docs/adr/0002-whisper-runtime.md`. Same shape, rationale from release plan and spec §11.2.

Show both ADRs to me before committing. Once I approve, commit them as `docs(adr): record ADRs 0001 and 0002 (NATS JetStream, faster-whisper)` with DCO sign-off.

#### Phase 7 — Day 0 verification log

Treat Day 0 itself as a "rung 0.0" worth a brief verification log. Use the per-rung template at `docs/templates/verification-log.md`. Four lenses:

- **Engineering** — repo structure matches CLAUDE.md decisions; ADRs 0001/0002/0003 land cleanly; license files correct.
- **Tests** — CI workflows are scaffolded but green (running on placeholder content); pre-commit hooks installed and tested locally on the bootstrap commit.
- **Docs** — README, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, SUPPORT, LICENSE files all present and correct; spec/release plan/CLAUDE.md/templates moved to permanent locations.
- **Runtime** — `gh repo view` shows the private repo on my GitHub account; `git log` shows two commits (bootstrap + ADRs); `pre-commit run --all-files` passes.

Commit the verification log to `docs/releases/v0.0.0-day0-verification.md`. Tag `v0.0.0-day0` if everything is clean.

### What you must not do today

- Do not start any Sprint 0.1 work. The hardware probe (`/api/hardware`), the `civiccast doctor` CLI, the umbrella shell — none of that is Day 0. That's Sprint 0.1 day 1, after we both confirm Day 0 is clean.
- Do not silently change the project name. If trademark or availability checks raise concerns, surface them and let me decide.
- Do not silently pick hardware. Walk me through it; capture in ADR 0003 only after I confirm.
- Do not commit secrets. The OS credential store discipline (CLAUDE.md / spec §15.3) starts now — no API keys, no tokens, nothing sensitive in the repo.
- Do not skip any of the per-commit careful-coding steps even on bootstrap commits. The discipline starts at commit zero. The bootstrap commits are unusually small but they still get the 9-step loop and a Conventional Commit + DCO sign-off message.
- Do not ask me to install or configure anything you can verify or do yourself with my pre-existing permissions. Conversely, do not assume permission for anything that touches my GitHub account, my filesystem outside `~/Code/`, or my package managers — ask first.

### Where to stop

After Phase 7 is complete, stop and report:

- Repo URL on GitHub.
- Local path of the repo on my machine.
- Day 0 verification log link.
- Tag name (`v0.0.0-day0`).
- Any items deferred to a `next-cleanup.md` file (if any).
- Confirmation of the closed architectural decisions (D3 NATS, D4 faster-whisper, plus the ADR-0003 hardware decision).
- Explicit handoff: "Day 0 complete. Ready for Sprint 0.1 — Foundation, per the release plan rung 0.1 scope."

I will then either green-light Sprint 0.1 or call out anything from Day 0 that needs adjusting first.

### One more thing

You are operating as Principal Software Engineer + Senior UI/UX Designer + Senior QA Engineer simultaneously, per the role posture in CLAUDE.md. The bootstrap is small but it sets the tone for everything that follows. If anything looks wrong or unclear, push back before doing it. Better to ask twice on Day 0 than to have a discipline regression on day one of Sprint 0.1.

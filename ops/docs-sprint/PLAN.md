# Documentation sprint plan (started 2026-10-03; owner: Scott; writer: Claude, docs only, no code)

Scott's directions (2026-10-02): publish docs as plain files straight to `main` **in stages** (no PR, no CI, no LFS, nothing in the
installer or beta.10 release). Manual = non-technical section + technical section for a small-city IT team, professional formatting,
Mermaid/architecture diagrams, complete appendix, downloadable PDF/DOCX. Landing page rebuilt with the landing-page skill using the
owner's brand kit (`docs/brand/`). In-app help is written as **files for the incoming coder** (`docs/in-app-help/`); Claude writes no code.
Screenshots: use the lab station's own mock data (no blurring needed).

## Stages (each ends with a push to `main` and a short report)
0. Brand kit committed (`docs/brand/`) — **done** (main 0edb02e2).
1. Inventory (this folder): per-screen inventories, deterministic API/CLI/env/ports/files tables, claims register.
2. Screenshots from the lab station (operator console, resident portal, installer if capturable).
3. Manual drafts by section, each verified against the inventories and the code.
4. Diagrams (Mermaid source + rendered images), appendix, build PDF/DOCX, page through the layout.
5. Landing page + visitor audit of every published page and link.
6. In-app help files (`docs/in-app-help/`) + mismatch list for the coder.

## Truth rules
Every factual sentence in the manual must trace to code, a running check, or a cited evidence file. Claims about what has/hasn't been proven
use the exact beta.10 wording in `docs/releases/v1.0.0-beta.10-verification.md`. The measured-evidence section cites the oversight log.

## Status
(see the bottom of this file; updated at each stage push)

### 2026-10-03 — Stage 1 (inventory) complete
- 63 per-screen/surface inventories in `inventory/screens/` (operator console 7 sections + shell + roles, resident portal, installer, install layout), written read-only from the code with `file:line` evidence; 473 Help-text/behavior findings consolidated in `inventory/FINDINGS-INDEX.md` (390 `UNVERIFIED` marks are explicit "could not confirm" notes, not claims).
- Generated tables in `inventory/generated/`: `cli.md` (42 commands, from the Typer app), `api.md` (488 operations / 405 paths, from the FastAPI app), `env-vars.md` (412 names; 17 use the one-C `CIVICAST_` spelling). Generators in `tools/` rerun against any commit.
- Coordinator spot-checked six of the most serious findings directly against the code (autoschedule items born `published`; summary Approve payload vs `extra="forbid"` model; paywall blank-secret save; facility sample endpoint 192.0.2.10; installer MA-17 download-only limitation; installer exit-code behavior): all six confirmed.
- Not yet verified on a running station: anything marked `UNVERIFIED` (the screenshot stage will resolve many).
- Next: Stage 2 screenshots from the lab station; Stage 3 manual drafting.

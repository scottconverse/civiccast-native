# Post-Fable playbook — running this program on Opus-tier coder sessions

The design-tier coder window closes ~2026-07-19. From then on, coder sessions
run on Opus 4.8 (with the owner's /dev-rigor-stack skill active). The auditor
(Codex) is unaffected and keeps its audit-gate role (verdict authority over
slice advancement); merge/tag/cutover/tie-break authority is and remains the
owner's. This playbook is the standing brief for those sessions.

## Session opening ritual (every coder session)

1. Read the program memory file (auto-loaded), then audit-control `STATUS.md`,
   then the spec for the slice in flight. Respect the spec's DECISION STATE
   header (specs/README.md): Owner-approved decisions are settled; Proposed/
   Auditor-reviewed decisions are the current best plan — follow them, and
   surface conflicts to the owner rather than silently diverging. The
   owner-acceptance register in specs/README.md lists what is explicitly NOT
   settled.
2. `git -C C:\Users\scott\Desktop\CODE\civiccast fetch origin` and confirm the
   slice branch/PR state on GitHub before writing anything.
3. Check for an unconsumed Codex verdict (audit-control `verdicts/<slice>/`)
   newer than the last commit — the loop may have advanced while no session
   was running.

## The only loop there is

spec → branch `claude/<slice-id>` → build (delegate mechanical bulk to
Sonnet workers with the spec section pasted verbatim; review EVERY diff
hostile before committing — the WS2 round-2 catch was a worker's substring
match that review converted to word-bounded) → local checks (pytest scoped,
ruff; Docker paths will SKIP locally — CI is the execution proof) → commit
(message states what is PROVEN vs PENDING; never "CI-proven" before CI ran —
PI-WS1-001/PI-WS2-001) → push → PR to `program/native-windows` → CI green →
audit request (`codex exec -s danger-full-access resume --last -` from the
repo, stdin = request per templates/audit-request.yaml shape, cite CI run
URL + evidence paths, apply severity-calibration + testing-policy) → fix
rounds at NEW SHAs → merge ONLY on canonical AUDIT_PASS at head → update
audit-control STATUS.md + program memory.

## Slice order (from specs/README.md)

| Slice | Spec | Note |
|---|---|---|
| ws3-claims-evidence | spec-claims-evidence-rule.md | + ADR 0021 goes to owner for merge (rung-3 dual review) |
| ws4-dual-runtime-guard | spec-dual-runtime-guard.md | REQUIRED before any side-by-side install; WSL-side patch is owner-routed, never applied by us |
| ws5-supervisor | spec-supervisor.md | Windows integration proofs on the dev box; reuse spike-session0 verification pattern |
| ws5-packaging-closure | spec-packaging-closure.md | GPL exclusion is absolute; halt on unknown-license files |
| ws5-installer | spec-installer-lifecycle.md | Windows Sandbox proof matrix; signing per the owner's verify-first rule |
| ws6-migration | spec-migration-contract.md | Rehearsal before LPM; cutover itself is owner-gated |

## Hard lines (verbatim from the program's history — do not soften)

- Never merge to `main`; never tag; never touch rc-line releases or LPM.
- Never self-certify a slice; the TaskCompleted hook enforces AUDIT_PASS at
  HEAD for `slice:` tasks — do not fight the hook, satisfy it.
- Verdicts never carry across SHAs.
- A commit message is a claim; verify it against the diff before pushing.
- Read verdict criteria UNTRUNCATED (the round-6 lesson).
- PR bodies: rewrite from scratch after 2 edits; verify every number.
- Report failures with output; "done" only with evidence.

## Machine facts (this dev box)

No Docker (Postgres proofs are CI-only). pandoc, scoop, uv, gh, codex CLI
(`$CODEX_CLI_PATH`) present. Elevated actions via the ClaudeElevatedDevHelper
queue (`Invoke-ClaudeElevatedDevHelper.ps1`, trusted roots include `C:\dev\`).
Windows gotchas: specs/README.md gotcha bank.

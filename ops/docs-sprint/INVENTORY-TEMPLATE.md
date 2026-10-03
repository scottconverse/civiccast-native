# Screen inventory template (documentation sprint, 2026-10-03)

One file per screen or surface, written by a read-only worker. These inventories are the *source of truth* for the
user manual and for the in-app help files. They are built from the code, not from the old manual.

## Rules for the worker
1. **Read-only on the product.** Do not edit any file outside your own output files. Do not run the station, restart services,
   or touch `C:\ProgramData\CivicCast\data\egress\live-hls\`.
2. **Every statement must come from code you read.** Cite `path:line`. If you cannot verify something, write `UNVERIFIED:` and say
   what you would need. Never describe a feature you did not see in code. Never copy claims from `docs/USER-MANUAL.md`.
3. **Exact UI strings.** Quote button labels, headings, status words, empty-state text, error text and any help/tooltip/`title=`/
   `aria-label`/`<details>` text verbatim, with `path:line`.
4. **Roles.** Record `requiredRoles` for the nav entry and any control-level gating. Roles seen in the product: `setup_admin`,
   `support_admin`, `meeting_operator`, `publish_operator`, `records_clerk` (verify the full list in `civiccast/auth`).
5. **Plain facts about behavior**: what the user sees first, what each control does (and which API it calls), what happens on
   success and on failure, what the screen looks like when empty/loading/offline, any confirmation dialogs, anything destructive.
6. **Mismatches.** Where in-app help text, labels or links look wrong, missing or misleading for a first-time non-technical user,
   list them under "Help-text findings" (for the in-app-help handoff to the coder).
7. Keep each file under ~250 lines. Tables where they help. No marketing language.

## Output file format (`ops/docs-sprint/inventory/screens/<nav-id>.md`)
```
# <Screen name>  (nav id: <id>, section: <Setup|Run Meeting|Review Records|Publish|System Health|Help|Public|Installer>)
Source files: <paths>
Who can open it: <roles / "everyone signed in" / "kit-pending allowed?">
## What it is for (2-4 sentences, plain English, grounded in the code)
## What the user sees (layout in order top to bottom: cards/panels/tables/forms)
## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes (confirmations, destructive, disabled-when) |
## States
Empty / loading / error / offline / not-configured, with the exact text shown.
## Typical task flows (numbered, only flows the code supports)
## Statuses and words on this screen (exact strings -> what they mean; link to `status-language.ts` if shared)
## Related settings / env / CLI / API (names only)
## Help-text findings
- [HELP-nn] file:line — what is there now (quoted) — problem (missing/wrong/jargon/stale) — suggested plain-English fix
## Screenshot plan
Which states to capture (what has to be on screen) and any setup needed.
## UNVERIFIED / open questions
```

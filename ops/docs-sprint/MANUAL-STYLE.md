# CivicCast manual - style guide and chapter map (documentation sprint)

Read this completely before writing any chapter. It is the contract between the chapter writers and the assembler.

## 1. Audiences and voice
The manual has four parts. **Part I is for people who are not technical**: a public-access volunteer, a camera operator, a video
editor, a records clerk, a PEG station employee. **Part II is for the IT person at a small city** (one or two people who run
everything). Part III is architecture. Part IV is reference.

Part I voice: second person ("you"), present tense, short sentences, plain words. Say what to click and what you will see. Explain
every piece of jargon the first time it appears in a chapter, in one clause, in plain English ("the *conform cache* - a folder where
CivicCast keeps ready-to-play copies of your videos"). No marketing language. No "simply", "just", "easily", "obviously".
Part II voice: precise, complete, command-line and file-level detail is welcome, still plain English first.
Never address a reader as a computer expert in Part I. Never talk down to the IT reader in Part II.

## 2. Truth rules (non-negotiable)
1. Every factual statement about what the software does comes from the **inventories** in `ops/docs-sprint/inventory/` (screens,
   `generated/cli.md`, `generated/api.md`, `generated/env-vars.md`) **and/or from code you read yourself**. When you rely on a
   statement you cannot trace, do not write it.
2. **Describe actual behavior, not intended behavior.** The inventories list defects as `[HELP-nn]` findings. If a control is broken
   or misleading in beta.10, say what really happens in a callout (section 4, "Known issue") and give the reader the workaround if the
   code shows one. Do not hide a defect and do not describe the screen as if it worked.
3. Anything marked `UNVERIFIED` in an inventory is **not** to be stated as fact. Either omit it, or write it as "In testing we could not
   confirm..." only when it matters to the reader.
4. Proof status. State beta.10's status exactly: published 2026-10-02 as a **GitHub pre-release / beta candidate**; Gate A passed for the
   clean-install lane only; upgrade and download-only lanes not run; a **first install with neither the full kit nor an earlier install is
   not proven** (the installer needs the `packs` and `station` folders; see `inventory/screens/installer-*.md`); no human field-tester
   sign-off yet. The exact wording lives in `docs/releases/v1.0.0-beta.10-verification.md`. Do not claim more.
5. No invented numbers, sizes, times, limits or defaults. Quote them from code/inventory with a source in a hidden comment (section 6).
6. Time zones: several screens treat typed times as **UTC** (see the Recording, Program Guide, Schedule inventories). Say so wherever
   a reader types a time.

## 3. Structure of every task chapter (Part I)
```
# Chapter title                      (level 1 = chapter; `{#ch-<slug>}` anchor on the heading)
One short paragraph: what this chapter lets you do and who normally does it.
## Before you start                  (what you need: role, what must already be set up)
## <Task name>                       (one level-2 heading per task, verb first: "Start a channel")
Numbered steps. One action per step. Bold the exact label of anything the reader clicks: **Start**.
What you should see after the steps (one sentence, quoting the real on-screen text).
> **Known issue (beta.10):** ...     (only where the code is wrong/misleading)
> **Warning:** ...                   (anything that affects a channel on the air, or deletes, or cannot be undone)
## If it did not work                (real error texts quoted from the code, with the cause and the fix)
## Related                           (links to other chapters by anchor)
```
Part II chapters use the same headings but may add `## Reference tables`. Use pipe tables with a header row. Keep each table
column short enough to render in a printed page; split wide tables.

## 4. Callouts (render as pandoc block quotes with a bold label; do not invent other labels)
`> **Note:**` background the reader may need. `> **Tip:**` a faster or safer way. `> **Warning:**` can affect what is on the air,
delete data, or cannot be undone. `> **Known issue (beta.10):**` a defect or surprise in this build, with the workaround.
`> **For IT staff:**` (Part I only) one line pointing to the Part II chapter that has the technical detail.

## 5. Screenshots
Screenshots live in `docs/manual/images/` as PNG, named `<surface>-<screen>-<state>.png` (examples: `operator-live-onair.png`,
`portal-watch.png`). Reference them like this, **always with alt text and a caption**:
```
![The Live screen while a channel is on air. The blue bar at the top shows the channel name.](manual/images/operator-live-onair.png){width=90%}
```
Use only screenshots that exist or that you list in your chapter's shot list: write `ops/docs-sprint/shots/<chapter>.json` (a JSON list;
fields in `ops/docs-sprint/tools/shoot.py`) naming every screenshot you reference that does not already exist, with the screen path (hash
route, e.g. `/operator/#/live`), what must be on screen, and any click steps. The coordinator will capture them. Existing resident-portal
images: `portal-home.png`, `portal-recordings.png`, `portal-schedule.png`, `portal-watch.png`, `portal-home-phone.png`.
Do not describe a screenshot's contents beyond what the inventory states the screen shows.

## 6. Provenance comments
At the end of each chapter, add one HTML comment: `<!-- SOURCES: inventory/screens/live.md; civiccast/egress/router.py:120-188; ... -->`.
It is not rendered. A reviewer will use it to verify the chapter.

## 7. Diagrams (Part III mainly; also a few in Parts I and II)
Use Mermaid in fenced blocks (` ```mermaid `). Keep each diagram readable on a letter page: at most ~12 nodes, short labels, one idea
per diagram. Prefer `flowchart LR/TB`, `sequenceDiagram`, `stateDiagram-v2`. Every diagram needs a caption line below it and a one-paragraph
explanation in plain English. Only draw components, ports and flows you verified in code or the inventories.

## 8. Cross-references and anchors
Chapter anchors: `{#ch-welcome}`, `{#ch-signing-in}`, etc. Link with `[text](#ch-xyz)`. Appendix anchors `{#app-cli}`, `{#app-roles}`.
Do not link to files outside the manual except public URLs (the GitHub release page, the repo). Do not copy text from the old
`docs/USER-MANUAL.md` unless you have re-verified every sentence against the inventories or code.

## 9. Chapter map and file names (`docs/manual/src/`)
| File | Part | Chapter |
| --- | --- | --- |
| `00-front.md` | - | Title page metadata, "About this manual", how to read it (written by the coordinator) |
| `10-welcome.md` | I | 1 What CivicCast is, the people and roles, the life of a meeting |
| `11-signing-in.md` | I | 2 Signing in and finding your way around |
| `12-before-meeting.md` | I | 3 Before the meeting: schedules, agendas, recording schedules |
| `13-running-meeting.md` | I | 4 Running the meeting: Live, Channels, Control Room, graphics, remote guests |
| `14-after-meeting.md` | I | 5 After the meeting: assets, captions, summaries, approvals |
| `15-publishing.md` | I | 6 Publishing, and what residents see |
| `16-station-business.md` | I | 7 Reports, analytics, program guide export, underwriting, apps |
| `17-something-wrong.md` | I | 8 When something looks wrong (health, alerts, emergency alerts, who to call) |
| `20-planning.md` | II | 9 Planning your station: hardware, network, storage, accounts |
| `21-installing.md` | II | 10 Installing, first run, upgrading, uninstalling |
| `22-configuration.md` | II | 11 Configuring the station |
| `23-operations.md` | II | 12 Running it day to day: service, logs, backups, updates |
| `24-security.md` | II | 13 Security and privacy |
| `25-troubleshooting.md` | II | 14 Troubleshooting matrix |
| `26-integrations.md` | II | 15 Cable headend, streaming, CDN, federation, emergency alerts, the API |
| `30-architecture.md` | III | 16 How CivicCast is built (diagrams) |
| `40-appendices.md` | IV | A-L (CLI, API, settings, files/ports, statuses, roles, checklists, evidence, glossary, licenses, history) |

Write only your assigned file(s). Use level-1 headings for chapters and level-2/3 below that. Do not write front matter (`---` blocks).

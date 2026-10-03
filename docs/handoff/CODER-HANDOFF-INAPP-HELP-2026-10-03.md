# CivicCast: coder handoff for the built-in help (beta.11)

Written 2026-10-03 (Mountain time) by the documentation coordinator (Claude, Sonnet 5.5). This is the one document to start from for the built-in help work. It is for the AI that owns code on this project. The coordinator writes no code; nothing described here has been implemented.

Read [`CODER-HANDOFF-2026-10-02.md`](CODER-HANDOFF-2026-10-02.md) first for the project, the owner's rules and the machine gotchas. This file only adds the built-in help work.

## 1. What you are being asked to do

Make the text inside CivicCast (the staff console, the resident portal and the installer screens) say what the program really does, in plain English for a station volunteer or clerk. The audit is finished and the replacement text is written. Your job is to put it in the code, fix the tests that pin the old text, fix the defects the audit found, and regenerate the in-app manual.

- Target release: **beta.11**. Do not touch the `v1.0.0-beta.10` tag or its installer. Beta.10 was published as is.
- The owner (Scott) is a project manager, not an engineer. Decisions about how to implement are yours. Push, merge, tag and release stay his.
- Describe the program as it is. Where a feature is broken, the specs give honest text for now and an **"after fix:"** version. Use the "after fix:" text only once the code is repaired and you have run it.

## 2. Where everything is (all on `main`, GitHub `scottconverse/civiccast-native`)

| What | Path |
| --- | --- |
| 63 per-screen help specs | `docs/in-app-help/*.md` |
| Index of the specs, usage steps, 25-row product-gap list | `docs/in-app-help/README.md` |
| In-app manual spec (regeneration, anchor map) | `docs/in-app-help/help.md` |
| The new User Manual (Markdown, PDF, Word) | `docs/USER-MANUAL.md`, `.pdf`, `.docx` |
| Manual chapter sources | `docs/manual/src/*.md` |
| Style rules used for all the text | `ops/docs-sprint/MANUAL-STYLE.md` |
| Screen inventories the specs were built from | `ops/docs-sprint/inventory/screens/` (63 files) |
| All 473 audit findings | `ops/docs-sprint/inventory/FINDINGS-INDEX.md` |
| Generated tables (CLI commands, API routes, environment variables) | `ops/docs-sprint/inventory/generated/` |
| Documentation tools | `ops/docs-sprint/tools/` (`build_manual.py`, `build_help_index.py`, `shoot.py`, `gen_*.py`) |

Each spec has six sections, in this order: where the text lives now (file and line), the current text, what the screen really does, the mismatches table, the proposed text, and notes for the coder. Line numbers were confirmed against commit `c09b0e67`; re-check them, because code may have moved.

The 63 specs are grouped like this (the README lists every file):

| Group | Files | Mismatch rows |
| --- | --- | --- |
| Operator console: Run Meeting | 11 | see README |
| Operator console: Review and publish | 14 | see README |
| Operator console: Setup, health and shell | 15 | see README |
| Resident portal | 10 | see README |
| Installer | 13 | see README |
| **Total** | **63** | **645** |

## 3. How to implement one screen

1. Open the spec. Read **Mismatches** first. Each row is: what the text claims, what the code really does (with a citation) and a severity.
2. Re-verify the row against the code before you change anything. The specs were written by reading code, not by running a station. Lines marked **UNVERIFIED** are things the writers could not confirm. Run the screen and confirm them.
3. Apply the **Proposed text** strings in the file named under "Where the text lives now". Keep the wording; change it only if the screen's behavior has changed.
4. Search `tests/`, the operator `*.test.tsx` files and `civiccast/apps/portal-operator/e2e/` for the **old** text before you edit. The spec's "Notes for the coder" names the tests that pin strings. Update the tests and the text together.
5. Items marked as a **code fix, not a text fix** are defects. They are listed in section 5 below. Fix the code, then switch that screen's text from the beta.10 wording to the "after fix:" wording.
6. Run the narrowest check first (the screen's own test), then the whole operator suite, then the installer and docs tests in section 6.

IDs: `HELP-nn` and `SHELL-nn` come from the screen inventories and are unique. `NEW-n` restarts in every file, so cite one as `<file>:NEW-n` (for example `summary:NEW-2`). The files that name `NEW-` rows in a prefixed form (the resident portal ones) already do. Severity words differ by writer: the console files use *blocks work / misleading / cosmetic*; the installer and portal files use *SERIOUS / High / Moderate / Medium / Low*. Treat *blocks work*, *SERIOUS* and *High* as the same top tier.

## 4. Suggested order

Do the top tier first. These are the screens where today's text actively misleads someone into a wrong action or tells them something is working that is not.

**First (top tier; text and code):**
1. **Installer text** (`installer-*.md`). The setup page and first-run wizard say AI models download after setup; setup needs the full kit and stops with exit 110 or 123 without it. The exit 128 and 129 dialogs say nothing was changed, but setup has already replaced the program files and stopped the service. The self-test failure dialog names a log entry that does not exist. Uninstall deletes the model-pack cache (about 21 GB) that a reinstall cannot re-download. Source: `installer/` NSIS hooks (`nsis-hooks-bootstrap.nsh`, comments near lines 358-372) and `civiccast/installer/service.py`.
2. **Summary review** (`summary.md`). Approve most likely fails with HTTP 422 and Export is unreachable.
3. **Alerts and Emergency Alerts** (`alerts.md`, `eas.md`, `public-shell.md`). No destinations, several alert kinds with no rule, emergency alerts off unless two environment variables are set that nothing sets, and a hard-coded placeholder in the portal.
4. **Contributors, Program Guide, Schedule, Auto-schedule** (`contribute.md`, `guide.md`, `schedule.md`, `autoschedule.md`).
5. **Paywall and Subscribe** (`paywall.md`, `public-paywall.md`, `public-subscribe.md`).
6. **The in-app manual** (`help.md`). See section 7. It has five top-tier rows, and the new manual is currently not shown correctly.

**Second:** the rest of the "misleading" rows, screen by screen. By count of top-tier rows, the heaviest files are `help`, `channels`, `schedule`, `publish`, `contribute`, `underwriting`, `live`, `guide`, `controlroomsetup`, `epg`, `assets`, `ai-models`, `medialifecycle`.

**Last:** the "cosmetic" rows, the portal pages and the shell labels.

## 5. Product defects found while writing the help (code, not text)

The consolidated list, with the manual chapter and spec that describe each, is the table at the end of `docs/in-app-help/README.md`. Summary of what you will be fixing:

- Summary Approve sends fields the server refuses; approved summaries leave the list so Export signed record cannot be reached. Fix: send only `approval_note`; list Approved summaries; add Download and Verify.
- Contributors "Send to schedule" likely fails for any submission with a requested air date (no time zone on the producer's date).
- Program Guide skipped airings are never retried by Refresh guide.
- Auto-schedule text is wrong (items are created Published and compiled hourly).
- Alerts: destinations empty and cannot be attached to a rule; no rule for several kinds, including emergency-alert source down.
- Emergency alerts: polling and auto-surface off by default; the portal box is a hard-coded placeholder.
- Paywall: saving with the secret box blank erases the stored secret; no tier or checkout routes; no sign-in email.
- Resident subscribe: notices never sent, the confirmation link has no web address and no page serves it, RSS feeds are empty.
- Playback policy: most settings are not enforced on video.
- Analytics: the "Telemetry is off" box points at a Reports tab and a Setup switch that do not exist.
- Live and Channels: the sample test source passes pre-flight with no camera; Take live with a source last checked more than 30 seconds ago is refused before it re-checks.
- Facility: sample data only, no way to send a command.
- Sign-in: the only sign-in page is titled First setup.
- Installer: items under "Installer" in section 4.
- Backup and restore: no `civiccast backup` or `restore` command; the DR drill calls the Postgres tools by bare name.
- Service configuration: nothing writes the service `Environment` registry value that the manual's recipe uses.
- Control Room: the sidecar has no installer.
- Logs: `control_plane.log` and `postgres.log` are never rotated; the support bundle omits worker and control-plane logs.
- Health: `/health` shows `degraded` only for a non-current database schema.
- `civiccast/live/cdn_publisher.py`: unclear whether it is wired into the shipped app.
- Live caption audio is dropped when the caption worker falls behind (the top open engine item in the earlier handoff).

When you fix one, update the spec's note, the manual chapter and `PROJECT-STATUS.md`, and log it in `ops/beta10-oversight/OVERSIGHT-LOG.md` as the earlier handoff asks, so the docs can follow.

## 6. Tests that pin the old text

Known string-pinning tests (verify each before editing; the specs list more per screen):

- `tests/installer/test_nsis_bootstrap_hooks.py` and `tests/policy/test_native_installer_identity.py` pin installer wording.
- `civiccast/apps/portal-operator/src/**/*.test.tsx`, for example `ReportsScreen.test.tsx` ("No content has aired"), `ManualScreen.test.tsx`, `manual-link.test.ts`, `ProviderReadinessPanel.test.tsx`, `StationProfileScreen.test.tsx`, `SetupScreen.test.tsx`, `SourceUploadWizard.test.tsx`, `ActivityPubScreen.test.tsx`, `SetupScreenLoopbackDenied.test.tsx`.
- `civiccast/apps/portal-operator/e2e/` specs, for example `summary-review.spec.ts` and `signed-records.spec.ts`. Check what they mock before changing the Approve call.
- `tests/docsite/test_router.py` pins nine manual anchors (lines about 35-46) and `test_architecture_diagrams_are_embedded_not_broken_relative_links` (about 51-62).
- Documentation guards that must stay green: `tests/docs` (no "not signed" wording; landing-page primary buttons `class="button primary"` must not say "download"; no raw `.md` links), `tests/docsite`, `tests/test_user_manual_render.py`.

## 7. The in-app manual (`civiccast/docsite/manual.json`)

This file is product code. It is generated from `docs/USER-MANUAL.md`, which is now the new four-part manual, so the file shipped in beta.10 is the old manual. Full detail, with measurements and the old-to-new anchor map, is in `docs/in-app-help/help.md`. Short version:

1. **The generator loses most of the text.** `scripts/render_docsite_manual.py` keeps only about 2.8 percent of the new manual's text (24,586 of 875,806 characters), and the contents list has 24 entries instead of 635. Cause: pandoc reads words in angle brackets (`<your-name>`, `<id>`, and so on) as HTML tags and the cleaner drops them. Fix: add `-f markdown-raw_html-task_lists` to the pandoc call (about 892,701 of 922,980 characters then survive).
2. **Allow-list.** Add `dl`, `dt`, `dd` to `_ALLOWED_TAGS` in `civiccast/docsite/render.py` (definition lists were dropped). Open external links in a new tab with `rel="noopener noreferrer"`.
3. **Images.** 79 images; 50 point at `manual/images/*.png` that are not in the repository (the console screenshots are blocked, see section 8). Make the build fail on an unresolved image so a missing screenshot cannot ship. Size is about 10 MB without the missing screenshots; choose between shrinking and embedding, or serving from a public route, and add GZip.
4. **Links.** `ManualScreen.tsx` needs a click handler so a `#section` link inside the manual does not land on "Page not found" (the console uses a hash router). Confirm in the lab.
5. **Anchors.** Update every product link and the nine anchors in `tests/docsite/test_router.py` to the new ids, using the map in `help.md` (for example `glossary` to `app-glossary`, `report-without-github` to `report-a-beta-issue`, `where-recordings-live` to `configuration-storage`).
6. **Contents list.** 635 entries on six levels do not fit the 280 px panel. Group by Part and show a chapter's sections only when it is open.
7. **Order.** Regenerate **last**, after the text and code changes, because any later manual edit changes the source hash. Then run `uv run python scripts/render_docsite_manual.py --check-current`, `pytest tests/docsite` and the operator tests.

Also: a manual edit that the code changes force (for example a fixed Approve button) means editing `docs/manual/src/*.md`, rebuilding with `python ops/docs-sprint/tools/build_manual.py` and `python scripts/render_user_manual.py`, and keeping the 81 documentation tests green.

## 8. What is not finished (be exact with Scott about this)

- **Operator-console screenshots are missing.** The lab station has no real admin password, and the coordinator did not guess credentials. The manual shows described placeholders for the staff console. Minting a lab token with `civiccast token issue` needs Scott's yes; then `python ops/docs-sprint/tools/shoot.py <out> http://127.0.0.1:8000 <shots.json> --token-env NAME` takes read-only shots (shot lists in `ops/docs-sprint/shots/`).
- **Nothing was run on a station.** Every spec was written from code and the fact-checked manual. Items the writers could not confirm are marked UNVERIFIED in each spec. Examples: what Mute, Drop and Close do to a guest's sound; what happens when a one-hour takeover ends; what Target series does on Recording; whether internal manual links land on "Page not found".
- **A formal visitor audit of the published pages has not been run.**
- **Beta.10 proof status** is stated in the manual and landing page exactly: pre-release; Gate A clean-install lane only (10 of 10, local Windows Sandbox, 5-minute soak); upgrade and download-only lanes not run; first install without the full kit not proven; no human field-tester sign-off. Do not write help text that claims more.

## 9. Ground rules for the text

- Plain English for a volunteer or clerk. Define any jargon the first time (the specs already do).
- No softeners ("if convenient", "optionally", "if time allows"). Every step is mandatory or omitted; a conditional states both branches.
- Never claim readiness above the evidence. If a screen cannot do something yet, say so, with what to do instead.
- Times in logs are Mountain (`-0600` in October). Read the offset; never assume UTC.
- Absolute `C:\` paths when you tell Scott where a document is.
- Do not edit the published manual, landing page or `docs/in-app-help/` without telling Scott, unless you are changing behavior the docs describe; in that case log it and update the doc in the same change.

## 10. Receipt

The specs and this file are documentation only. They were produced by the coordinator's writers and checked by the doc tests (81 passed at `9d794fbb`). No product code was changed.

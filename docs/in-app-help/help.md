# Manual (nav id: help)

Sidebar: Help > **Manual** (the section is collapsed by default). Page eyebrow "Help"; page H1 "Operator manual". Routes `#/help`, `#/docs`, `#/manual`. Manual authority: `docs/manual/src/11-signing-in.md` (find your way around; the Report a beta issue button) and `17-something-wrong.md` (section "Report a beta issue", `#report-a-beta-issue`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/ManualScreen.tsx` (160 lines), `screens/manual-link.ts`, `components/shell/Sidebar.tsx` (section tooltip 91, nav item 93, footer button 395-399), `App.tsx:110, 257-259`, `api/client.ts:617` (`getManual`), `index.css:300-322` (`.cc-manual-prose`). Server and content: `civiccast/docsite/{render,service,router,models}.py`, `civiccast/docsite/manual.json`, `manual.render.json`, `scripts/render_docsite_manual.py`, `docs/docsite-sync.md`, `ops/docs-sprint/tools/build_manual.py`. Lines confirmed by opening the files (HEAD c09b0e67).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Help" (eyebrow); "Operator manual" (H1) | page header | ManualScreen.tsx:94, 96 |
| "This is the same manual that ships as docs/USER-MANUAL.md, rendered here so it works with no internet connection. Signing in, getting a video in, packaging, publishing, where recordings live, and a plain-language glossary of provider jargon are all in here." | intro | 98-101 |
| "Loading the operator manual..." | loading | 107 |
| "The manual could not load." + server text or "Try again." | error card | 113 |
| "Manual contents" (nav label); "Filter manual sections" (hidden label); placeholder "Search this manual" | contents panel | 120, 125, 131 |
| "No section title matches "<text>"." | empty filter | 138 |
| "Operator manual, glossary, and provider setup guides" | sidebar section tooltip | Sidebar.tsx:91 |
| "Manual" | nav label | Sidebar.tsx:93; App.tsx:110 |
| "Report a beta issue" (opens `/help#report-without-github`) | sidebar footer | Sidebar.tsx:395-399 |
| "<path> not found. Run: uv run python scripts/render_docsite_manual.py" | HTTP 503 detail shown in the error card | service.py:38-40, router.py:27-30 |

## What the screen really does
It shows the manual that is built into the program, with a contents list and a box that filters the contents by section title. It works for anyone, signed in or not, and it is the only screen that stays open while the recovery kit is waiting to be confirmed. It does not read `docs/USER-MANUAL.md`; it displays one pre-built file, `civiccast/docsite/manual.json`, made at commit time by `scripts/render_docsite_manual.py` (pandoc, then an allow-list HTML cleaner). Other screens link into it with `/help#<section id>`. As of HEAD the file is the old manual: `manual.render.json` records source hash `b5df977e...` while `docs/USER-MANUAL.md` now hashes to `f32463ca...` (the new four-Part manual, commit 98709eaa). Building the new manual with today's generator keeps only about 3 percent of its text (Mismatches NEW-1).

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | In-app manual is the current manual | Stale: recorded hash `b5df977e` vs source `f32463ca`. The shipped HTML still says beta.10 "has not been published" (old text). The CI step `ci-docs.yml:75-76` (`--check-current`) fails on this tree. Fix by regenerating after NEW-1 to NEW-5 are fixed, as the last step of the doc sprint | blocks work |
| HELP-02 | (no text) Internal links inside the manual, e.g. `href="#ch-integrations"` (408 of them in the new manual, all resolve inside the file) | `ManualScreen` has no click handler on the content panel (145-155). The console is a `HashRouter` app (`main.tsx:14`); `Layout.tsx:36-46` records that a bare `#id` link is read as a route and lands on Page not found. UNVERIFIED at runtime (one click in the lab confirms) | blocks work |
| HELP-03 | Section `report-without-github` (old manual) sends people to System Health to press Create support bundle | Old section no longer exists in the new manual (no heading with that id), so the sidebar link `Report a beta issue` lands at the top of the manual with no scroll. The new manual's real section is `report-a-beta-issue` (17-something-wrong.md:324). The public site also links `#report-without-github` (`portal-public/src/App.tsx:35`). Only Support admin can create a support bundle (see health.md NEW-2) | misleading |
| HELP-04 | Old section `your-first-beta-workflow`: "choose Run private rehearsal" | No such button (it is "Check broadcast readiness", SystemHealthScreen.tsx:1577). Resolved by the new manual, but `SourceUploadWizard.tsx:212` still links to the old id, which will not exist | misleading |
| HELP-05 | "Search this manual" (131) | Filters section titles only (62-63); the box does not search the text | misleading |
| HELP-06 | Intro names `docs/USER-MANUAL.md` (98) | A clerk does not know what that is | cosmetic |
| HELP-07 | One flat contents list | Old: 64 entries. New manual: 635 entries on six levels, with 5 level-1 (About, Parts I to IV), 35 level-2 (chapters and appendices), 266 level-3 and more; the list has no folding and indents up to 4.25 rem inside a 280 px panel | misleading |
| HELP-08 | "works with no internet connection" (98) | True for the text; every external link (GitHub, Cloudflare, Google) opens in the same tab and replaces the console, because the cleaner drops `target` and `rel` (`render.py:123-126`). 50 screenshots are also missing (NEW-3) | misleading |
| HELP-09 | Old sections `roles-and-permissions`, `the-five-role-model` cited `KNOWN_ROLES` and `require_role` | Not in the new manual (zero hits). New role text is chapter 11 and Appendix F (`#app-roles`, fact-checked). Resolved once regenerated | cosmetic |
| HELP-10 | Old `destructive-actions-confirm` said Emergency Alerts "force a slate" uses a confirmation dialog | Resolved by the new manual (see _shell-shared-components.md); no change to this screen | cosmetic |
| HELP-11 | Old `provider-federation` mentioned a federation on/off switch | Resolved: new manual `#federation-activitypub` and `#understand-federation-federation` say there is no switch (activitypub.md) | cosmetic |
| HELP-12 | "Run: uv run python scripts/render_docsite_manual.py" (service.py:38-40) | Developer wording on a broken install | cosmetic |
| HELP-13 | (no text) | No link to the PDF or Word copies (`docs/USER-MANUAL.pdf`, `.docx`); no print style in `index.css` was found | cosmetic |
| NEW-1 | Every section of the new manual appears | `pandoc` reads loose words in angle brackets, such as `<your-name>`, `<time>`, `<id>`, `<channel>`, `<cue>`, `<source>`, `<file>`, `<folder>`, `<install>`, `<out>`, `<staff-token>`, as raw HTML tags. `sanitize_html` drops a tag it does not know together with everything up to its end tag (`render.py:163-172, 189-196`). Measured: of 875,806 text characters only 24,586 survive (2.8 percent) and the contents list has 24 entries instead of 635. Fix: pandoc flag `-f markdown-raw_html` (then 892,701 of 922,980 survive) | blocks work |
| NEW-2 | Definition lists and checklists appear | `dl`, `dt`, `dd` (22 lists, 176 terms) and `label` + `input` (97 checklist items, from `- [ ]` lines) are not in the allow-list, so their text is dropped (about 30,000 characters). Fix: add `dl`, `dt`, `dd` to `_ALLOWED_TAGS`, and read the manual with `-task_lists` (the items then keep their text) | blocks work |
| NEW-3 | Screenshots appear | 79 `<img>` tags; 50 point at `manual/images/<name>.png`, which are not in `docs/manual/images/` (6 files there). `embed_local_images` leaves a missing file unchanged and the cleaner then removes its `src` (relative paths fail `_safe_url`), so the browser shows a broken image. Nothing in the build fails | misleading |
| NEW-4 | (no text) | With NEW-1 and NEW-2 fixed, `manual.json` is about 10.15 MB (10,151,770 characters of HTML, 29 images embedded). The 50 missing screenshots at the present average of 0.23 MB would add about 15 MB (estimate). It is sent whole by `GET /api/public/manual` with no token; no GZip middleware was found in `civiccast/app.py` | misleading |
| NEW-5 | Dangling anchors in product code | See the anchor map below; the nine anchors pinned by `tests/docsite/test_router.py:35-46` and every `manualLink(...)` id do not exist in the new manual | blocks work |
| NEW-6 | "Report a beta issue" opens the section "Don't Have A GitHub Account?" (manual 11-signing-in.md:212, 17-something-wrong.md:328) | That heading is not in the new manual (the section is "Report a beta issue"). The manual text, not the code, is wrong here | cosmetic |
| NEW-7 | `docs/docsite-sync.md` and the `embed_local_images` docstring say "two architecture diagrams" and "every ##/###/#### heading" | New manual has 79 images (23 diagrams) and headings to level 6 | cosmetic |

## Proposed text
**Header:** eyebrow "Help"; H1 "CivicCast manual". Intro: "What this is for: the full CivicCast manual, built into the console so it works without internet. Part I is for station staff and volunteers. Parts II to IV are for IT staff. Who can use this: anyone, even before signing in. Links to other websites need internet and open in a new tab."
**Search box:** placeholder "Filter sections by title". Hidden label "Filter manual sections by title". Empty: "No section title matches "<text>". Try one word, such as captions or backup."
**Contents:** group headings "About this manual", "Part I. Using CivicCast", "Part II. Installing and running", "Part III. How CivicCast is built", "Part IV. Reference". Show the chapter titles under each part; show the sections of the chapter you are reading.
**Loading / error:** "Loading the manual..." / "The manual could not load. The manual file is missing or damaged. Ask your IT person to repair CivicCast, or open the PDF copy. (Details for IT: <server text>.)"
**Sidebar tooltip:** "The CivicCast manual: how to use each screen, set up the station and fix problems."
**Sidebar footer:** keep "Report a beta issue".
**After fix:** an "Open the PDF copy" link if the PDF is shipped with the station (UNVERIFIED that it is).

## Notes for the coder
Files to change: `ManualScreen.tsx` (text above, click handler, grouped contents), `Sidebar.tsx:91, 395`, `service.py:38-40`, `civiccast/docsite/render.py`, `scripts/render_docsite_manual.py`, `docs/docsite-sync.md`. List only; do not edit `manual.json` by hand.

**1. Regeneration steps (in order).**
1. Rebuild the source if `docs/manual/src` changed: `python ops/docs-sprint/tools/build_manual.py` (3 chapter files are modified and uncommitted at this commit).
2. Apply the generator changes in item 2, then run `uv run python scripts/render_docsite_manual.py`. It writes `civiccast/docsite/manual.json` and `manual.render.json`. Run it last: any later edit to the manual changes the source hash.
3. Run `uv run python scripts/render_docsite_manual.py --check-current`, `pytest tests/docsite`, and the portal-operator tests.

**2. Generator and router changes (measured with pandoc 3.9.0.2 on the new manual).**
- `render_docsite_manual.py` pandoc call: change `["pandoc", SOURCE, "-t", "html5", "--wrap=none"]` to add `-f markdown-raw_html-task_lists` (NEW-1, NEW-2). Result: 892,701 of 922,980 text characters kept, 635 contents entries, 0 duplicate ids, longest id 75 and longest title 80 characters (the model limits are 200 and 400).
- `render.py` `_ALLOWED_TAGS`: add `dl`, `dt`, `dd` (NEW-2). `colgroup` and `col` already work. Add tests in `tests/docsite/test_render.py`.
- `render.py`: for every `http(s)` `<a href>`, write `target="_blank" rel="noopener noreferrer"` in `_emit`; do not accept author-written `target` (HELP-08). Update `_ALLOWED_ATTRS` or set it in code, with a test.
- `embed_local_images` / build script: count images it cannot resolve and fail the build (or print each name) so a missing screenshot cannot ship as a broken image (NEW-3). Either add the 50 PNGs to `docs/manual/images/` or remove the references.
- Size (NEW-4): choose one. (a) Keep data URIs and shrink the PNGs (convert to WebP or reduce width to 1280 px). (b) Copy images to `civiccast/docsite/images/`, serve them from a public route such as `/api/public/manual/images/<name>`, add the folder to the `pyproject.toml` force-include (lines 190-196), and rewrite `src` to that path (`_safe_url` already allows a leading `/`). Option (b) also requires updating `test_architecture_diagrams_are_embedded_not_broken_relative_links` (test_router.py:51-62). Add GZip for `/api/public/manual` either way.
- `ManualScreen.tsx`: add an `onClick` on the content panel (line 145). If the click target's closest `a` has an `href` starting with `#`, call `preventDefault` and `navigate('/help#<id>')` (react-router `useNavigate`), unless a modifier key is held (HELP-02). Add a test beside `ManualScreen.test.tsx:130`.
- `ManualScreen.tsx` contents: group by the five level-1 entries; show level 2 under each; show level 3 and below only inside the open chapter, or all levels while the filter box has text (HELP-07). `TocList` indents by `(level-1) * 0.85rem` and bolds levels 1 and 2 (lines 18, 34); six levels do not fit the 280 px panel.
- Docs: update `docs/docsite-sync.md` and the docstring at `render.py:32-52` (NEW-7). `service.py` and `router.py` need no change; the 503 text should be plain (HELP-12).

**3. Anchor map (old id -> id in the new manual).** Update the product code and the tests together.
| Old id | New id | Where used |
| --- | --- | --- |
| glossary | app-glossary | manual-link.ts:9-10; ManualScreen.test.tsx:106, 125-127; test_router.py:36 |
| publish-surfaces | the-publishing-steps-surfaces | installer/service.py:2115; test_router.py:42 |
| where-recordings-live | configuration-storage (`plan-storage` for the planning view) | installer/service.py:2131; StationProfileScreen.tsx:381; its test :258; manual-link.test.ts:14 |
| provider-internet-archive, provider-youtube, provider-subscriber-notifications, provider-local-archive-folder, provider-podcast-feed | publishing-providers | installer/service.py:2149-2292; ProviderReadinessPanel.test.tsx:73; test_router.py:38-39 |
| provider-cloudflare-r2, provider-alternative-cdns | cdn-and-provider-options | installer/service.py:2216-2276; test_router.py:37; manual-link.test.ts:9 |
| provider-federation | federation-activitypub | installer/service.py:2311; ActivityPubScreen.tsx:156 and its test :93; test_router.py:40 |
| cdn-cost-estimate | cdn-and-provider-options (no cost section exists in the new manual; add one or reword `SetupScreen.tsx:1303-1308`) | SetupScreen.tsx:1305; SetupScreen.test.tsx:134; test_router.py:43 |
| report-without-github | report-a-beta-issue | Sidebar.tsx:395; SetupScreen.tsx:1333; portal-public/src/App.tsx:35; SetupScreenLoopbackDenied.test.tsx:181; test_router.py:44; also fix manual 11-signing-in.md:212, 224 and 17-something-wrong.md:328 (NEW-6) |
| your-first-beta-workflow | ch-before-meeting (dangling today as well, see setup.md NEW-3) | SourceUploadWizard.tsx:212; SourceUploadWizard.test.tsx:60 |
| live-captions-switch | live-captions-what-the-settings-change | StationProfileScreen.tsx:424; its test :366 |
`test_router.py:30` also needs `len(toc) > 10` (still true). The `ManualScreen.test.tsx` fixture uses its own fake ids and only needs edits if the real ids are used.

**4. Pins and cautions.** `tests/docsite/test_router.py:27` pins `source == "docs/USER-MANUAL.md"`, `:31` an `<h1` or `<h2`, `:60-62` `<figure>` and `data:image/png;base64,` (keep if option (a) above). The Gate A render check string pins live in `sandbox-lab/scripts/In-Sandbox-Report.ps1` (see setup.md); none of the strings on this screen were found there or in `e2e/`. Add tests that fail if the text kept falls below about 95 percent, if the HTML has no `<dt`, or if any `<img>` lacks `src`.

**5. Not fixed here, needs a decision.** Real full-text search (HELP-05) versus renaming the box; whether to ship the PDF with the station (HELP-13); whether a role-based "start here" page is wanted (HELP-07).

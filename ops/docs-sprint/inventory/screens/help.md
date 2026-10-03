# Manual (Help)  (nav id: help, section: Help)
Source files (under `civiccast/apps/portal-operator/src/`): `screens/ManualScreen.tsx`, `screens/manual-link.ts`, `routes.ts`, `App.tsx`, `components/shell/Sidebar.tsx`, `api/client.ts:617`.
Server/content (under `civiccast/`): `docsite/{router,service,models,render}.py`, `docsite/manual.json`, `docsite/manual.render.json`; repo: `docs/USER-MANUAL.md`, `scripts/render_docsite_manual.py`, `docs/docsite-sync.md`, `pyproject.toml:190-196`, `.github/workflows/ci-docs.yml:75-76`.
Route: `#/help` (aliases `/docs`, `/manual`, `routes.ts:47-52`). Nav label `Manual` in sidebar section `Help` (collapsed by default).
Who can open it: **anyone, even signed out.** `/help` is a public route (`routes.ts:96-99`), the API needs no token (`docsite/router.py:19`), and it is the only nav entry that stays clickable while the first-setup recovery kit is waiting to be confirmed (`availableWhileKitPending`, `Sidebar.tsx:93`; `App.tsx:222`).

## What it is for
An offline copy of the user manual, shown inside the console, with a clickable contents list and section links that other screens can point to
("Read more in the manual"). It is the only help the console has: there is no per-screen help, tooltip system or search across text.

## How the in-app manual works (where the content comes from)
1. **Source of truth:** `docs/USER-MANUAL.md` (one markdown file; sections A end-user guide, B technical reference, C architecture reference, plus `Language Standard`).
2. **Render step (manual, at commit time):** `scripts/render_docsite_manual.py` runs `pandoc` to HTML, embeds the two local diagram images as base64 `data:` PNGs, sanitizes the HTML through an allowlist (`render.py`), and extracts a flat table of contents from every heading that has an id. Output: `civiccast/docsite/manual.json` plus a hash note `manual.render.json`.
3. **Shipping:** `manual.json` is committed to git and force-included in the wheel (`pyproject.toml:195-196`). It is not regenerated at install or startup (`docs/docsite-sync.md`).
4. **Serving:** `GET /api/public/manual` (no staff token) -> `service.load_manual()` reads and validates the one file, cached by file mtime (`docsite/service.py:44-58`). Missing file -> HTTP 503 with text "`<path>` not found. Run: uv run python scripts/render_docsite_manual.py" (`service.py:38-40`, `router.py:27-30`).
5. **Display:** `ManualScreen` fetches it once (`staleTime` 5 min, no retry, `ManualScreen.tsx:51-56`) and injects `html` with `dangerouslySetInnerHTML` (:154); the contents list is built from `toc`.
6. **Response fields:** `source` (`docs/USER-MANUAL.md`), `source_sha256`, `generated_at`, `toc[{id,level,title}]`, `html` (`docsite/models.py:23-32`).
7. **Sanitizer allowlist** (`render.py:75-130`): tags p br hr h1-h6 ul ol li table thead tbody tr th td a strong em code pre blockquote img figure figcaption span div sup sub del; attributes `a`: href id title; `img`: src alt title width height; all: id class aria-hidden; URL schemes http(s), `#`, `mailto:`, `/`. No `target`/`rel`, so every link opens in the same tab.
8. **Drift gate:** CI runs `render_docsite_manual.py --check-current` (`ci-docs.yml:75-76`); it fails if `USER-MANUAL.md` changed since the last render.

Facts measured on the checked-out tree (HEAD `0edb02e2`): `manual.json` records `source_sha256 = b5df977e...6e37` and `generated_at = 2026-10-02T08:33:56Z`; 64 contents entries (1 level-1, 5 level-2, 36 level-3, 22 level-4); html about 298,000 characters (mostly the two base64 images); 36 internal `#` links and 45 external `https` links.

## What the user sees (top to bottom)
1. Eyebrow `Help`, h1 `Operator manual`, text: "This is the same manual that ships as docs/USER-MANUAL.md, rendered here so it works with no internet connection. Signing in, getting a video in, packaging, publishing, where recordings live, and a plain-language glossary of provider jargon are all in here." (`ManualScreen.tsx:96-101`).
2. While loading: `Loading the operator manual...` Error: `The manual could not load.` + server detail or `Try again.`
3. Two columns (one on narrow screens): left = sticky `Manual contents` navigation with a search box (placeholder `Search this manual`, hidden label `Filter manual sections`) and the contents list; right = the manual text in a bordered panel.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Search this manual` box | Narrows the contents list to sections whose **title** contains the text (case-insensitive) | none (client filter, :59-64) | none | Does not search the body text. No match: `No section title matches "<text>".` |
| a contents entry (link) | Scrolls to that section and highlights it | route `/help#<id>`; effect at :73-88 scrolls smoothly and sets the active row (`aria-current="location"`) | none | Indented by heading level; level 1-2 bold |
| any `/help#<id>` link elsewhere | Opens Manual and scrolls to that section | `manualLink(id)` (`manual-link.ts:12`) | none | Used by: `SourceUploadWizard` (`your-first-beta-workflow`), `ActivityPubScreen:156` (`provider-federation`), `SetupScreen:1015` (backend `manual_section` values), `:1305` (`cdn-cost-estimate`), `:1333` (`report-without-github`), `StationProfileScreen:381` (`where-recordings-live`), `:424` (`live-captions-switch`), Sidebar footer `Report a beta issue` (`/help#report-without-github`, `Sidebar.tsx:395`) |
| links inside the manual text | see HELP-02 and HELP-08 | | | |

Backend `manual_section` ids sent to Setup cards (`installer/service.py:2115-2311`): publish-surfaces, where-recordings-live, provider-internet-archive, provider-youtube, provider-subscriber-notifications, provider-local-archive-folder, provider-cloudflare-r2, provider-alternative-cdns, provider-podcast-feed, provider-federation. All of these and all `manualLink` ids above exist in the shipped contents list (checked).

Shipped contents ids (level:id) - for in-app help authors:
`1:civiccast-user-manual 2:who-reads-what 2:section-a-end-user-guide 3:what-is-civiccast 3:advanced-not-this-beta 3:your-first-beta-workflow 3:destructive-actions-confirm 3:where-recordings-live 3:managing-sign-in 3:publish-surfaces 3:cdn-cost-estimate 3:live-broadcast-limits 3:live-captions-switch 3:operator-graphics-control 3:common-operator-questions 3:provider-setup-plain-language (4: provider-cloudflare-r2, provider-internet-archive, provider-youtube, provider-subscriber-notifications, provider-local-archive-folder, provider-alternative-cdns, provider-federation, provider-podcast-feed) 3:glossary 3:when-to-ask-for-help 3:report-without-github 3:admin-quick-guide 3:meeting-operator-quick-guide 3:records-clerk-quick-guide 2:section-b-technical-reference (3: install-and-first-boot, upgrade-path, roles-and-permissions, environment-variables [4: identity-storage-and-first-run, staff-identity-and-tokens, channel-egress-gstreamer-engine-automation, captions-eas-alerting, cdn-public-base-url-trusted-proxies, tsa-records-rfc-3161, providers-publish-archive-syndicate, subscribe-email-webhook, analytics, activitypub-federation, headend-handoff-ndi-sdi-tsduck, remote-contribution-production-control-room, ai-model-dispatch, diagnostics-and-overrides], credential-store, cli-reference, troubleshooting-matrix, cross-references) 2:section-c-architecture-reference (3: subsystems-and-module-layout, the-five-role-model, the-alembic-migration-chain, the-s15-gstreamer-playout-engine, the-three-protocol-seams, the-publish-pipeline, the-cdn-aware-trusted-proxy-resolver, comparative-capability-status, open-items-and-roadmap-pointers) 2:language-standard`

## States
| State | Text |
|---|---|
| Loading | `Loading the operator manual...` |
| Error (e.g. 503) | `The manual could not load.` + the server's text |
| Empty filter | `No section title matches "<text>".` |
| Signed out | works; nav shows only entries without a role requirement; other entries bounce to First Setup |
| Offline from the internet | works (content is local); external links in the text will fail |
| Kit pending | works; every other nav entry is disabled with the title "Save or print your recovery kit and confirm it on First Setup before leaving that screen." |
| Station API down | the error card (browser network text) |

## Typical task flows
1. Open `Manual` -> type in the box -> pick a section.
2. From a Setup provider card: click `Read more in the manual` -> lands on the section (hash scroll).
3. Cannot reach GitHub: sidebar footer `Report a beta issue` -> section "Don't Have A GitHub Account?".

## Statuses and words on this screen
None of its own. Sidebar tooltip for the `Help` section: "Operator manual, glossary, and provider setup guides" (`Sidebar.tsx:91`).

## Related settings / env / CLI / API
`GET /api/public/manual`; `uv run python scripts/render_docsite_manual.py [--check-current]`; `docs/USER-MANUAL.md|.pdf|.docx`, `docs/USER-MANUAL.render.json`; Env: none.

## Help-text findings
- [HELP-01] The shipped in-app manual is out of date against its own source. `manual.json` (commit `c08032c4`, 2026-10-02 02:34 -0600) was rendered before `docs/USER-MANUAL.md` last changed (`9b834a3d`, 2026-10-02 20:36 -0600; current source sha `9ec58a06...94d6` != recorded `b5df977e...6e37`). The tag `v1.0.0-beta.10` carries the old file (`manual.render.json` at the tag has the same hash). The in-app text still says beta.10 "is a beta candidate: it has not been published, and its formal station acceptance (Gate A) has not been run. The latest published release is v1.0.0-beta.7" - false for the running product. The CI drift gate (`ci-docs.yml:75-76`) would fail on this tree. Fix: re-render at the end of the doc sprint and re-check before the next tag.
- [HELP-02] The manual body has 36 internal links of the form `href="#section"` (e.g. `#glossary`, `#your-first-beta-workflow`). The console is a `HashRouter` app (`main.tsx:14`); `Layout.tsx:36-46` records that a bare `#...` link is read as a route and lands on "Page not found". `ManualScreen` has no click handler on the content panel (:145-155). So cross-links inside the manual very likely break. UNVERIFIED at runtime (needs one click in the lab). Fix: intercept clicks in the content panel and route them to `/help#id`, or rewrite hrefs at render time.
- [HELP-03] Section `report-without-github` (the target of the sidebar `Report a beta issue` link) tells the reader to go to System Health and press `Create support bundle` and `Download support bundle`. Those buttons work only for the `support_admin` role (`SystemHealthScreen.tsx:1496,1279`; `installer/router.py:911`), and the nav calls the page `Readiness`, not `System Health`. A meeting operator or records clerk cannot follow the steps. The same section sends people to `SECURITY.md`, a repository file they cannot open from the console. Fix: say who can create the bundle and put the contact address in the text.
- [HELP-04] Section `your-first-beta-workflow` tells users: "In System Health, choose Run private rehearsal." No such button exists; the button is `Check broadcast readiness` (`SystemHealthScreen.tsx:1577`), and the screen's own name is `Readiness`/`Safe to broadcast`.
- [HELP-05] `Search this manual` (:131) promises a text search but filters section titles only (:62-63). Fix: placeholder "Filter sections by title" or add real search.
- [HELP-06] Intro text (:98) names a repository file path (`docs/USER-MANUAL.md`); a clerk does not know what that is. Fix: "This is the CivicCast user manual, built into the console so it works without internet."
- [HELP-07] The contents list is one flat 64-entry list that mixes the clerk-level guide (Section A) with engineering sections B and C (environment variables, Alembic migration chain, protocol seams). Nothing labels "start here" or role-based guides (the quick guides are three entries in the middle of Section A). Fix: show Section A by default and fold B/C under "For IT staff".
- [HELP-08] All 45 external links (GitHub, Google Cloud console, etc.) open in the same tab because the sanitizer drops `target`/`rel` (`render.py:123`); the intro promises it "works with no internet connection" but many steps are external. Clicking one replaces the console; a clerk loses their place. Fix: allow `target="_blank" rel="noopener noreferrer"` for http(s) links.
- [HELP-09] Section `roles-and-permissions` / `the-five-role-model` cite `KNOWN_ROLES` and `require_role("...")`; neither name exists in the code (`civiccast/auth/roles.py` has `ALL_OPERATOR_ROLES` and `require_any_role`; searched all `*.py`). The table says support_admin "cannot change records or publish" while code lets it run restore/update/rollback, moderate federation and edit schedule/CG data (see `_shell-navigation-and-roles.md`). Fix: regenerate that section from `_shell-navigation-and-roles.md`.
- [HELP-10] Section `destructive-actions-confirm` lists "Emergency Alert Screen - ... force a slate" among actions that show a confirmation dialog; the code uses a tick-box, not the dialog (`EasScreen.tsx:177-196`). The same section says the Channels feed buttons are covered; Alerts destination delete uses an inline two-step button instead (`AlertsScreen.tsx:612-630`).
- [HELP-11] Section `provider-federation` says to "open ActivityPub in the console" and "See the station's ActivityPub screen for the current on/off switch"; the nav item is `Federation` and the screen has no on/off switch (see `activitypub.md` HELP-01).
- [HELP-12] On a failed load the operator sees developer wording such as "Run: uv run python scripts/render_docsite_manual.py" (`service.py:38-40`). Only reachable on a broken install, but should be a plain "The manual file is missing; reinstall or contact support."
- [HELP-13] There is no link from the Manual page to the PDF/Word copies that exist in `docs/` (`USER-MANUAL.pdf`, `.docx`), and no print layout rule was found for the page (UNVERIFIED: `index.css` print rules not searched).

## Screenshot plan
1. `/help` signed in with the contents list and the top of the manual.
2. Contents list filtered (e.g. `glossary`) and the empty-filter message (`zzz`).
3. A deep link (`#/help#glossary`) landed and highlighted.
4. The same page signed out (nav with fewer entries) - needs a private window.
5. Setup provider card `Read more in the manual` link beside the landed section (optional, for the Setup chapter).

## UNVERIFIED / open questions
- UNVERIFIED: HELP-02 runtime result (click an in-text `#glossary` link in the lab console).
- UNVERIFIED: whether the installed beta.10 payload on the lab station really carries the pre-`9b834a3d` manual (the tag does; the installed copy not inspected).
- UNVERIFIED: whether `/api/version` (shown as the version superscript in the top bar) needs a token; not read.
- UNVERIFIED: print/PDF behavior of the page.

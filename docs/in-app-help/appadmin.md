# App Admin (nav id: appadmin)

Console group: Publish. Spec for the in-app help of the resident-app build screen. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/AppAdminScreen.tsx` unless stated.

## Where the help text lives now
- Heading 265; intro 267-269. No-access note 50. Identity error 277; identity loading 273.
- Build profile: heading 291; App name 294; Tier 295; Store-ready 296; loading 300.
- New build: Platform target 76 ("Select a platform…" 79); Tier 89 ("Select a tier…" 92); button 111 ("Building…"); confirm title 115, body 116, confirm label 117; publish-operator note 313.
- Build history: heading 320; error 324; empty 328; row text 335; Download 344.
- Store submissions: heading 353; offline note 355; error 360; empty 364; row fields Version name 167, Package ID 171, Published URL 175; Save 197.
- Action errors 232, 241, 254. Platform and tier words: `screens/app-admin-format.ts:35-37,51-58`.
- Role gate: `components/shell/Sidebar.tsx:169`; `civiccast/app_platform/build_router.py:55-56,148,178,230,270,282`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Build the OTT app shells for each platform and track their store submissions. Apps read the station config at runtime — branding + content update without a rebuild." | Intro | :267-269 |
| "Build profile": "App name", "Tier", "Store-ready: yes/no" (read-only; no pointer to where they change) | Section | :291-296 |
| "Platform target" (values shown as `web pwa`, `roku`, `tvos`, `fire tv`, `android tv`, `android mobile`, `ios ipados`) | Drop-down | :76; app-admin-format.ts:35-37 |
| "Tier" (unbranded / branded) | Drop-down | :89 |
| "Queue build" / "Building…" | Button | :111 |
| "Queue a {platform} build ({tier} tier)?" / "The build runs on this machine using the station app build toolchain and appears in Build history when it finishes." | Confirm dialog | :115-116 |
| "Queueing a build requires the setup admin role." | Publish operator note | :313 |
| "No builds yet." ; row "{time} · sha {12 characters} · {who}" | Build history | :328, 335 |
| "CivicCast makes no calls to app stores — record submission status here after submitting offline." | Store submissions | :355 |
| "No submissions tracked yet." | Store submissions empty (permanent on a fresh station) | :364 |
| "App build tooling is not configured in this runtime. Meeting capture and scheduled recording are unaffected; app-shell builds are optional and require the station app build toolchain." | Server error | `app_platform/build_router.py:57-61` |

## What the screen really does
It builds a generic starter package of the resident app for web, Roku, Apple TV, Fire TV, Android TV, Android phones and tablets, and iPhone and iPad, on the station's own computer. The build runs inside a single web request: the button reads Building… with no progress or time estimate, and the page must stay open. Each finished build is saved in Build history with a Download button. Tier (unbranded or branded) only labels the record; the build steps do not read it or the station settings. The apps read the station's name and branding from the station when they run (stated in the app shell's README; not tested in a running app). CivicCast never contacts an app store; someone technical must still sign each package and submit it. App name, Tier and Store-ready in the Build profile are read-only here and are changed on the Channels screen; Store-ready is only a flag. The Store submissions notebook has no way to add a row, so it stays empty unless IT staff create one through the programming interface. Setup admin and publish operator can open the screen; only setup admin can start a build.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "OTT app shells", "tier", "build profile", "store-ready" | Never defined | misleading |
| HELP-02 | Tier unbranded / branded | Only labels the record; same build either way (`build_orchestrator.py:101-128`; `build-targets.mjs` has no tier reference) | misleading |
| HELP-03 | "appears in Build history when it finishes" | Page waits on "Building…" with no progress; duration UNVERIFIED | misleading |
| HELP-04 | "No submissions tracked yet." | No control adds a row; the section is a dead end (`build_store.py:79-83`) | blocks work |
| HELP-05 | Build profile read-only | Does not say it is changed on the Channels screen | misleading |
| HELP-06 | "update without a rebuild" | Store review is separate; not tested in a running app | misleading |
| HELP-07 | "Store-ready: yes/no" | A manual flag; tests nothing (`models.py:104`) | misleading |
| HELP-08 | Status drop-down includes "published" | No check that a Published URL exists | cosmetic |
| HELP-09 | "sha {12 characters}" | Unexplained | cosmetic |
| HELP-10 | Lowercase `tvos`, `ios ipados`, `web pwa` | Not people words | cosmetic |
| NEW-1 | Build profile shows "Loading…" if the config request fails | Errors are not shown, so it can read "Loading…" forever (inventory States; `:292-301`) | misleading |

## Proposed text
What this is for (new, under heading): "Builds a starter app package so residents can watch your station on a phone or a TV box. It does not put any app in any app store."
Who can use it (new): "Setup admin or publish operator can look and download. Only a setup admin can start a build."
Warning (new, top of page): "Someone technical must still sign each package and submit it to the app store. CivicCast never contacts a store. The package is a generic starter. A Store-ready mark is only a note and tests nothing."
Intro: "OTT apps are viewing apps for Roku, Apple TV, Fire TV, Android and iPhone/iPad. This screen builds a basic starter package for one platform. The apps read your station's name and branding from the station when they run. In testing we could not confirm this in a running app."
Build profile note (new): "Change App name, Tier and Store-ready on the Channels screen. Store-ready is a note someone set; it tests nothing."
Platform names: "Web app (PWA)", "Roku", "Apple TV (tvOS)", "Fire TV", "Android TV", "Android phone and tablet", "iPhone and iPad (iOS)".
Tier helper: "In beta.10 unbranded and branded only change the label on the build record. The package is the same."
Confirm dialog: "Build the {platform} app? The build runs on this computer and can take several minutes. Keep this page open until it finishes. The result appears in Build history."
Building state: "Building… do not close this page."
Publish operator note: keep, add "You can still look at builds and download them."
SHA tooltip: "A fingerprint of the file. If you pass the ZIP to someone else, they can compare it to check it was not changed."
Store submissions empty: "No submissions tracked yet. In beta.10 this notebook cannot be started from this screen; ask your IT person." After fix: "Add a platform to start tracking."
Status helper: "For your notes only. CivicCast does not check the store."
Tooling error (replace): "This computer does not have the app build tools. Meeting recording and scheduled recording are not affected. Ask your IT person."
Download error: "The file is missing from the station computer. Build again."

## Notes for the coder
- Edit `AppAdminScreen.tsx`, `app-admin-format.ts`; server texts in `civiccast/app_platform/build_router.py`.
- Tests that pin strings (verified by grep): `screens/AppAdminScreen.test.tsx` ("Queueing a build", "Request failed"). "Build the OTT", "No submissions tracked" and "Select a platform" are not pinned.
- Code fixes, not text fixes: an Add platform control or default rows for submissions (HELP-04); show config load errors in Build profile (NEW-1); make the build a background job with progress (HELP-03); either make Tier change the build or remove it (HELP-02); URL check for the Published status.
- UNVERIFIED in the inventory: build duration; whether `node` ships with the installed product; what is in each platform ZIP; whether the shells vary by tier; run-time branding in a real app.

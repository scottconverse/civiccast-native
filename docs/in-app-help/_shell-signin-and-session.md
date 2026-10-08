> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Sign-in, sign-out and session messages (nav id: _shell-signin-and-session)

A shared surface, not a screen. There is no separate sign-in page: sign-in lives on First Setup (`#/setup`; `/login` and `/sign-in` redirect there). The cards themselves are specified in `setup.md`; this file covers sign-out, the token rules, and the error texts any screen can show. Manual authority: `docs/manual/src/11-signing-in.md`.

## Where the help text lives now
`civiccast/apps/portal-operator/src/` : `components/shell/TopBar.tsx` (Sign out), `components/AuthRequiredState.tsx`, `api/client.ts` (error rewrites), `queryClient.ts` (the 401 handler), `auth/recoveryKitGate.ts`, `App.tsx` (redirects), `screens/SetupScreen.tsx` (cards). Server texts: `civiccast/auth/roles.py`, `auth/router.py`, `installer/router.py`. Lines confirmed by opening each file (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Sign out" / "Signing out…" | top-bar button | TopBar.tsx:205 |
| "Sign out of this browser" | button tooltip | TopBar.tsx:188 |
| "Save or print your recovery kit and confirm it on First Setup before leaving that screen." | tooltip on the disabled button and on every greyed nav row | recoveryKitGate.ts:133 |
| "<display name> / <role names>" (hover and screen-reader text of the initials badge); "No roles"; "Operator" | badge | TopBar.tsx:148-159 |
| "Could not verify your <staff identity> (<detail>). Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then retry once the local API is running." | any screen whose identity check fails | AuthRequiredState.tsx:8-10 |
| "Sign in with the local station admin account, then try again." | rewrite of "missing authorization header" | api/client.ts:383-390 |
| "Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again." | 429 rewrite | api/client.ts:422-427 |
| "Request failed: <status> <statusText>" | generic fallback | api/client.ts:563, 599, 911 |
| "Staff identity is required for this action." | server 401 | civiccast/auth/roles.py:90 |
| "This action requires one of these CivicCast roles: <raw role ids>." | server 403 | civiccast/auth/roles.py:96-98 |
| "Signed out of this browser. This staff token is configured by the station environment and cannot be revoked here; rotate CIVICCAST_STAFF_TOKENS to retire it." | sign-out response for env-configured tokens, not shown to users | civiccast/auth/router.py:129-134 |
| "You were signed out" + "This browser's console session is no longer valid — most often because it was the oldest session and was removed to stay under the station's concurrent-session limit ... Sign in below to continue where you left off." | notice set by the 401 handler | queryClient.ts:60-83 (flag), SetupScreen.tsx:1764-1770 |
| "This browser's console sign-in is no longer valid"; "Sign in again" | stale-token card | SetupScreen.tsx:1668-1681 |
| "The station is cooling down after too many requests"; "Too many sign-in attempts from this station. Wait N seconds, then try again with the correct password, or use a printed recovery code." | 429 on sign-in | SetupScreen.tsx:1696; installer/router.py:1092-1095 |
| "First setup can only be done from the station computer itself" | 403 card, also shown for sign-in and recovery | SetupScreen.tsx:1730-1734 |

## What the screen really does
Sign-in is a username and password (or one of 8 one-time recovery codes) typed on First Setup, in a browser running on the station computer. The station hands the browser a private pass (the "console token"), which the browser keeps in both `localStorage` and `sessionStorage` under `civiccast.staffToken` and sends with every request. It has no expiry time in the code searched; it lasts until Sign out, until a 401, or until it is the oldest of the 20 sessions the station keeps. Sign out ends only this browser's session and always clears the pass here, even if the server call fails. Closing the browser does not sign you out. The console has no screen to add people, give roles or paste a token: the first admin holds all five roles.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| SHELL-07 | The only sign-in sits under the page title "First setup" | A returning user lands on a page about creating an admin | blocks work |
| SHELL-08 | "First setup can only be done from the station computer itself" (SetupScreen.tsx:1730) | Shown to anyone signing in or recovering from another computer; nothing says the console works only at the station computer or in a remote session on it (installer/router.py:1467, 1485) | misleading |
| SHELL-09 | AuthRequiredState: "Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link" | Both are retired (installer/router.py:1213-1216); the real step is Admin sign-in on First Setup | blocks work |
| SHELL-10 | No mention that the token is kept in `localStorage` | Closing the browser does not sign out; on a shared computer the next person is signed in as you | misleading (security) |
| SHELL-11 | "Sign out" is hidden until the identity check succeeds and is disabled with a tooltip only during the kit hold (TopBar.tsx:188-205, 219) | Keyboard and screen-reader users get no visible reason | cosmetic |
| SHELL-12 | "requires one of these CivicCast roles: meeting_operator, setup_admin" | Raw ids; the console has no screen to grant a role, so the message gives no next step | misleading |
| SHELL-13 | "authenticate with the staff API" | "Staff API" is jargon | cosmetic |
| NEW-1 | "Sign in below to continue where you left off." (SetupScreen.tsx:1770) | The page you left is restored only when a bounce set `returnTo`; otherwise sign-in lands on Readiness (App.tsx:135-144) | cosmetic |
| NEW-2 | The 401 and 403 sentences ("Staff identity is required...", "requires one of these CivicCast roles") are server text with no console wording around them | Any screen can show them with no instruction | misleading |

## Proposed text
- **Who can use this:** anyone at the station computer. Add to the sign-in card: "Sign in only works in a browser on the station computer, or inside a remote session on it."
- **Sign out tooltip:** "Sign out of this browser only. Other browsers and computers stay signed in. Closing the browser does not sign you out."
- **Kit-hold tooltip:** keep. Add a visible line under the top bar while the hold is active: "Sign out is off until you confirm the recovery kit on First Setup."
- **AuthRequiredState:** "CivicCast could not confirm who you are (<detail>). Open First Setup and sign in with the admin username and password from your recovery kit. If the page does not load at all, ask your IT person whether CivicCast is running." After fix: add a button "Go to sign-in" that opens the sign-in page.
- **401 rewrite (client.ts):** "You are not signed in. Open First Setup and sign in."
- **403 role message:** "You do not have the role this needs: <Setup admin, Meeting operator>. Ask your station admin. In this version roles are set by IT staff, not in the console." Map ids with `ROLE_LABELS` (auth/roles.ts:6-12) in `client.ts`, or change `roles.py:96-98` to emit labels.
- **429 text:** "Too many failed sign-in attempts from this computer. Wait N seconds, then try again."
- **Stale-token and signed-out cards:** see `setup.md` (same cards).
- **Shared-computer tip under Sign in:** "On a shared or borrowed computer, click Sign out before you leave."
- After fix: show the signed-in station name in the sidebar profile card and a "Signed in as <name>" line in the top-bar tooltip; add an expiry or "last used" time if tokens gain one.

## Notes for the coder
- Files: `AuthRequiredState.tsx` (shared by Station Profile, AI Models, Custom Fields, Emergency Alerts, Commissioning), `TopBar.tsx`, `client.ts`, `SetupScreen.tsx`, `civiccast/auth/roles.py`.
- Pins: `SetupScreen.test.tsx` ("You were signed out", "Routine sign-in", "console token"); `SetupScreenLoopbackDenied.test.tsx` and `e2e/setup-loopback-only.spec.ts` (403 heading); `src/queryClient.test.ts`, `AppRecoveryKitGate.test.tsx`, `e2e/auth-redirect.spec.ts` (redirects). Grep tests and e2e for any old wording before changing it.
- Code fix needed (not text): a real sign-in route (SHELL-07); roles shown as labels from the server (SHELL-12); an entry for tokens issued by `civiccast token issue` (UNVERIFIED how such a token reaches the browser; no paste field exists); optional token expiry.

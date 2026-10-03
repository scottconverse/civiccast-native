# Shell: sign-in, token handling, sign-out, session rules  (shared surface)
Source files (under `civiccast/apps/portal-operator/src/`): `App.tsx`, `routes.ts`, `api/client.ts` (:294-431, :500-572, :691), `queryClient.ts`, `auth/recoveryKitGate.ts`,
`components/shell/TopBar.tsx` (:162-222), `components/AuthRequiredState.tsx`, `screens/SetupScreen.tsx` (sign-in card :1583-1639, recovery :1817-1933, notices :1659-1800).
Server: `civiccast/auth/{middleware,tokens,router,rate_limit}.py`, `civiccast/installer/router.py` (:1066-1100, :1211-1294, :1352-1500), `installer/station_state.py` (:76, :795-870).
Who can do it: anyone at the station computer. There is no separate login page: **sign-in lives on the `First Setup` screen** (`/setup`); `/login` and `/sign-in` redirect there (`routes.ts:63-66`).

## What it is for
Explains how an operator proves who they are to the console, where the proof (a "console token") is kept, what happens when it stops working,
and how to sign out. Roles come from the token (see `_shell-navigation-and-roles.md` section 3).

## What the user sees
- **Fresh station, nobody signed in:** any URL except `/setup` and `/help` redirects to `#/setup` (`App.tsx:234-238`); the screen shows `First setup` (create the first admin). After the first admin exists it shows `Setup complete` + the sign-in cards below.
- **Setup complete, signed out:** header `First setup` / "Create the station identity, first local admin, and recovery kit before a public meeting." then, in order: (optional) notice `You were signed out`; (optional) `Recovery kit never confirmed`; card `Setup complete` ("`<station>` already has a first admin and recovery kit." / "Sign in with the local admin password if this browser lost its console token."); card `Admin sign-in`; card `Use recovery code`.
- **Signed in:** top bar shows initials badge and `Sign out`; sign-in lands on `#/health` (Readiness), or on the page the person was bounced from (`App.tsx:135-144`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Admin username`, `Admin password`, `Sign in` | Routine sign-in. Text: "Routine sign-in — use this every time, with the username and password from your printed or saved recovery kit. Creates a fresh console token for this browser without touching any other browser or device already signed in." | `POST /api/setup/login` -> returns `operator_console_token` | none (public, **loopback only**) | Button disabled until both fields filled. Error shown in a red alert: server text e.g. "Invalid admin username or password." |
| `Admin username`, `Recovery code`, `New admin password`, `Confirm new admin password`, `Recover account` -> `Confirm — consume recovery code` | Emergency: burns one of 8 one-time codes and sets a new password | `POST /api/setup/recover` | none (loopback only) | Two clicks (first click arms and shows "This permanently consumes one recovery code — only 8 exist for this station. Click Recover account again to confirm."); new password needs 12+ characters and a matching confirmation ("Passwords do not match."). Text: "Emergency only — if you have the admin password, use Admin sign-in instead. This permanently consumes one of your 8 printed codes and immediately sets a new admin password. Every other browser or device already signed in stays signed in." Autofill is switched off on this form |
| `Sign in again` (in stale-token card) | Forgets the dead token and re-reads setup state | clears browser storage, refetch | none | Card title "This browser's console sign-in is no longer valid"; text "The station rejected the console token this browser was still sending (`<detail>`). Nothing is wrong with the station. Sign in again with the admin username and password from your recovery kit." |
| `Try again` (429 card) | Re-reads setup state | refetch | none | Card title "The station is cooling down after too many requests"; says sign-in is counted separately so the form below still works |
| `I found the kit — it is stored safely` | Tells the station the recovery kit exists | `POST /api/setup/recovery-kit/acknowledge` | `setup_admin` (server) | Shown only when the kit was never confirmed |
| top bar `Sign out` (`Signing out…`) | Ends **this browser's** session only | `POST /api/staff/auth/sign-out`, then always clears the stored token, drops cached identity, goes to `#/setup` | any signed-in token; button visible only after the identity check succeeded (`TopBar.tsx:219`) | Disabled while the recovery kit is unconfirmed (tooltip = kit message). Tooltip `Sign out of this browser`. Even if the server call fails the local sign-out still runs |

## States
| State | What happens / text |
|---|---|
| No token, protected page | redirect to `#/setup` (remembers the page as `returnTo`) |
| Token rejected on any screen (401) | token deleted from this browser, flag set, shell redirects to `#/setup`, notice `You were signed out`: "This browser's console session is no longer valid — most often because it was the oldest session and was removed to stay under the station's concurrent-session limit after many sign-ins elsewhere, or because the station's sign-in state was reset. Nothing is wrong with the station. Sign in below to continue where you left off." (`queryClient.ts:60-83`, `SetupScreen.tsx:1764-1771`). "Continue where you left off" returns to the page only when the bounce set `returnTo` |
| Too many bad tokens (429, staff API) | `Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again.` (`client.ts:422-427`); server default: 10 failures per 60 s per client address (`auth/rate_limit.py:66-76`); a request with **no** token never counts |
| Too many sign-in attempts (429, setup) | "Too many sign-in attempts from this station. Wait N seconds, then try again with the correct password, or use a printed recovery code." (`installer/router.py:1092-1095`) |
| Opened from another computer | HTTP 403; card `First setup can only be done from the station computer itself`: "This page must be opened in a browser running on the station itself — not in a remote desktop viewer's own separate computer, and not from another computer on the network." `login` and `recover` have the same loopback rule (`router.py:1467,1485`) |
| Identity check fails on a screen | each screen shows its own message; e.g. Emergency Alerts shows `AuthRequiredState` (see `eas.md`) |
| Missing credential text from server | rewritten for people: "Sign in with the local station admin account, then try again." (`client.ts:383-390`) |
| Other errors | `Request failed: <status> <statusText>` plus the server `detail` when it is a string; a network failure shows the browser's own message (e.g. `Failed to fetch`) |

## Typical task flows
1. Routine: open console on the station computer -> `Sign in` with username/password -> lands on Readiness.
2. Lost password: `Use recovery code` -> enter a printed code and a new password -> confirm click -> signed in. Each code works once.
3. Shared computer: `Sign out` before leaving (token is otherwise kept, see rules).
4. First-run kit: after creating the first admin the recovery kit stays on screen, nav and `Sign out` are locked, until the kit is saved/printed and confirmed (`recoveryKitGate.ts`; details in `setup.md`).

## Token and session rules (code facts)
- Token name in browser storage: `civiccast.staffToken`, written to **both** `localStorage` and `sessionStorage` after first-admin setup, sign-in and recovery (`SetupScreen.tsx:1458-1459,1473-1474,1485-1486`). So it survives closing the browser and is shared by all tabs of that browser until `Sign out` or a 401. Read order: localStorage, sessionStorage, then a test-only `window.__CIVICCAST_STAFF_TOKEN__` (`client.ts:355-369`).
- Every API call sends `Authorization: Bearer <token>` (`client.ts:510-514`). If a request returns 401 while a token is stored, the token is dropped at once so stale tokens are not resent (stops lock-outs, `client.ts:294-326`).
- Console tokens have no expiry time in code searched (`station_state.py` stores only `issued_at`); they last until sign-out, revocation, or eviction. The station keeps up to **20** concurrent console sessions and drops the oldest first (`station_state.py:76`). Signing in elsewhere does not sign this browser out.
- Server verifies the token on every `/api/staff/*` request (`auth/middleware.py`); the identity (name + roles) is fetched from `GET /api/staff/auth/me` and cached 30 s (`queryClient.ts:54`).
- Sign-out response (not shown to the user): `signed_out`, `session_revoked` true/false; env-configured tokens cannot be revoked server-side, so only the browser forgets them ("rotate CIVICCAST_STAFF_TOKENS to retire it", `auth/router.py:129-136`).
- Console token vs CLI token: `civiccast token issue|list|revoke|rotate|generate-env` manage API tokens for CLI/headless use (`cli.py:2065-2180`); the console UI has no way to enter one.

## Statuses and words on this screen
`Admin sign-in`, `Use recovery code`, `You were signed out`, `Recovery kit never confirmed`, `Sign in`, `Sign in again`, `Sign out`, `Signing out…`.
Role labels used in the badge tooltip: Setup admin, Meeting operator, Records clerk, Publish operator, Support admin (`auth/roles.ts:6-12`).

## Related settings / env / CLI / API
`/api/setup/{station-state,login,recover,first-admin,recovery-kit/acknowledge,storage}`, `/api/staff/auth/{me,sign-out}`; env `CIVICCAST_STAFF_TOKENS`, `CIVICCAST_AUTH_RATE_LIMIT` (default 10), `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS` (default 60); CLI `civiccast token ...`; browser keys `civiccast.staffToken`, `civiccast.pendingRecoveryKit`, `civiccast.staffSignedOutNotice`.

## Help-text findings
- [SHELL-07] The only sign-in is on a page titled `First setup` (`SetupScreen.tsx:1647`). A returning operator who types `/login` or clicks a bounced link lands on "First setup" and must find `Admin sign-in` below `Setup complete`. Fix: a plain `Sign in` page title when setup is already complete.
- [SHELL-08] The 403 card "First setup can only be done from the station computer itself" (`SetupScreen.tsx:1730-1739`) appears when anyone signs in from another computer, although they are not doing setup. Sign-in and recovery are also loopback-only (`installer/router.py:1467,1485`). Nothing in the manual or the console says the console can only be used at the station computer or through a remote-desktop session. Fix: wording "Sign in only works on the station computer itself" and say what to do.
- [SHELL-09] `AuthRequiredState.tsx:8-10` tells users to "Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link" - both are obsolete (the installer-handoff nonce was retired, `installer/router.py:1213-1216`); the real step is `Admin sign-in` on First Setup.
- [SHELL-10] The token is kept in `localStorage` too, so "close the browser" does not sign out; the console never says so. The manual says "Use it on a shared or borrowed computer" (`managing-sign-in`) but the sign-in card has no "this computer is shared" tip. Fix: one line under `Sign in`.
- [SHELL-11] `Sign out` is hidden until the identity check succeeds and is disabled during the recovery-kit hold with a tooltip only (`TopBar.tsx:188-205`); keyboard/screen-reader users get `aria-disabled` + title but no visible text. Minor.
- [SHELL-12] 403 messages use raw role ids ("meeting_operator, setup_admin") (`roles.py:93-98`); there is no "ask your admin to give you the Meeting operator role" because the console has no screen to grant roles (see roles file).
- [SHELL-13] 429 text for the staff API says "Too many failed attempts to authenticate with the staff API" - "staff API" is jargon; the actionable part ("Wait N seconds") is good.

## Screenshot plan
1. `/setup` signed out on a configured station: `Admin sign-in` + `Use recovery code` cards.
2. Failed sign-in alert ("Invalid admin username or password.").
3. `You were signed out` notice after deleting the token (`Application` storage) and reloading a protected page.
4. Top bar signed in (badge + `Sign out`); hover on badge for roles.
5. The loopback card (open console from a second computer on the lab network if the station is reachable - UNVERIFIED that the lab binds beyond 127.0.0.1).
6. Recovery-code card after first click (armed message). Do not use a real code; the lab station should have a throwaway kit.

## UNVERIFIED / open questions
- UNVERIFIED: that tokens never expire (no expiry found in the files read; `auth/store.py` lifecycle tokens not read for expiry).
- UNVERIFIED: whether the control plane is reachable off-box at all (comment in `installer/router.py` says it binds 127.0.0.1 only).
- UNVERIFIED: what `POST /api/setup/login` returns in `StationAuthResponse` beyond the token (fields not read).
- UNVERIFIED: whether more than one username can exist (only a single first admin was found; no UI to add users).

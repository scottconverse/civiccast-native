# portal-operator - Operator Console (Mode A)

Sprint 0.3 introduced the operator-facing Vite app. v0.4 Slice 2 extended it
with the Live Room for starting, monitoring, and ending a broadcast. The v0.5
captions rung adds the Review queue for caption moderation. The v0.6 rung adds
Summary review for sourced summaries and signed-record export. The app now
includes the shell, asset library, schedule drawer, trim/chapter tools, asset
detail editing, live-broadcast controls, caption review controls, and sourced
summary approval/export controls. In v1.0.0, signed-record export produces a
veraPDF-validated PDF/A-3B artifact with deterministic/local timestamp and
signing authority by default; no real TSA or legal-record claim is made.

Sibling to `portal-public` (the resident-facing VOD portal). Different
audiences, different design priorities: information density and keyboard
shortcuts here; clarity and fast first-frame on the public side. Both share
design tokens.

## Stack

React 19 + TypeScript + Vite + Tailwind v4 + TanStack Query. Mirrors
`portal-public` so a developer who has worked on one can read the other without
learning a new pattern.

## Design System

Tokens are ported from the design package's `tokens.css` and live in
`src/index.css`. The full tree (color, typography, spacing, radii, shadows,
motion, layout dims) is exposed both as CSS custom properties (`--cc-*`) for
direct use and as Tailwind v4 `@theme` mappings (`bg-cc-paper`,
`text-cc-ink`, etc.).

Light theme is the default. Dark mode toggles via `[data-theme="dark"]` on
`<html>`; the TopBar's theme button flips it.

## Dev Startup

The default dev path uses the same installer-managed durable storage as the
operator beta path. When `DATABASE_URL` is unset, CivicCast starts in local
setup mode; the Setup screen prepares the SQLite database under the station
data directory and applies migrations.

```bash
# 1. Start the FastAPI backend.
uv run uvicorn civiccast.app:app --port 8000

# 2. In a second terminal, start the operator app
cd civiccast/apps/portal-operator
npm install
npm run dev
# Vite proxies /api/* to http://127.0.0.1:8000.
```

Open `http://127.0.0.1:5173/#/setup` (or whatever port Vite prints) from the
station computer itself, then choose **Prepare storage** in Setup. First
setup is admitted from loopback only -- no query string or handoff needed.
The operator app will hit the live backend and activate the database without
a server restart.

## Optional Postgres Dev Startup

Technical database work can still point CivicCast at Postgres:

```bash
docker run --rm -d --name civiccast-pg \
  -e POSTGRES_PASSWORD=civiccast \
  -e POSTGRES_DB=civiccast \
  -p 5432:5432 postgres:17
export DATABASE_URL=postgresql+psycopg://postgres:civiccast@localhost:5432/civiccast
uv run alembic upgrade head
uv run uvicorn civiccast.app:app --port 8000
```

## Routes

v1.3 groups the same routes by operator job: Setup, Run Meeting, Review
Records, Publish, and System Health. This is a navigation shell, not RBAC or
SSO. Disabled nav items keep a release badge so operators can see what is
queued without mistaking it for active functionality.

| Mode | Routes |
|---|---|
| Setup | Channel & Settings |
| Run Meeting | **Live**, Today, Schedule |
| Review Records | **Assets**, **Review queue**, **Summary review**, Meetings Archive |
| Publish | Publish, Subscribers |
| System Health | Federation |

## Keyboard Shortcuts

The trim editor supports transport shortcuts. The schedule drawer and trim
editor bind Escape. Card-style radiogroups in Live, Schedule, and Asset Detail
support Arrow, Home, and End navigation.

| Key | Action | Where |
|---|---|---|
| `Left` / `Right` | Step playhead by one frame, 1/29.97 seconds, saved to millisecond precision | trim editor |
| `Shift` + `Left` / `Right` | Step playhead by one second | trim editor |
| `I` | Set IN point at current playhead | trim editor |
| `O` | Set OUT point at current playhead | trim editor |
| `M` | Mark a chapter at the current playhead | trim editor |
| `Home` | Jump to start | trim editor |
| `End` | Jump to end | trim editor |
| Arrow keys | Move between radio cards | live source, schedule mode, retention policy |
| `Home` / `End` | First / last radio card | live source, schedule mode, retention policy |
| `Esc` | Close the trim editor / schedule drawer | both |

While focus is in an `<input>` or `<textarea>`, single-letter shortcuts are
suppressed. Arrow keys and Escape still work for the dialog itself.

In Summary review, sourced-claim timestamp buttons seek the inline transcript
player without stealing focus from review/export actions. If **Approve summary**
has focus and the operator activates a timestamp link, focus returns to
**Approve summary** after the transcript target updates.

## Mobile

The shell switches to a single-column layout below 768px. The TopBar gains a
hamburger button that opens the Sidebar as a drawer overlay with a scrim. The
drawer closes on a tap on the scrim, a tap on any nav item, or pressing Escape.

Per spec section 4.1, every primary workflow works on a phone with one thumb.
The drawer pattern is the canonical CivicSuite shell mobile behavior; Mode B
operators see the same pattern under the CivicSuite chrome.

## v1.3 Operator First Mile

The default landing route is **Setup**. It reads `/api/setup/station-state`,
creates the first local admin through `/api/setup/first-admin`, stores the
one-time operator-console token in browser storage, and displays the recovery
kit exactly once. The **System Health** route reads
`/api/staff/installer/system-health`, opens the resident preview target, and
runs the private first-broadcast rehearsal through
`/api/staff/installer/rehearsal`.

## Build, Lint, And Browser Gates

```bash
npm run build
npm run lint
npm run test:a11y
```

CI: `ci-operator-build` runs lint and build on every push and PR.

## v0.4 Live Room Evidence

- Desktop screenshot: `../../../docs/releases/evidence/v0.4-operator-live-room-desktop.png`
- Mobile screenshot: `../../../docs/releases/evidence/v0.4-operator-live-room-mobile.png`
- Browser gate: `npx playwright test` covers the Live Room flow, source-drop
  slate fallback, serious/critical axe scan, and the shared radio-card keyboard
  behavior across Live, Schedule, and Asset Detail.

## v0.5 Caption Review Evidence

- Desktop screenshot: `../../../docs/releases/evidence/v0.5-caption-review-success-desktop.png`
- Mobile screenshot: `../../../docs/releases/evidence/v0.5-caption-review-success-mobile.png`
- Browser gate: `npx playwright test e2e/caption-review.spec.ts` covers the
  review workflow, loading, empty, error, mutation-error, keyboard filtering,
  and serious/critical axe scan states.

## v0.6 Summary Review Evidence

- Desktop summary screenshot: `../../../docs/releases/evidence/v0.6-summary-review-success-desktop.png`
- Mobile summary screenshot: `../../../docs/releases/evidence/v0.6-summary-review-success-mobile.png`
- Partial/refusal screenshot: `../../../docs/releases/evidence/v0.6-summary-review-partial-mobile.png`
- Signed-record export screenshot: `../../../docs/releases/evidence/v0.6-signed-record-export-desktop.png`
- Browser gate: `npx playwright test e2e/summary-review.spec.ts e2e/signed-records.spec.ts`
  covers loading, success, empty, error, partial/refusal, sourced-claim
  navigation, transcript seeking, focus preservation, actionable copy, browser
  console cleanliness in success flows, signed-record export, and
  serious/critical axe scan states.

## Reference Docs

- Design package: see Scott's design session export.
- Spec section 18.2: shell layout.
- Spec section 18.2a: profile-aware navigation.
- Spec section 4.1: UX non-negotiables.

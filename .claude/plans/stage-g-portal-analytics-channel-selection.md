# Stage G — Public Portal Routing/Playback Analytics + Operator Channel Selection

> Sprint plan stage 7 (final feature stage). Capability gaps:
> "Analytics (frontend): missing — no portal emits events; generated type
> exists but no runtime instrumentation", and the operator Live Room
> hardcodes `CHANNEL_ID = 'gov-ch12'` (`LiveRoomScreen.tsx:37`) — multi-channel
> stations cannot run a live session on any other channel.

**Goal:** The resident portal emits privacy-safe routing (`schedule_browse`)
and playback (`playback_start/heartbeat/complete/error`) events to the
existing hardened public ingest endpoint, and the operator Live Room gets a
real channel selector (fetched channel list, persisted choice) replacing the
hardcoded constant. Backend unchanged — Stage A built the ingest path;
Stage G finally gives it a sender.

**Privacy posture (load-bearing):** events use the Origin-allowlist path (no
keys in the browser), send no `anonymous_session_id` / `hashed_viewer_id`,
and the emitter is fail-silent + self-disabling: the first 403/503 (ingest
not configured for this origin) turns it off for the page lifetime. Analytics
must never affect playback or page behavior.

## Tasks

### G1: portal-public emitter + instrumentation

- `civiccast/apps/portal-public/src/analytics.ts`:
  `emitAnalyticsEvent(name, {channelId, contentId, properties})` —
  POST `/api/public/app/analytics/events` with `AnalyticsEvent` shape
  (`event_id` = `pub-<uuid>`, `app_target: 'web_pwa'`, ISO `occurred_at`),
  fire-and-forget (`catch {}`), module-level disable latch on 403/503.
- `App.tsx`: emit `schedule_browse` on portal load (`{section: 'portal_home'}`)
  and on in-page hash navigation (`{section: <hash>}`); pass
  `analytics={{channelId|contentId}}` into `HlsPlayer` for live
  (channel) and `?manifest=` watch (content) modes.
- `HlsPlayer.tsx`: optional `analytics` prop; `play` (first per source) →
  `playback_start`; 60 s interval while playing → `playback_heartbeat`
  (`{position_seconds}`); `ended` → `playback_complete`; error path →
  `playback_error` (`{reason}` — generic, no URLs).

### G2: operator channel selection

- `LiveRoomScreen.tsx`: replace the `CHANNEL_ID` constant with a labeled
  select fed by `GET /api/public/channels` (already served; no auth), default
  to the stored choice (`localStorage civiccast.liveRoom.channelId`) falling
  back to the first channel / `gov-ch12`; the ingest-plan query and session
  create payload use the selection. Disabled while a session is active
  (channel is fixed once a session exists).

### G3: tests + verification (Node toolchain)

- portal-public Playwright spec `e2e/analytics.spec.ts`: route-intercept the
  ingest endpoint; assert `schedule_browse` fires on load and on section
  navigation with the privacy-safe shape (no session/viewer identifiers);
  assert a portal with ingest disabled (403) stops sending after the first
  response. (Real playback events are exercised manually — Playwright's
  bundled Chromium lacks licensed codecs for HLS video; declared.)
- portal-operator spec: live-room channel selector renders the mocked
  channel list, selection persists across reload, create-session payload
  carries the selected channel.
- Builds + eslint for both portals; full a11y suites stay green.
- CAPABILITIES rows ("Analytics (frontend)" → wired for portal-public with
  scope; operator console not instrumented — say so), CHANGELOG.
- Backend full suite unchanged-green; no OpenAPI change expected.

### G4: result file + commit

`feat(portal): playback analytics and live-room channel selection refs #98`.

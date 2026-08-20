// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Privacy-safe analytics emitter for the resident portal (audit sprint
// Stage G). Sends events to the hardened public ingest endpoint
// (`POST /api/public/app/analytics/events`, Stage A) over the
// Origin-allowlist path — no keys ship in the browser.
//
// Privacy posture (load-bearing):
// - No `anonymous_session_id`, no `hashed_viewer_id`, no identifiers of any
//   kind. Properties are coarse strings/numbers only.
// - Fail-silent and self-disabling: analytics must never affect playback or
//   page behavior. The first 403/503 response (ingest not configured for
//   this origin) disables the emitter for the rest of the BROWSER SESSION
//   (audit ENG-006/QA-003: a per-page-load latch re-paid one 503 + console
//   error on every navigation; the latch now persists in sessionStorage).

export type AnalyticsEventName =
  | 'playback_start'
  | 'playback_heartbeat'
  | 'playback_complete'
  | 'playback_error'
  | 'schedule_browse'

export interface AnalyticsContext {
  channelId?: string | null
  contentId?: string | null
  properties?: Record<string, string | number | boolean>
}

const DISABLE_KEY = 'civiccast.analyticsDisabled'

function readPersistedDisable(): boolean {
  try {
    return window.sessionStorage.getItem(DISABLE_KEY) === '1'
  } catch {
    return false
  }
}

let disabled = readPersistedDisable()

function persistDisable(): void {
  disabled = true
  try {
    window.sessionStorage.setItem(DISABLE_KEY, '1')
  } catch {
    // Storage unavailable (private mode etc.): the in-memory latch stands.
  }
}

function eventId(): string {
  const uuid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`
  return `pub-${uuid}`
}

export function emitAnalyticsEvent(name: AnalyticsEventName, context: AnalyticsContext = {}): void {
  if (disabled) return
  const payload: Record<string, unknown> = {
    event_id: eventId(),
    event_name: name,
    occurred_at: new Date().toISOString(),
    app_target: 'web_pwa',
    properties: context.properties ?? {},
  }
  if (context.channelId) payload.channel_id = context.channelId
  if (context.contentId) payload.content_id = context.contentId
  void fetch('/api/public/app/analytics/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  })
    .then((response) => {
      if (response.status === 403 || response.status === 503) {
        // Ingest is not configured for this origin/deployment; stop trying
        // for the rest of the browser session.
        persistDisable()
      }
    })
    .catch(() => {
      // Network failures are irrelevant to the resident experience.
    })
}

/** Test seam: reset the self-disable latch (used by Playwright specs). */
export function _resetAnalyticsForTests(): void {
  disabled = false
  try {
    window.sessionStorage.removeItem(DISABLE_KEY)
  } catch {
    // ignore
  }
}

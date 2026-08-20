// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * One place that turns backend enums into the words an operator reads.
 *
 * GauntletGate F1 (Major, 2026-07-21). `docs/operator-language-guide.md` pins
 * five readiness phrases so a city clerk never has to parse a machine enum:
 * "Translate them at the product layer before they reach non-technical copy."
 * Two screens did that correctly and said so in a comment; the rest rendered
 * `status.replaceAll('_', ' ')` verbatim, so the same underlying concept read
 * as "Do not broadcast yet" on System Health and as the literal, lowercase,
 * grammatically broken "needs it help" on the Provider setup card one click
 * away. That inconsistency is worse than one wrong label: it teaches the clerk
 * the console's readiness words are unreliable, exactly when they most need to
 * trust them.
 *
 * Two functions, because two different kinds of enum reach the screen:
 *
 * - `readinessLabel()` — for the "can I act?" question. Returns one of the
 *   guide's five sanctioned phrases and nothing else.
 * - `stateLabel()` — for lifecycle values (`archive_pending`, `on_air`,
 *   `dead_letter`) that the readiness table does not govern. It does not
 *   invent vocabulary; it just makes sure no raw snake_case token is ever the
 *   words on screen.
 *
 * Raw enum values still belong in API responses, generated docs, and
 * "Technical detail" disclosures — that is the guide's own carve-out.
 */

/** The five phrases from the guide's Readiness States table. Nothing else. */
export const READINESS_READY = 'Ready'
export const READINESS_CHECK_BEFORE_MEETING = 'Check before meeting'
export const READINESS_DO_NOT_BROADCAST_YET = 'Do not broadcast yet'
export const READINESS_NOT_SET_UP_YET = 'Not set up yet'
export const READINESS_NEEDS_IT_HELP = 'Needs IT help'

export const READINESS_PHRASES = [
  READINESS_READY,
  READINESS_CHECK_BEFORE_MEETING,
  READINESS_DO_NOT_BROADCAST_YET,
  READINESS_NOT_SET_UP_YET,
  READINESS_NEEDS_IT_HELP,
] as const

export type ReadinessPhrase = (typeof READINESS_PHRASES)[number]

/**
 * Backend readiness enums, keyed to the guide's MEANINGS rather than to the
 * spelling in its "Avoid" column.
 *
 * One deliberate call worth naming: the guide lists `blocked` in the Avoid
 * column for "Not set up yet", because that is where stations most often meet
 * the word — an optional provider with no credential. But the Control Room
 * emits `blocked` for a check that stops tonight's broadcast, which is the
 * guide's own definition of "Do not broadcast yet" ("a required check failed
 * for tonight's broadcast"). Mapping it to "Not set up yet" there would
 * understate a blocking failure, so the definition wins over the spelling.
 */
const READINESS_BY_ENUM: Readonly<Record<string, ReadinessPhrase>> = {
  // Ready — required checks passed for the selected action.
  ready: READINESS_READY,
  ok: READINESS_READY,
  pass: READINESS_READY,
  passed: READINESS_READY,
  proof_passed: READINESS_READY,
  verified: READINESS_READY,
  complete: READINESS_READY,
  completed: READINESS_READY,
  // The update/rollback panel's only "nothing to do" value. It never reaches
  // a screen as readiness label text (that panel renders it through
  // stateLabel, not readinessLabel) — this entry exists solely so
  // toneForReadiness() gives it the 'ok' tier instead of falling through to
  // the unknown-status 'warn' default.
  current: READINESS_READY,
  green: READINESS_READY,

  // Check before meeting — something optional or recoverable needs attention.
  needs_attention: READINESS_CHECK_BEFORE_MEETING,
  needs_live_proof: READINESS_CHECK_BEFORE_MEETING,
  needs_input: READINESS_CHECK_BEFORE_MEETING,
  warning: READINESS_CHECK_BEFORE_MEETING,
  warn: READINESS_CHECK_BEFORE_MEETING,
  degraded: READINESS_CHECK_BEFORE_MEETING,
  yellow: READINESS_CHECK_BEFORE_MEETING,

  // Do not broadcast yet — a required check failed for tonight's broadcast.
  blocked: READINESS_DO_NOT_BROADCAST_YET,
  preflight_blocked: READINESS_DO_NOT_BROADCAST_YET,
  fail: READINESS_DO_NOT_BROADCAST_YET,
  failed: READINESS_DO_NOT_BROADCAST_YET,
  failed_needs_action: READINESS_DO_NOT_BROADCAST_YET,
  proof_failed_redaction: READINESS_DO_NOT_BROADCAST_YET,
  error: READINESS_DO_NOT_BROADCAST_YET,
  red: READINESS_DO_NOT_BROADCAST_YET,

  // Not set up yet — optional provider or feature has no credential or proof.
  not_set_up: READINESS_NOT_SET_UP_YET,
  not_configured: READINESS_NOT_SET_UP_YET,
  credential_or_secret_required: READINESS_NOT_SET_UP_YET,
  not_started: READINESS_NOT_SET_UP_YET,
  not_tested: READINESS_NOT_SET_UP_YET,
  not_applicable: READINESS_NOT_SET_UP_YET,
  skipped_optional: READINESS_NOT_SET_UP_YET,

  // Needs IT help — the next step requires admin, shell, certificate,
  // database, or service work.
  needs_it_help: READINESS_NEEDS_IT_HELP,
  hardware_required: READINESS_NEEDS_IT_HELP,
}

/**
 * Translate a backend readiness enum into operator words.
 *
 * An unrecognised value falls back to `stateLabel` — the honest sentence-cased
 * form of whatever the backend actually said — and NOT to a readiness phrase.
 *
 * The first draft of this function defaulted unknowns to "Check before
 * meeting". Running the real console immediately showed why that is wrong:
 * the restore proof checklist sends `pending` ("will be checked during the
 * rehearsal"), and ten rows in a column all claimed something needed
 * attention before a meeting. Nothing did. A translation table must never
 * invent a readiness verdict the backend never made; when it does not know,
 * it says what it was told.
 */
export function readinessLabel(status: string | null | undefined): string {
  if (!status) return READINESS_NOT_SET_UP_YET
  return READINESS_BY_ENUM[status.trim().toLowerCase()] ?? stateLabel(status)
}

/** True when the table recognises the value — used by tests, not by screens. */
export function isKnownReadinessStatus(status: string): boolean {
  return status.trim().toLowerCase() in READINESS_BY_ENUM
}

/** The fixed severity tier for each of the guide's five sanctioned phrases. */
const READINESS_TONE: Readonly<Record<ReadinessPhrase, 'ok' | 'warn' | 'err'>> = {
  [READINESS_READY]: 'ok',
  [READINESS_CHECK_BEFORE_MEETING]: 'warn',
  [READINESS_DO_NOT_BROADCAST_YET]: 'err',
  [READINESS_NOT_SET_UP_YET]: 'warn',
  [READINESS_NEEDS_IT_HELP]: 'err',
}

/**
 * The pill color for the same status readinessLabel() turns into words.
 *
 * Reads through readinessLabel() so the two can never disagree: whatever
 * phrase a status maps to, its tone is that phrase's fixed tier. Four
 * call sites used to special-case `needs_attention` (and, on one screen,
 * `needs_it_help`) straight to the red/err tier, so a status that
 * readinessLabel rendered as "Check before meeting" showed up in a
 * "Do not broadcast yet" red pill. An unrecognised status inherits
 * stateLabel's honest fallback text, which is never one of the five
 * phrases, so it renders as 'warn' — attention-worthy without claiming a
 * tier the backend never asserted.
 */
export function toneForReadiness(status: string | null | undefined): 'ok' | 'warn' | 'err' {
  const label = readinessLabel(status)
  return READINESS_TONE[label as ReadinessPhrase] ?? 'warn'
}

/**
 * The pill tone for an outgoing-channel-feed state (`EgressStateRow.state`).
 *
 * On air is good, an errored feed is bad, and everything else (stopped,
 * draining, starting, transitioning, showing slate) is attention-worthy amber
 * -- a feed that is not on air during a meeting is not a neutral,
 * "informational" state. ChannelOpsScreen previously defaulted this to blue
 * (info) while SystemHealthScreen defaulted it to amber (warn), so the same
 * STOPPED feed rendered two different colours (UX-2/UX-6, in the tone
 * dimension). Both screens now route through here so the tone cannot diverge.
 */
export function toneForEgressState(state: string | null | undefined): 'ok' | 'warn' | 'err' {
  const normalized = (state ?? '').toUpperCase()
  if (normalized === 'ON_AIR') return 'ok'
  if (normalized === 'ERROR') return 'err'
  return 'warn'
}

/**
 * The pill tone for a notification channel's last delivery attempt
 * (`AlertChannel.last_delivery_status`).
 *
 * A delivered notification is good, a failed or dead-lettered one is bad, and
 * anything mid-flight (queued, retrying) is attention-worthy amber -- not a
 * neutral grey, because a station operator watching whether alerts are getting
 * out needs the in-between states to read as "not done yet", not "nothing to
 * see". AlertsScreen previously inlined this as `failed || dead_letter ? err :
 * muted`, so a successfully delivered channel and a still-retrying one rendered
 * the same grey. Routed through here so the tone is decided in one place.
 */
export function toneForDeliveryStatus(status: string | null | undefined): 'ok' | 'warn' | 'err' {
  const normalized = (status ?? '').trim().toLowerCase()
  // Backend delivery states: delivered, sent, success (done); failed,
  // dead_letter (bad); pending, queued (in flight).
  if (['delivered', 'sent', 'success', 'ok'].includes(normalized)) return 'ok'
  if (['failed', 'dead_letter', 'error'].includes(normalized)) return 'err'
  return 'warn'
}

/**
 * Sentence-case a lifecycle enum the readiness table does not govern.
 *
 * `archive_pending` -> "Archive pending". Acronyms the operator vocabulary
 * uses are preserved in the casing they are read in.
 */
const LIFECYCLE_OVERRIDES: Readonly<Record<string, string>> = {
  // "Pending" on a proof checklist means the rehearsal has not run, not that
  // something is wrong. Say that, rather than borrowing a readiness word.
  pending: 'Not run yet',
  not_run: 'Not run yet',
  not_started: 'Not run yet',
  on_air: 'On air',
  dead_letter: 'Undeliverable',
  portal_live: 'Live on the portal',
  reach_degraded: 'Reaching fewer places than planned',
  archive_pending: 'Archive pending',
  archive_verified: 'Archive verified',
  pending_ingest: 'Waiting for media',
  needs_changes: 'Needs changes',
  under_review: 'Under review',
  not_configured: 'Not set up yet',
  not_set_up: 'Not set up yet',
  credential_or_secret_required: 'Not set up yet',
  needs_it_help: 'Needs IT help',
  hardware_required: 'Needs IT help',

  // Outgoing-channel-feed lifecycle (EgressStateRow.state). Two screens each
  // kept a byte-for-byte copy of this switch statement instead of routing
  // through here, so the exact bug the readiness table exists to end
  // (two translations of one enum) recurred one enum space over.
  fallback_slate: 'Showing slate',
  starting: 'Starting',
  stopping: 'Stopping',
  draining: 'Finishing current item',
  transitioning: 'Changing source',
  stopped: 'Stopped',
  error: 'Needs attention',

  // Publish dashboard state (PublishDashboardState). The backend used to
  // hand-write these as its own display labels — including the guide's own
  // "Avoid" word ("Reach degraded") for reach_degraded above — instead of
  // routing through this table, so the dashboard's pill and filter chip
  // could each say something different for the same state.
  draft: 'Draft',
  preflight_blocked: 'Preflight blocked',
  publishing: 'Publishing',
  complete: 'Complete',
  failed_needs_action: 'Needs action',
}

export function stateLabel(state: string | null | undefined, fallback = 'Unknown'): string {
  if (!state) return fallback
  const normalized = state.trim().toLowerCase()
  const override = LIFECYCLE_OVERRIDES[normalized]
  if (override) return override
  const words = normalized.replaceAll('_', ' ').trim()
  if (!words) return fallback
  return words.slice(0, 1).toUpperCase() + words.slice(1)
}

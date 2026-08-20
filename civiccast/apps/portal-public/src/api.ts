// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Shared fetch helpers + display formatters for the public portal.

/**
 * Error thrown by fetchJson / postJson / postForm when the server response is
 * not OK. Carries the HTTP `status` so callers can discriminate "absent"
 * (404) from "transient/server" (5xx) without regex-matching on `.message`
 * (S25 T-7 fix). The `message` is the server's `detail` field when present,
 * otherwise the response's status + statusText string.
 */
export class FetchError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'FetchError'
    this.status = status
  }
}

function humanizeField(value: string): string {
  const words = value.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function readableProblemDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== 'object') return readableProblemDetail(item)
        const record = item as Record<string, unknown>
        const message = readableProblemDetail(record.msg ?? record.message ?? record.detail)
        if (!message) return null
        const location = Array.isArray(record.loc) ? record.loc : []
        const field = [...location]
          .reverse()
          .find((part) => typeof part === 'string' && !['body', 'path', 'query'].includes(part))
        return typeof field === 'string' ? `${humanizeField(field)}: ${message}` : message
      })
      .filter((message): message is string => Boolean(message))
    return messages.length > 0 ? messages.join(' ') : null
  }
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    return readableProblemDetail(record.message ?? record.msg ?? record.detail)
  }
  return null
}

async function responseError(response: Response): Promise<FetchError> {
  const parsed = (await response.json().catch(() => null)) as { detail?: unknown } | null
  return new FetchError(
    readableProblemDetail(parsed?.detail) ?? `${response.status} ${response.statusText}`.trim(),
    response.status,
  )
}

export async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw await responseError(response)
  }
  return (await response.json()) as T
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw await responseError(response)
  }
  return (await response.json()) as T
}

export async function postForm<T>(url: string, body: FormData): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body,
  })
  if (!response.ok) {
    throw await responseError(response)
  }
  return (await response.json()) as T
}

// ---------------------------------------------------------------------------
// S26 paywall — public client helpers
//
// These wrap the public paywall endpoints implemented by slice 3 (router).
// All endpoints are unauthenticated POST/GET; the magic-link + checkout flows
// are the ones that change session state on the server. The shape of the
// responses mirrors the contract documented in S26 §4 and slice 3.
// No card data is ever passed through these helpers — `startCheckout` only
// returns a `checkout_url` to Stripe-hosted Checkout (DC-4).
// ---------------------------------------------------------------------------

export interface PaywallAccessResponse {
  allowed: boolean
  reason?: string
}

export async function checkPaywallAccess(
  assetId: string,
  email: string | null,
): Promise<PaywallAccessResponse> {
  const params = new URLSearchParams({ asset_id: assetId, email: email ?? '' })
  return fetchJson<PaywallAccessResponse>(
    `/api/public/paywall/access?${params.toString()}`,
  )
}

export async function requestMagicLink(
  email: string,
  scopeKind: 'asset' | 'series' | 'all',
  scopeId: string,
): Promise<{ sent: true }> {
  return postJson<{ sent: true }>('/api/public/paywall/magic-link', {
    email,
    scope_kind: scopeKind,
    scope_id: scopeId,
  })
}

export async function verifyMagicLink(token: string): Promise<{
  allowed: true
  email?: string
}> {
  const params = new URLSearchParams({ token })
  return fetchJson<{ allowed: true; email?: string }>(
    `/api/public/paywall/verify?${params.toString()}`,
  )
}

export async function startCheckout(
  email: string,
  tierId: string | null,
  scopeKind: string,
  scopeId: string,
): Promise<{ checkout_url: string }> {
  return postJson<{ checkout_url: string }>('/api/public/paywall/checkout', {
    email,
    // Pass `null` when no tier was chosen so the backend can reject
    // deterministically with a clear "tier required" reason. The legacy
    // sentinel `"default"` is still accepted by callers that pass a string.
    tier_id: tierId,
    scope_kind: scopeKind,
    scope_id: scopeId,
  })
}

// UX-2 (S26 gauntletgate): the gate used to hard-code `tier_id="default"`
// with no way for the viewer to see what they were subscribing to. Slice-3
// will expose `GET /api/public/paywall/tiers?asset_id=…` returning the
// per-asset tier list (id + name + interval, optional price label). Until
// that endpoint ships, this helper degrades gracefully: a 404 / 501 /
// empty body resolves to `{ tiers: [] }` and the gate renders a "no plans
// configured" hint instead of the generic "checkout failed" toast.

/** A single subscription tier the viewer can pick from the gate. Shape
 *  intentionally minimal — no pricing strings come from CivicCast (Stripe
 *  is the source of truth); the operator-supplied `name` already carries
 *  the human-facing label ("Basic — $5/month"). */
export interface PaywallTier {
  tier_id: string
  name: string
  interval: 'month' | 'year'
  /** Optional helper hint (e.g. "see Stripe for current price"). The
   *  backend may omit this; the gate falls back to a generic note. */
  price_label?: string
}

export interface PaywallTierListResponse {
  tiers: PaywallTier[]
}

/** Fetch the public tier list for `assetId`. The endpoint is unauthenticated.
 *  Returns `{ tiers: [] }` on 404 / 410 / 501 (the endpoint isn't deployed
 *  yet on this server) so the caller can render the "no plans configured"
 *  empty state instead of a hard error. Network errors and other 4xx/5xx
 *  re-throw so the caller can distinguish "server down" from "no plans". */
export async function listPaywallTiers(
  assetId: string,
): Promise<PaywallTierListResponse> {
  const params = new URLSearchParams({ asset_id: assetId })
  try {
    return await fetchJson<PaywallTierListResponse>(
      `/api/public/paywall/tiers?${params.toString()}`,
    )
  } catch (err) {
    if (
      err instanceof FetchError &&
      (err.status === 404 || err.status === 410 || err.status === 501)
    ) {
      return { tiers: [] }
    }
    throw err
  }
}

export function formatDateTime(value: string | null): string {
  // Audit UX-011: plain language, not data-speak.
  if (!value) return 'Time to be announced'
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

export function formatDuration(seconds: number | null): string {
  if (!seconds) return 'Duration not posted'
  if (seconds < 60) return `${Math.round(seconds)} sec`
  const minutes = Math.max(1, Math.round(seconds / 60))
  return `${minutes} min`
}

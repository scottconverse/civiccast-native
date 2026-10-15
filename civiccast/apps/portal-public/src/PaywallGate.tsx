// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// S26 §6 — Public-portal paywall gate.
//
// No card / PAN data ever rendered or captured here — Stripe-hosted Checkout
// only (DC-4). The "Subscribe" CTA posts to the public checkout endpoint and
// then redirects the browser to the Stripe-hosted URL returned by the server;
// the gate never sees a card number, CVV, or any payment instrument.
//
// Behavior (S26 §6 + slice-5 contract):
// - Default OFF preservation: if the access endpoint returns `allowed=true`
//   (the DC-1 case the backend returns when no paywall is configured) the
//   children render unchanged. The gate is inert.
// - allowed=false: replaces the children with a subscription card carrying
//   a humanized reason, an inline magic-link email form, a Subscribe CTA, and
//   a "Switch email" affordance that clears the session email and reloads.
// - ?token=... on first load: short-circuit the access check, call verify,
//   persist the email returned by the server in sessionStorage, then strip
//   the token from the URL and reload. A 401 surfaces an expired-link notice
//   with a Retry CTA.
// - Loading window: render the children behind a small role="status" flag
//   ("Checking access...") rather than gate-hiding them. The DC-1 case is the
//   overwhelming majority — hiding the player every time the page loads would
//   make the default-off experience worse than the pre-paywall code path.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import {
  FetchError,
  checkPaywallAccess,
  listPaywallTiers,
  requestMagicLink,
  startCheckout,
  verifyMagicLink,
  type PaywallTier,
} from './api'

const EMAIL_STORAGE_KEY = 'civiccast.paywall.email'

interface PaywallGateProps {
  assetId: string
  children: ReactNode
}

// Humanize the backend `reason` codes into copy a viewer can act on. Unknown
// codes fall through to a generic "subscribers only" message rather than
// leaking the raw machine string.
function humanizeReason(reason: string | undefined): string {
  switch (reason) {
    case 'subscription_required':
      return 'This content is for subscribers.'
    case 'sign_in_required':
      return 'Please sign in to continue.'
    case 'expired':
      return 'Your subscription has expired. Renew or sign in again.'
    case 'tier_required':
      return 'A paid tier is required to view this content.'
    default:
      return 'This content is for subscribers.'
  }
}

type VerifyState =
  | { kind: 'none' }
  | { kind: 'pending' }
  | { kind: 'ok' }
  | { kind: 'error'; message: string }

// AccessState is the SETTLED result of an access check; the absence of a
// result keyed to the current (assetId, email) tuple is treated as "loading"
// at the render boundary. This mirrors the MeetingAgendaSidebar pattern and
// keeps the access effect free of a synchronous setState(loading) preamble
// (react-hooks/set-state-in-effect).
interface AccessResult {
  assetId: string
  email: string | null
  state: 'allowed' | 'denied' | 'error'
  reason?: string
}

function readStoredEmail(): string | null {
  // sessionStorage can throw in private-mode Safari; treat any failure as
  // "no email" rather than crashing the whole player.
  try {
    return window.sessionStorage.getItem(EMAIL_STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStoredEmail(email: string): void {
  try {
    window.sessionStorage.setItem(EMAIL_STORAGE_KEY, email)
  } catch {
    /* private mode — drop silently; the access check will re-fail and the
       user will be re-prompted, which is the safe failure mode. */
  }
}

function clearStoredEmail(): void {
  try {
    window.sessionStorage.removeItem(EMAIL_STORAGE_KEY)
  } catch {
    /* see writeStoredEmail */
  }
}

function readTokenFromHash(): string | null {
  // The portal uses hash-based routing (#/watch/{asset_id}). Magic-link URLs
  // append ?token=... to the hash so the server never sees the token. Parse
  // it out of either the search OR the hash, whichever has it.
  const fromSearch = new URLSearchParams(window.location.search).get('token')
  if (fromSearch) return fromSearch
  const hash = window.location.hash
  const qIdx = hash.indexOf('?')
  if (qIdx === -1) return null
  const params = new URLSearchParams(hash.slice(qIdx + 1))
  return params.get('token')
}

function stripTokenFromUrl(): void {
  // Strip the token from both the search string and the hash, then push the
  // cleaned URL so a refresh after a successful verify doesn't re-redeem the
  // (now consumed) token.
  const url = new URL(window.location.href)
  url.searchParams.delete('token')
  const hash = url.hash
  const qIdx = hash.indexOf('?')
  if (qIdx !== -1) {
    const params = new URLSearchParams(hash.slice(qIdx + 1))
    params.delete('token')
    const rest = params.toString()
    url.hash = rest ? `${hash.slice(0, qIdx)}?${rest}` : hash.slice(0, qIdx)
  }
  window.history.replaceState(null, '', url.toString())
}

export function PaywallGate({ assetId, children }: PaywallGateProps) {
  const [accessResult, setAccessResult] = useState<AccessResult | null>(null)
  // Initialize verify lazily based on whether a token is present in the URL,
  // so the verify-pending state is the initial value (no synchronous
  // setState-in-effect needed to enter it).
  const [verify, setVerify] = useState<VerifyState>(() =>
    readTokenFromHash() ? { kind: 'pending' } : { kind: 'none' },
  )
  const [email, setEmail] = useState<string | null>(() => readStoredEmail())

  // Magic-link form state.
  const [emailInput, setEmailInput] = useState('')
  const [linkSubmitting, setLinkSubmitting] = useState(false)
  const [linkSent, setLinkSent] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)

  // Checkout-button state.
  const [checkoutSubmitting, setCheckoutSubmitting] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)

  // UX-2: tier list, fetched after access is denied. `null` while the
  // fetch is in flight or hasn't started; `[]` means "endpoint not built
  // yet on this server or no tiers configured" (fall back to the single
  // Subscribe button + an honest empty-state hint).
  const [tiers, setTiers] = useState<PaywallTier[] | null>(null)
  const [selectedTierId, setSelectedTierId] = useState<string | null>(null)

  // UX-4: refs to the two h2s that own state transitions. When the gate
  // flips into a new branch (denied / verify-error) we call .focus() on
  // the heading so AT users and keyboard-navigation users are landed in
  // the new region instead of stranded in the old one. The h2s are made
  // focusable with tabIndex={-1}, matching the WatchScreen convention.
  const gateHeadingRef = useRef<HTMLHeadingElement | null>(null)
  const verifyHeadingRef = useRef<HTMLHeadingElement | null>(null)

  // 1. ?token=... short-circuit. Runs once; on success persist the verified
  //    email then refetch access. On 401, surface the expired-link notice
  //    and leave the access check unrun (the card carries its own Retry).
  useEffect(() => {
    const token = readTokenFromHash()
    if (!token) return
    let cancelled = false
    verifyMagicLink(token)
      .then((response) => {
        if (cancelled) return
        if (response.email) {
          writeStoredEmail(response.email)
          setEmail(response.email)
        }
        stripTokenFromUrl()
        setVerify({ kind: 'ok' })
      })
      .catch((error: Error) => {
        if (cancelled) return
        const expired =
          error instanceof FetchError && (error.status === 401 || error.status === 410)
        setVerify({
          kind: 'error',
          message: expired
            ? 'This link has expired or already been used. Request a new one.'
            : 'We could not verify that link. Please request a new one.',
        })
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 2. Access check. Skipped while a verify is pending or in an error state
  //    (so the expired-link card isn't replaced by a denied card while the
  //    viewer is still reading it). After a successful verify the access
  //    check runs with the freshly-stored email.
  useEffect(() => {
    if (verify.kind === 'pending' || verify.kind === 'error') return
    let cancelled = false
    const requestEmail = email
    checkPaywallAccess(assetId, requestEmail)
      .then((response) => {
        if (cancelled) return
        if (response.allowed) {
          setAccessResult({
            assetId,
            email: requestEmail,
            state: 'allowed',
          })
        } else {
          setAccessResult({
            assetId,
            email: requestEmail,
            state: 'denied',
            reason: response.reason,
          })
        }
      })
      .catch(() => {
        if (cancelled) return
        setAccessResult({ assetId, email: requestEmail, state: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [assetId, email, verify.kind])

  // 3. Tier-list fetch (UX-2). Only runs when access is settled-denied so
  //    we don't probe the endpoint on the default-off / verify paths. A
  //    404/410/501 maps to `[]` inside `listPaywallTiers` so the gate
  //    degrades to the single-button + "not yet configured" empty state.
  useEffect(() => {
    if (!accessResult || accessResult.state !== 'denied') return
    let cancelled = false
    listPaywallTiers(assetId)
      .then((response) => {
        if (cancelled) return
        setTiers(response.tiers)
        // Default-pick the first tier so a single-tier deployment doesn't
        // force the viewer to click a radio. The viewer can still change
        // before clicking Subscribe.
        if (response.tiers.length > 0) {
          setSelectedTierId((prev) => prev ?? response.tiers[0].tier_id)
        }
      })
      .catch(() => {
        // A non-degradable fetch failure (network error, 5xx). Leave
        // `tiers` at null so onSubscribeClick falls back to the sentinel —
        // the existing behavior, not a regression.
        if (cancelled) return
        setTiers(null)
      })
    return () => {
      cancelled = true
    }
  }, [assetId, accessResult])

  const onMagicLinkSubmit = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const trimmed = emailInput.trim()
      if (!trimmed) {
        setLinkError('Please enter your email.')
        return
      }
      setLinkError(null)
      setLinkSubmitting(true)
      try {
        await requestMagicLink(trimmed, 'asset', assetId)
        setLinkSent(true)
      } catch {
        setLinkError(
          'We could not send a sign-in link right now. Please try again in a moment.',
        )
      } finally {
        setLinkSubmitting(false)
      }
    },
    [assetId, emailInput],
  )

  const onSubscribeClick = useCallback(async () => {
    const target = (emailInput.trim() || email || '').trim()
    if (!target) {
      setCheckoutError('Enter your email above before subscribing.')
      return
    }
    setCheckoutError(null)
    setCheckoutSubmitting(true)
    try {
      // UX-2: tier selection.
      // - If a tier picker is rendered (`tiers != null && tiers.length > 0`),
      //   pass the chosen tier id. The Subscribe button is disabled until
      //   the viewer picks one.
      // - If the tier list is empty (the operator hasn't configured tiers,
      //   or the public tier-list endpoint isn't deployed on this server),
      //   pass `null` so the backend rejects with a clear "tier required"
      //   reason instead of silently honoring the old "default" sentinel.
      // - For back-compat with slice-3 servers that still accept the
      //   sentinel: when `tiers` is null (fetch failed in a way that didn't
      //   degrade to empty), we fall through to the sentinel.
      let tierIdForCheckout: string | null
      if (tiers && tiers.length > 0) {
        tierIdForCheckout = selectedTierId
      } else if (tiers && tiers.length === 0) {
        tierIdForCheckout = null
      } else {
        tierIdForCheckout = 'default'
      }
      const response = await startCheckout(
        target,
        tierIdForCheckout,
        'asset',
        assetId,
      )
      window.location.href = response.checkout_url
    } catch (err) {
      // Distinguish 4xx from 5xx so the viewer sees actionable copy.
      // A 4xx ("tier required", "no plans configured") points at the
      // station; a 5xx is a transient server problem the viewer can retry.
      if (err instanceof FetchError && err.status >= 400 && err.status < 500) {
        setCheckoutError(
          "This station hasn't finished setting up subscriptions yet. Please contact them.",
        )
      } else {
        setCheckoutError(
          'We could not start the subscription flow. Please try again in a moment.',
        )
      }
      setCheckoutSubmitting(false)
    }
  }, [assetId, email, emailInput, tiers, selectedTierId])

  const onSwitchEmail = useCallback(() => {
    clearStoredEmail()
    setEmail(null)
    // Reload so any cached access state is dropped and the access check runs
    // fresh against the anonymous session.
    window.location.reload()
  }, [])

  const onVerifyRetry = useCallback(() => {
    setVerify({ kind: 'none' })
  }, [])

  // UX-4: move focus to the headings on the loading→denied and pending→
  // error transitions. Both refs are guarded so re-renders of the same
  // branch don't steal focus from a viewer who's mid-interaction.
  useEffect(() => {
    if (verify.kind === 'error') {
      verifyHeadingRef.current?.focus()
    }
  }, [verify.kind])
  useEffect(() => {
    if (accessResult?.state === 'denied') {
      gateHeadingRef.current?.focus()
    }
  }, [accessResult?.state])

  // -- RENDER ---------------------------------------------------------------

  // UX-3: during verify-pending, render ONLY the status panel. The previous
  // behavior mounted the player underneath, which could cause a "video
  // starts then disappears" flash if the token turned out to be expired.
  // The verify path only runs when ?token=… is present (the viewer is
  // expecting a sign-in handoff) — a brief hold is cheaper than the flash.
  // We also expose a `aria-busy="true"` wrapper so AT users understand the
  // page is in a transient state, and the copy is more honest ("Signing
  // you in…" -> stays the same, but no player flash).
  if (verify.kind === 'pending') {
    return (
      <div aria-busy="true">
        <div
          role="status"
          aria-live="polite"
          className="rounded-md border border-stone-500/30 bg-[#172018] p-3 text-sm text-stone-200"
        >
          Signing you in&hellip;
        </div>
      </div>
    )
  }

  if (verify.kind === 'error') {
    return (
      <section
        role="alert"
        aria-labelledby="paywall-verify-heading"
        className="rounded-lg border border-amber-300/50 bg-amber-950/30 p-5 text-sm text-amber-50"
      >
        {/* UX-4: tabIndex={-1} lets us .focus() the h2 on the loading→
            error transition so AT users hear the new heading and keyboard
            users are landed in the new region. Matches WatchScreen. */}
        <h2
          ref={verifyHeadingRef}
          id="paywall-verify-heading"
          tabIndex={-1}
          className="text-xl font-semibold"
        >
          Sign-in link unavailable
        </h2>
        <p className="mt-2">{verify.message}</p>
        <button
          type="button"
          onClick={onVerifyRetry}
          className="mt-3 min-h-11 rounded-md border border-amber-200/60 px-4 py-2 text-sm font-semibold text-amber-50 hover:bg-amber-300/10 focus:outline-none focus:ring-2 focus:ring-amber-200"
        >
          Request a new sign-in link
        </button>
      </section>
    )
  }

  // Derive "loading" from "the settled result is not for the current
  // (assetId, email) tuple" — switching assets or signing in implicitly
  // returns the gate to the loading branch without a setState-in-effect.
  const settled =
    accessResult && accessResult.assetId === assetId && accessResult.email === email
      ? accessResult
      : null
  const accessKind: 'loading' | 'allowed' | 'denied' | 'error' = settled
    ? settled.state
    : 'loading'

  if (accessKind === 'loading') {
    // Render children behind a small status flag so default-off (the common
    // case) doesn't briefly hide the player.
    return (
      <div className="relative">
        <span
          role="status"
          aria-live="polite"
          className="mb-2 inline-block rounded bg-stone-800/60 px-2 py-1 text-xs text-stone-300"
        >
          Checking access&hellip;
        </span>
        {children}
      </div>
    )
  }

  if (accessKind === 'allowed') {
    return <>{children}</>
  }

  if (accessKind === 'error') {
    return (
      <p
        role="alert"
        className="rounded-lg border border-red-400/50 bg-red-950/40 p-5 text-sm text-red-100"
      >
        We could not check whether this content is available right now. Refresh
        the page, then contact the station if the problem continues.
      </p>
    )
  }

  // accessKind === 'denied'
  // UX-2: tier-picker rendering decision.
  //   tiers === null  → not loaded (or non-degradable fetch error). Show
  //                     the legacy single Subscribe button; on click
  //                     onSubscribeClick falls back to the "default"
  //                     sentinel for slice-3 servers.
  //   tiers === []    → endpoint returned empty OR was 404/410/501.
  //                     Render an honest "not yet configured" empty state
  //                     and keep the Subscribe button as a contact-the-
  //                     station courtesy (the catch handler distinguishes
  //                     4xx from 5xx in copy).
  //   tiers === [...] → render a radio picker; Subscribe carries the
  //                     chosen tier id.
  const showTierPicker = tiers != null && tiers.length > 0
  const showTierEmptyState = tiers != null && tiers.length === 0
  const subscribeDisabled =
    checkoutSubmitting || (showTierPicker && !selectedTierId)
  return (
    <section
      aria-labelledby="paywall-gate-heading"
      className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-100"
    >
      {/* UX-4: tabIndex={-1} makes the h2 focusable for the
          loading→denied focus move. */}
      <h2
        ref={gateHeadingRef}
        id="paywall-gate-heading"
        tabIndex={-1}
        className="text-xl font-semibold"
      >
        Subscription required
      </h2>
      <p className="mt-2 text-stone-200">{humanizeReason(settled?.reason)}</p>

      <form onSubmit={onMagicLinkSubmit} className="mt-4 space-y-2">
        <label htmlFor="paywall-email" className="block text-sm font-medium">
          Sign in by email
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="paywall-email"
            type="email"
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
            placeholder="you@example.com"
            className="min-h-11 flex-1 rounded-md border border-stone-500/60 bg-[#0f1410] px-3 py-2 text-sm text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            autoComplete="email"
          />
          <button
            type="submit"
            disabled={linkSubmitting}
            className="min-h-11 rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {linkSubmitting ? 'Sending…' : 'Email me a sign-in link'}
          </button>
        </div>
        {linkError && (
          <p role="alert" className="text-sm text-red-200">
            {linkError}
          </p>
        )}
        {linkSent && (
          <p role="status" aria-live="polite" className="text-sm text-emerald-200">
            Check your inbox for a link.
            {/* UX-9: the old "(Local dev: see server logs.)" leaked dev-
                only copy to every public viewer. Gate it on Vite's DEV
                flag so production builds get the clean message and local
                dev keeps the convenience hint. */}
            {import.meta.env.DEV && ' (Local dev: see server logs.)'}
          </p>
        )}
      </form>

      <div className="mt-4 border-t border-stone-500/30 pt-4">
        <p className="text-sm text-stone-200">New here?</p>

        {/* UX-2 tier picker. Radio inputs so the keyboard arrow keys move
            between options; the first tier is preselected for single-tier
            deployments. */}
        {showTierPicker && (
          <fieldset className="mt-3 space-y-2">
            <legend className="text-xs font-medium text-stone-300">
              Choose a plan
            </legend>
            {tiers!.map((tier) => {
              const inputId = `paywall-tier-${tier.tier_id}`
              return (
                <label
                  key={tier.tier_id}
                  htmlFor={inputId}
                  className="flex cursor-pointer items-start gap-2 rounded-md border border-stone-500/30 p-2 text-sm text-stone-100 hover:bg-emerald-300/5"
                >
                  <input
                    id={inputId}
                    type="radio"
                    name="paywall-tier"
                    value={tier.tier_id}
                    checked={selectedTierId === tier.tier_id}
                    onChange={() => setSelectedTierId(tier.tier_id)}
                    className="mt-1"
                  />
                  <span className="flex-1">
                    <span className="font-medium">{tier.name}</span>
                    <span className="ml-2 text-xs text-stone-400">
                      ({tier.interval === 'year' ? 'yearly' : 'monthly'})
                    </span>
                    {tier.price_label && (
                      <span className="ml-2 text-xs text-stone-400">
                        {tier.price_label}
                      </span>
                    )}
                  </span>
                </label>
              )
            })}
          </fieldset>
        )}

        {showTierEmptyState && (
          <p
            role="status"
            className="mt-2 text-xs text-stone-400"
          >
            Tier selection isn&rsquo;t configured yet on this station. Contact
            them for subscription details.
          </p>
        )}

        <button
          type="button"
          onClick={onSubscribeClick}
          disabled={subscribeDisabled}
          className="mt-2 min-h-11 rounded-md border border-emerald-300/60 bg-emerald-300/10 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/20 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {checkoutSubmitting ? 'Opening checkout…' : 'Subscribe'}
        </button>
        {checkoutError && (
          <p role="alert" className="mt-2 text-sm text-red-200">
            {checkoutError}
          </p>
        )}
      </div>

      {email && (
        <p className="mt-4 text-xs text-stone-400">
          Already signed in as{' '}
          <span className="font-mono text-stone-300">{email}</span>?{' '}
          <button
            type="button"
            onClick={onSwitchEmail}
            className="underline focus:outline-none focus:ring-2 focus:ring-emerald-200"
          >
            Switch email
          </button>
        </p>
      )}
    </section>
  )
}

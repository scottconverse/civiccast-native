// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// S26 slice-5 — PaywallGate behavior + DC-1 default-off regression.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { PaywallGate } from './PaywallGate'

// Reset URL state between tests via the location stub installed below.

// jsdom's window.location is a real Location object that rejects .href
// reassignment via setting checkout_url. We swap a stub in per test so we can
// assert reload + href without triggering JSDOM navigation.
let reloadSpy: ReturnType<typeof vi.fn>
let originalLocation: Location

beforeEach(() => {
  originalLocation = window.location
  reloadSpy = vi.fn()
  const stub = {
    _href: originalLocation.href,
    reload: reloadSpy as unknown as () => void,
    replace: vi.fn() as unknown as (url: string | URL) => void,
    assign: vi.fn() as unknown as (url: string | URL) => void,
    get href() {
      return this._href
    },
    set href(value: string) {
      this._href = value
    },
    origin: originalLocation.origin,
    protocol: originalLocation.protocol,
    host: originalLocation.host,
    hostname: originalLocation.hostname,
    port: originalLocation.port,
    pathname: originalLocation.pathname,
    search: '',
    hash: '',
  }
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: stub as unknown as Location,
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: originalLocation,
  })
  window.sessionStorage.clear()
})

// --- fetch mocking helpers --------------------------------------------------

type Handler = (url: string, init?: RequestInit) => Promise<Response> | Response

function installFetchRouter(routes: Record<string, Handler>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    for (const [prefix, handler] of Object.entries(routes)) {
      if (url.startsWith(prefix)) {
        return handler(url, init)
      }
    }
    return new Response(JSON.stringify({ detail: 'no route' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 200 ? 'OK' : status === 401 ? 'Unauthorized' : 'Error',
    headers: { 'Content-Type': 'application/json' },
  })
}

function CHILD() {
  return <div data-testid="player-child">PLAYER</div>
}

// --- tests -----------------------------------------------------------------

describe('PaywallGate', () => {
  it('DC-1 default-off: children render unchanged when access allows', async () => {
    installFetchRouter({
      '/api/public/paywall/access': () => jsonResponse({ allowed: true }),
    })
    const { findByTestId, queryByText } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    // The player is visible after the access check resolves.
    await findByTestId('player-child')
    // The subscription card is NOT in the DOM.
    expect(queryByText('Subscription required')).toBeNull()
  })

  it('denies and shows the subscription card when allowed=false', async () => {
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'subscription_required' }),
    })
    const { findByText, queryByTestId } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    await findByText('Subscription required')
    await findByText('This content is for subscribers.')
    // Children must NOT be rendered while gated.
    expect(queryByTestId('player-child')).toBeNull()
  })

  it('shows a loading flag with role=status during the initial access check', () => {
    let resolve!: (response: Response) => void
    globalThis.fetch = vi.fn(
      () =>
        new Promise<Response>((res) => {
          resolve = res
        }),
    ) as unknown as typeof fetch
    const { getByRole } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    const status = getByRole('status')
    expect(status.textContent).toMatch(/Checking access/i)
    // Resolve to keep React happy on unmount.
    resolve(jsonResponse({ allowed: true }))
  })

  it('magic-link form: submits the email and shows a success message', async () => {
    const magicCalls: Array<Record<string, unknown>> = []
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'sign_in_required' }),
      '/api/public/paywall/magic-link': (_url, init) => {
        magicCalls.push(JSON.parse(init?.body as string))
        return jsonResponse({ sent: true })
      },
    })
    const { findByLabelText, findByRole, findByText } = render(
      <PaywallGate assetId="asset-99">
        <CHILD />
      </PaywallGate>,
    )
    const input = (await findByLabelText('Sign in by email')) as HTMLInputElement
    fireEvent.change(input, { target: { value: 'viewer@example.com' } })
    const submit = await findByRole('button', { name: /sign-in link/i })
    fireEvent.click(submit)
    await findByText(/Check your inbox for a link/i)
    expect(magicCalls).toHaveLength(1)
    expect(magicCalls[0]).toMatchObject({
      email: 'viewer@example.com',
      scope_kind: 'asset',
      scope_id: 'asset-99',
    })
  })

  it('magic-link form: rejects an empty email without calling the API', async () => {
    const magicCalls: number[] = []
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'sign_in_required' }),
      '/api/public/paywall/magic-link': () => {
        magicCalls.push(1)
        return jsonResponse({ sent: true })
      },
    })
    const { findByRole, findByText } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    const submit = await findByRole('button', { name: /sign-in link/i })
    fireEvent.click(submit)
    await findByText('Please enter your email.')
    expect(magicCalls).toHaveLength(0)
  })

  it('verify token: success stores email, strips token, runs access check', async () => {
    window.location.hash = '#/watch/asset-1?token=abc123'
    const accessCalls: string[] = []
    installFetchRouter({
      '/api/public/paywall/verify': () =>
        jsonResponse({ allowed: true, email: 'verified@example.com' }),
      '/api/public/paywall/access': (url) => {
        accessCalls.push(url)
        return jsonResponse({ allowed: true })
      },
    })
    const { findByTestId } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    await findByTestId('player-child')
    expect(window.sessionStorage.getItem('civiccast.paywall.email')).toBe(
      'verified@example.com',
    )
    // The access call was made with the verified email.
    await waitFor(() => {
      expect(
        accessCalls.some((u) => u.includes('email=verified%40example.com')),
      ).toBe(true)
    })
  })

  it('verify token: 401 shows the expired-link message with a retry CTA', async () => {
    window.location.hash = '#/watch/asset-1?token=stale'
    installFetchRouter({
      '/api/public/paywall/verify': () =>
        jsonResponse({ detail: 'expired' }, 401),
      '/api/public/paywall/access': () => jsonResponse({ allowed: true }),
    })
    const { findByText, findByRole } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    await findByText(/This link has expired or already been used/i)
    await findByRole('button', { name: /Request a new sign-in link/i })
  })

  it('Subscribe button POSTs to checkout and sets window.location.href', async () => {
    const checkoutCalls: Array<Record<string, unknown>> = []
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'subscription_required' }),
      '/api/public/paywall/checkout': (_url, init) => {
        checkoutCalls.push(JSON.parse(init?.body as string))
        return jsonResponse({ checkout_url: 'https://checkout.stripe.test/sess_1' })
      },
    })
    const { findByLabelText, findByRole } = render(
      <PaywallGate assetId="asset-7">
        <CHILD />
      </PaywallGate>,
    )
    const input = (await findByLabelText('Sign in by email')) as HTMLInputElement
    fireEvent.change(input, { target: { value: 'buyer@example.com' } })
    const subscribeBtn = await findByRole('button', { name: /^Subscribe$/i })
    fireEvent.click(subscribeBtn)
    await waitFor(() => {
      expect(window.location.href).toBe('https://checkout.stripe.test/sess_1')
    })
    expect(checkoutCalls).toHaveLength(1)
    expect(checkoutCalls[0]).toMatchObject({
      email: 'buyer@example.com',
      tier_id: 'default',
      scope_kind: 'asset',
      scope_id: 'asset-7',
    })
  })

  it('Switch email clears sessionStorage and reloads', async () => {
    window.sessionStorage.setItem('civiccast.paywall.email', 'old@example.com')
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'expired' }),
    })
    const { findByRole } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    const switchBtn = await findByRole('button', { name: /Switch email/i })
    fireEvent.click(switchBtn)
    expect(window.sessionStorage.getItem('civiccast.paywall.email')).toBeNull()
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('network error: surfaces a role=alert with retry-friendly copy', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof fetch
    const { findByRole } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    const alert = await findByRole('alert')
    expect(alert.textContent).toMatch(/Refresh the page/i)
  })

  it('reads a stored email from sessionStorage on mount and passes it to the access check', async () => {
    window.sessionStorage.setItem('civiccast.paywall.email', 'returning@example.com')
    const seen: string[] = []
    installFetchRouter({
      '/api/public/paywall/access': (url) => {
        seen.push(url)
        return jsonResponse({ allowed: true })
      },
    })
    render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    await waitFor(() => expect(seen.length).toBeGreaterThan(0))
    expect(seen[0]).toContain('email=returning%40example.com')
  })

  it('humanizes unknown reason codes to the generic subscribers message', async () => {
    installFetchRouter({
      '/api/public/paywall/access': () =>
        jsonResponse({ allowed: false, reason: 'mystery_code' }),
    })
    const { findByText } = render(
      <PaywallGate assetId="asset-1">
        <CHILD />
      </PaywallGate>,
    )
    await findByText('This content is for subscribers.')
  })
})

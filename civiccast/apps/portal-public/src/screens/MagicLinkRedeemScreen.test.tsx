// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MagicLinkRedeemScreen } from './MagicLinkRedeemScreen'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.replaceState(null, '', '/')
  window.sessionStorage.clear()
})

describe('MagicLinkRedeemScreen', () => {
  it('redeems a series link, stores the verified email, and removes the token from the URL', async () => {
    window.location.hash = '#/redeem?token=sample-token'
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ allowed: true, email: 'viewer@example.com' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ) as unknown as typeof fetch

    render(<MagicLinkRedeemScreen />)

    expect(await screen.findByText(/Your sign-in link is confirmed/)).toBeTruthy()
    expect(window.sessionStorage.getItem('civiccast.paywall.email')).toBe('viewer@example.com')
    expect(window.location.hash).toBe('#/redeem')
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/public/paywall/verify?token=sample-token',
      expect.anything(),
    )
  })
})

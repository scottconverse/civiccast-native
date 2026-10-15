// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import { verifyMagicLink } from './api'
import { MagicLinkVerificationScreen } from './MagicLinkVerificationScreen'

vi.mock('./api', () => ({ verifyMagicLink: vi.fn() }))
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
})

it('redeems a series link, stores the verified email and removes the token from the URL', async () => {
  window.location.hash = '#/paywall/verify?token=secret-token'
  vi.mocked(verifyMagicLink).mockResolvedValue({ allowed: true, email: 'viewer@example.com' })
  const { findByText } = render(<MagicLinkVerificationScreen token="secret-token" />)
  await findByText(/Your link is active/)
  expect(window.sessionStorage.getItem('civiccast.paywall.email')).toBe('viewer@example.com')
  expect(window.location.href).not.toContain('secret-token')
})

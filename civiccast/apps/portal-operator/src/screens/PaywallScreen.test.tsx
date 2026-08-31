// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  AccessGrant,
  PaywallConfig,
} from '../api/client'
import type { StaffIdentityResponse } from '../types/api.generated'

afterEach(cleanup)

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getStaffIdentity: vi.fn(),
  getPaywallConfig: vi.fn(),
  upsertPaywallConfig: vi.fn(),
  updatePaywallConfig: vi.fn(),
  deletePaywallConfig: vi.fn(),
  issueCompGrant: vi.fn(),
  deleteAccessGrant: vi.fn(),
}))

import {
  ApiError,
  deleteAccessGrant,
  deletePaywallConfig,
  getPaywallConfig,
  getStaffIdentity,
  issueCompGrant,
  upsertPaywallConfig,
} from '../api/client'
import { PaywallScreen } from './PaywallScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function config(overrides: Partial<PaywallConfig> = {}): PaywallConfig {
  const now = '2026-06-18T12:00:00Z'
  return {
    config_id: 'paywall-default',
    station_id: 'civiccast-station',
    enabled: false,
    provider: 'stripe',
    tiers: [],
    signing_secret: null,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

function grant(overrides: Partial<AccessGrant> = {}): AccessGrant {
  const now = '2026-06-18T12:00:00Z'
  return {
    grant_id: 'comp-viewer-asset-asset-2026-01-abc',
    station_id: 'civiccast-station',
    email: 'viewer@example.gov',
    scope_kind: 'asset',
    scope_id: 'asset-2026-01',
    granted_via: 'comp',
    subscription_id: null,
    magic_link_token_id: null,
    expires_at: null,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PaywallScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
  vi.mocked(getPaywallConfig).mockResolvedValue(config())
  vi.mocked(upsertPaywallConfig).mockImplementation(async (payload) =>
    config({
      enabled: payload.enabled,
      provider: payload.provider,
      tiers: payload.tiers,
      signing_secret: payload.signing_secret,
    }),
  )
  vi.mocked(deletePaywallConfig).mockResolvedValue(undefined)
  vi.mocked(issueCompGrant).mockImplementation(async (payload) =>
    grant({
      grant_id: payload.grant_id,
      email: payload.email,
      scope_kind: payload.scope_kind,
      scope_id: payload.scope_id,
      expires_at: payload.expires_at ?? null,
    }),
  )
  vi.mocked(deleteAccessGrant).mockResolvedValue(undefined)
})

describe('PaywallScreen role gate', () => {
  it('shows Forbidden for a non setup_admin role and does not fetch config', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/Forbidden/i)).toBeTruthy()
    expect(vi.mocked(getPaywallConfig)).not.toHaveBeenCalled()
  })

  it('renders the config card for a setup_admin role', async () => {
    const { findByLabelText } = renderScreen()
    expect(await findByLabelText('Enable paywall')).toBeTruthy()
  })
})

describe('PaywallScreen default-off banner (DC-1)', () => {
  it('shows the OFF banner by default', async () => {
    const { findByText } = renderScreen()
    expect(
      await findByText(/Paywall is OFF\. All content is public/i),
    ).toBeTruthy()
  })

  it('flips to the ON banner when the operator enables the paywall', async () => {
    const { findByLabelText, findByText } = renderScreen()
    const toggle = (await findByLabelText('Enable paywall')) as HTMLInputElement
    fireEvent.click(toggle)
    expect(
      await findByText(/Paywall is ON\. Tier-based gating active/i),
    ).toBeTruthy()
  })
})

describe('PaywallScreen treats 404 as no-config-yet seed', () => {
  it('renders an empty default form when the GET 404s', async () => {
    vi.mocked(getPaywallConfig).mockRejectedValue(
      new ApiError('Request failed: 404', 404, 'no config yet'),
    )
    const { findByLabelText } = renderScreen()
    const toggle = (await findByLabelText('Enable paywall')) as HTMLInputElement
    expect(toggle.checked).toBe(false)
  })
})

describe('PaywallScreen signing secret', () => {
  // UX-6 (S26 gauntletgate): redundant `aria-label`s were removed from the
  // signing-secret <input>, so it's now labelled solely by its visible
  // <span>Signing secret (HMAC)</span> inside <label htmlFor>. The tests
  // accordingly look up the field by its visible-text label, not by
  // aria-label='Signing secret'.
  it('starts in password mode and toggles to visible on Show', async () => {
    const { findByLabelText } = renderScreen()
    const field = (await findByLabelText(/Signing secret \(HMAC\)/i)) as HTMLInputElement
    expect(field.type).toBe('password')
    fireEvent.click(await findByLabelText('Show signing secret'))
    const field2 = (await findByLabelText(/Signing secret \(HMAC\)/i)) as HTMLInputElement
    expect(field2.type).toBe('text')
  })

  it('fills the signing-secret field with a non-empty base64 value on Generate', async () => {
    const { findByLabelText } = renderScreen()
    const field = (await findByLabelText(/Signing secret \(HMAC\)/i)) as HTMLInputElement
    expect(field.value).toBe('')
    // UX-7: when the field is empty the Generate button is a one-click safe
    // path (no two-step). Click straight through.
    fireEvent.click(await findByLabelText('Generate a new signing secret'))
    const filled = (await findByLabelText(/Signing secret \(HMAC\)/i)) as HTMLInputElement
    expect(filled.value.length).toBeGreaterThan(0)
  })
})

describe('PaywallScreen tier add / remove', () => {
  // UX-5 (S26 gauntletgate): the Tiers section is now `inert` when the
  // paywall is OFF, so these tests flip the enable toggle first to make
  // the section interactive. The labels also changed under UX-6 (the
  // visible <label> text is the source of truth now): "Tier ID (slug)",
  // "Display name", "Stripe price id".
  it('adds a tier with the Stripe price_id and shows it in the table', async () => {
    const { findByLabelText, findByText, getByRole } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    fireEvent.change(await findByLabelText(/Tier ID/i), { target: { value: 'basic' } })
    fireEvent.change(await findByLabelText(/Display name/i), {
      target: { value: 'Basic monthly' },
    })
    fireEvent.change(await findByLabelText(/Stripe price id/i), {
      target: { value: 'price_1ABCDEF' },
    })
    const add = getByRole('button', { name: /^add tier$/i }) as HTMLButtonElement
    await waitFor(() => expect(add.disabled).toBe(false))
    fireEvent.click(add)
    expect(await findByText('Basic monthly')).toBeTruthy()
    expect(await findByText('price_1ABCDEF')).toBeTruthy()
  })

  it('keeps Add tier disabled when the price_id does not start with price_', async () => {
    const { findByLabelText, getByRole } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    fireEvent.change(await findByLabelText(/Tier ID/i), { target: { value: 'basic' } })
    fireEvent.change(await findByLabelText(/Display name/i), {
      target: { value: 'Basic monthly' },
    })
    fireEvent.change(await findByLabelText(/Stripe price id/i), {
      target: { value: 'sku_garbage_id' },
    })
    const add = getByRole('button', { name: /^add tier$/i }) as HTMLButtonElement
    expect(add.disabled).toBe(true)
  })

  it('removes a tier from the local list when Remove is clicked', async () => {
    vi.mocked(getPaywallConfig).mockResolvedValue(
      config({
        enabled: true,
        tiers: [
          { tier_id: 'basic', name: 'Basic', price_id: 'price_1B', interval: 'month' },
        ],
      }),
    )
    const { findByText, findByRole, queryByText } = renderScreen()
    expect(await findByText('Basic')).toBeTruthy()
    fireEvent.click(await findByRole('button', { name: /remove tier basic/i }))
    await waitFor(() => expect(queryByText('Basic')).toBeNull())
  })
})

describe('PaywallScreen save', () => {
  it('PUTs the upsert payload with the local config state', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    const toggle = (await findByLabelText('Enable paywall')) as HTMLInputElement
    fireEvent.click(toggle)
    fireEvent.click(await findByRole('button', { name: /save paywall config/i }))
    await waitFor(() =>
      expect(vi.mocked(upsertPaywallConfig)).toHaveBeenCalledWith(
        expect.objectContaining({
          config_id: 'paywall-default',
          station_id: 'civiccast-station',
          enabled: true,
          provider: 'stripe',
          tiers: [],
        }),
      ),
    )
  })
})

describe('PaywallScreen "Saved." banner clears on further edits', () => {
  it('hides "Saved." as soon as the operator makes another edit after a successful save', async () => {
    const { findByLabelText, findByRole, findByText, queryByText } = renderScreen()
    const toggle = (await findByLabelText('Enable paywall')) as HTMLInputElement
    fireEvent.click(toggle)
    fireEvent.click(await findByRole('button', { name: /save paywall config/i }))
    await waitFor(() => expect(vi.mocked(upsertPaywallConfig)).toHaveBeenCalledTimes(1))
    expect(await findByText('Saved.')).toBeTruthy()

    // react-query's mutation.isSuccess never resets on its own -- editing
    // the form again (without saving) must hide the stale "Saved." banner.
    fireEvent.click(toggle)
    await waitFor(() => expect(queryByText('Saved.')).toBeNull())
  })
})

describe('PaywallScreen delete config 2-step confirm', () => {
  it('does not delete on the first click and does delete on the second', async () => {
    const { findByRole, findByText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /delete paywall config/i }))
    expect(
      await findByText(/Confirming will remove the paywall config entirely/i),
    ).toBeTruthy()
    expect(vi.mocked(deletePaywallConfig)).not.toHaveBeenCalled()
    fireEvent.click(await findByRole('button', { name: /confirm delete paywall config/i }))
    await waitFor(() =>
      expect(vi.mocked(deletePaywallConfig)).toHaveBeenCalledWith('paywall-default'),
    )
  })
})

describe('PaywallScreen comp grant form', () => {
  // UX-5 + UX-6 (S26 gauntletgate): the Grants section is `inert` when the
  // paywall is OFF (flip the toggle first), and aria-labels like
  // "Grant email"/"Grant scope ID"/"Grant scope kind" were dropped in
  // favor of the visible <label> text ("Email", "Scope ID", "Scope kind").
  it('hides the scope_id field when scope_kind is "all"', async () => {
    const { findByLabelText, queryByLabelText } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    expect(await findByLabelText(/^Scope ID$/i)).toBeTruthy()
    fireEvent.change(await findByLabelText(/^Scope kind$/i), {
      target: { value: 'all' },
    })
    await waitFor(() => expect(queryByLabelText(/^Scope ID$/i)).toBeNull())
  })

  it('issues a comp grant and inserts the new row into the table', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    fireEvent.change(await findByLabelText(/^Email$/i), {
      target: { value: 'viewer@example.gov' },
    })
    fireEvent.change(await findByLabelText(/^Scope ID$/i), {
      target: { value: 'asset-2026-01' },
    })
    fireEvent.click(await findByRole('button', { name: /issue comp grant/i }))
    await waitFor(() =>
      expect(vi.mocked(issueCompGrant)).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'viewer@example.gov',
          scope_kind: 'asset',
          scope_id: 'asset-2026-01',
          granted_via: 'comp',
          station_id: 'civiccast-station',
        }),
      ),
    )
    expect(await findByText('viewer@example.gov')).toBeTruthy()
  })

  it('sends an empty scope_id when scope_kind is "all"', async () => {
    const { findByLabelText, findByRole } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    fireEvent.change(await findByLabelText(/^Email$/i), {
      target: { value: 'vip@example.gov' },
    })
    fireEvent.change(await findByLabelText(/^Scope kind$/i), {
      target: { value: 'all' },
    })
    fireEvent.click(await findByRole('button', { name: /issue comp grant/i }))
    await waitFor(() =>
      expect(vi.mocked(issueCompGrant)).toHaveBeenCalledWith(
        expect.objectContaining({
          email: 'vip@example.gov',
          scope_kind: 'all',
          scope_id: '',
        }),
      ),
    )
  })

  it('does not revoke a grant on the first click and does revoke on confirm', async () => {
    const { findByLabelText, findByRole, findByText } = renderScreen()
    fireEvent.click(await findByLabelText('Enable paywall'))
    fireEvent.change(await findByLabelText(/^Email$/i), {
      target: { value: 'viewer@example.gov' },
    })
    fireEvent.change(await findByLabelText(/^Scope ID$/i), {
      target: { value: 'asset-2026-01' },
    })
    fireEvent.click(await findByRole('button', { name: /issue comp grant/i }))
    await findByText('viewer@example.gov')

    // Revoking cuts a real person's access -- it must arm, not fire
    // immediately, matching Delete config / Regenerate secret.
    fireEvent.click(await findByRole('button', { name: /^Revoke grant/i }))
    expect(vi.mocked(deleteAccessGrant)).not.toHaveBeenCalled()
    expect(await findByRole('button', { name: /^Confirm revoke grant/i })).toBeTruthy()

    fireEvent.click(await findByRole('button', { name: /^Confirm revoke grant/i }))
    await waitFor(() => expect(vi.mocked(deleteAccessGrant)).toHaveBeenCalledTimes(1))
  })
})

// DC-4 regression guard: no card / PAN data ever in the rendered DOM. We
// search every input on the screen and assert none of them are number-shaped
// AND adjacent to a "card"-looking label. The screen should never grow such
// a field — Stripe-hosted Checkout owns every card touch.
describe('PaywallScreen DC-4 no-PAN guard', () => {
  it('has no card / PAN input anywhere in the rendered DOM', async () => {
    const { container, findByLabelText } = renderScreen()
    // Ensure the screen has mounted.
    await findByLabelText('Enable paywall')
    const inputs = Array.from(container.querySelectorAll('input'))
    for (const input of inputs) {
      const text = `${input.name} ${input.id} ${input.placeholder} ${input.getAttribute('aria-label') ?? ''}`.toLowerCase()
      expect(text).not.toMatch(/card|pan|cvc|cvv|credit|debit/)
    }
    // No type="number" inputs at all — the form is text + select + radio + date.
    const numberInputs = inputs.filter((i) => i.type === 'number')
    expect(numberInputs.length).toBe(0)
  })
})

describe('PaywallScreen disabled-when-off section copy', () => {
  it('shows the "Save with the enable toggle on" hint when paywall is off', async () => {
    const { findAllByText } = renderScreen()
    const hints = await findAllByText(/Save with the enable toggle on/i)
    // Two sections (Tiers + Grants) each render the hint.
    expect(hints.length).toBeGreaterThanOrEqual(2)
  })

  it('hides the hint after the toggle flips on', async () => {
    const { findByLabelText, queryAllByText } = renderScreen()
    const toggle = (await findByLabelText('Enable paywall')) as HTMLInputElement
    fireEvent.click(toggle)
    await waitFor(() =>
      expect(queryAllByText(/Save with the enable toggle on/i).length).toBe(0),
    )
  })
})

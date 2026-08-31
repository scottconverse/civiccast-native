// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

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
  generateActivityPubStationKey: vi.fn(),
}))

import { generateActivityPubStationKey } from '../api/client'
import type { ActivityPubKeygenResponse, ActivityPubStatusResponse } from '../types/api.generated'
import { DisabledPanel } from './ActivityPubScreen'

function status(overrides: Partial<ActivityPubStatusResponse> = {}): ActivityPubStatusResponse {
  return {
    enabled: false,
    mode: 'disabled',
    handle: 'council',
    base_url: '',
    actor_url: null,
    authorized_fetch: false,
    blocked_instances: [],
    allowed_instances: [],
    followers: { pending: 0, accepted: 0, blocked: 0, rejected: 0, removed: 0 },
    outbox_items: 0,
    delivery_attempts: 0,
    has_station_key: false,
    ...overrides,
  }
}

function keygenResult(overrides: Partial<ActivityPubKeygenResponse> = {}): ActivityPubKeygenResponse {
  return {
    private_key_path: 'C:\\CivicCast\\activitypub-station-key.pem',
    public_key_pem: '-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n',
    handle: 'council',
    base_url: 'https://station.example.gov',
    already_existed: false,
    env_settings: {
      CIVICCAST_ACTIVITYPUB_MODE: 'approval-only',
      CIVICCAST_ACTIVITYPUB_BASE_URL: 'https://station.example.gov',
      CIVICCAST_ACTIVITYPUB_HANDLE: 'council',
      CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH: 'C:\\CivicCast\\activitypub-station-key.pem',
      CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH: '1',
    },
    next_step: 'The station key is ready. Restart CivicCast to turn federation on.',
    ...overrides,
  }
}

function renderPanel(statusOverrides: Partial<ActivityPubStatusResponse> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DisabledPanel status={status(statusOverrides)} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ActivityPubScreen DisabledPanel', () => {
  it('never shows the raw CLI keygen command', () => {
    renderPanel()
    expect(screen.queryByText(/civiccast activitypub keygen/i)).toBeNull()
  })

  it('explains what federation is and that most stations do not need it', () => {
    renderPanel()
    expect(screen.getByText(/most stations do not need this/i)).toBeTruthy()
    expect(screen.getByText(/ActivityPub protocol/i)).toBeTruthy()
  })

  it('links to the manual\'s federation section', () => {
    renderPanel()
    const link = screen.getByRole('link', { name: /read more in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#provider-federation')
  })

  it('generates a station key with a real button instead of a terminal command', async () => {
    vi.mocked(generateActivityPubStationKey).mockResolvedValue(keygenResult())
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /generate station key/i }))
    // A confirmation dialog now stands between the button and the API call.
    fireEvent.click(screen.getByRole('button', { name: 'Generate key' }))

    expect(await screen.findByText('Station key generated.')).toBeTruthy()
    expect(screen.getByText(/restart CivicCast to turn federation on/i)).toBeTruthy()
    expect(screen.getByText('approval-only')).toBeTruthy()
  })

  it('shows an error message, not a crash, when key generation fails', async () => {
    vi.mocked(generateActivityPubStationKey).mockRejectedValue(new Error('disk full'))
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /generate station key/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Generate key' }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/disk full|could not be generated/i)
  })

  it('tells the operator a key already exists before they click generate', () => {
    renderPanel({ has_station_key: true })
    expect(screen.getByText(/a station key already exists on disk/i)).toBeTruthy()
  })
})

// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * The First setup screen when the backend's loopback-only gate denies the
 * request.
 *
 * Formerly `SetupScreenNoNonce.test.tsx`: first setup used to be gated by a
 * one-time installer "setup nonce" handoff, and this file pinned the no-
 * nonce dead-end state. The owner retired the nonce/handoff mechanism
 * entirely -- first setup is now admitted purely by the FastAPI backend
 * checking that the request's peer IP is loopback
 * (`civiccast/installer/router.py`'s `_require_local_setup_request`), which
 * returns a plain 403 with detail exactly "First setup can only be done
 * from the station computer itself." for any non-loopback request. There is
 * no more nonce, no more in-product "I lost my setup link" recovery flow,
 * and no more elevated command-line recovery path.
 *
 * `/api/setup/station-state` and `/api/setup/storage` (both GET and POST)
 * are ALL gated by the same loopback check, so the moment `station-state`
 * resolves without an error, this browser has already proven it is on
 * loopback -- there is no separate "reached the page but can't act" state
 * left to test. `StorageSetupPanel` only ever renders once that GET has
 * already succeeded, so its "Prepare storage" button is unconditionally
 * actionable whenever it is on screen at all.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { SetupScreen } from './SetupScreen'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.localStorage.clear()
  window.sessionStorage.clear()
})

beforeEach(() => {
  window.history.replaceState(null, '', '/operator/#/setup')
  window.sessionStorage.clear()
})

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

const LOOPBACK_DENIED_DETAIL = 'First setup can only be done from the station computer itself.'

/** The request reached the backend, but the peer IP was not loopback. */
function stubNonLocalRequest() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/setup/station-state') {
      return jsonResponse({ detail: LOOPBACK_DENIED_DETAIL }, 403)
    }
    if (url === '/api/setup/storage') {
      return jsonResponse({ detail: LOOPBACK_DENIED_DETAIL }, 403)
    }
    if (url === '/api/staff/auth/me') {
      return jsonResponse({ detail: 'not authenticated' }, 403)
    }
    return jsonResponse({ detail: 'not stubbed' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Storage is genuinely unconfigured, and the station has no admin yet --
 * this browser IS on loopback (the read already succeeded). */
function stubUnconfiguredStationFromLoopback() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/setup/station-state') {
      return jsonResponse({ status: 'not_started', recovery_kit_acknowledged: false })
    }
    if (url === '/api/setup/storage' && method === 'GET') {
      return jsonResponse({
        status: 'not_configured',
        message: 'CivicCast has not prepared a local database yet.',
        next_step: 'Choose Prepare storage in the installer.',
      })
    }
    if (url === '/api/setup/storage' && method === 'POST') {
      return jsonResponse({
        status: 'ready',
        message: 'CivicCast prepared a local database.',
        next_step: 'Create the first admin.',
      })
    }
    if (url === '/api/staff/auth/me') {
      return jsonResponse({ detail: 'not authenticated' }, 403)
    }
    return jsonResponse({ detail: 'not stubbed' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderSetupScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SetupScreen />
    </QueryClientProvider>,
  )
}

function prepareStorageButton(): HTMLButtonElement | null {
  return (
    (screen.queryAllByRole('button').find((element) =>
      /prepare storage/i.test(element.textContent ?? ''),
    ) as HTMLButtonElement | undefined) ?? null
  )
}

async function settledStoragePanel(): Promise<void> {
  await screen.findByText('Durable storage')
  await screen.findByText(/Next step:/)
}

function postsToStorage(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter((call) => {
    const [url, init] = call as [RequestInfo | URL, RequestInit | undefined]
    return String(url) === '/api/setup/storage' && (init?.method ?? 'GET') === 'POST'
  })
}

describe('First setup when the loopback check denies the request', () => {
  it('shows the honest station-only refusal, naming the real requirement', async () => {
    stubNonLocalRequest()
    renderSetupScreen()

    const heading = await screen.findByRole('heading', {
      name: 'First setup can only be done from the station computer itself',
    })
    expect(heading).toBeTruthy()
    expect(screen.getByText(/opened in a browser running on the station itself/i)).toBeTruthy()
  })

  it('never tells the operator to click the button that just failed', async () => {
    stubNonLocalRequest()
    renderSetupScreen()

    await screen.findByRole('heading', {
      name: 'First setup can only be done from the station computer itself',
    })

    // The retired copy told the operator to go back to the installer and
    // click "Open operator console" again -- the exact button that, if
    // they're seeing this screen, already failed to reach loopback. None of
    // that framing, or the retired command-line/in-product recovery paths,
    // may remain.
    expect(screen.queryByText(/open operator console/i)).toBeNull()
    expect(screen.queryByText(/i lost my setup link/i)).toBeNull()
    expect(screen.queryByText(/get a new code/i)).toBeNull()
    expect(screen.queryByText(/--civiccast-restore-setup-handoff/i)).toBeNull()
    expect(screen.queryByText(/for it staff/i)).toBeNull()
  })

  it('points to support for a station believed to be local but refused anyway', async () => {
    stubNonLocalRequest()
    renderSetupScreen()

    await screen.findByRole('heading', {
      name: 'First setup can only be done from the station computer itself',
    })
    expect(screen.getByText(/support.md/i)).toBeTruthy()
    expect(screen.getByRole('link', { name: /open a support issue/i })).toBeTruthy()
  })

  it('never renders a Prepare storage control when the loopback check denied the read', async () => {
    stubNonLocalRequest()
    renderSetupScreen()

    await screen.findByRole('heading', {
      name: 'First setup can only be done from the station computer itself',
    })
    expect(screen.queryByText('Durable storage')).toBeNull()
    expect(prepareStorageButton()).toBeNull()
  })

  it('keeps the plain error banner for a real backend failure, not the loopback refusal copy', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/setup/station-state') {
        return jsonResponse({ detail: 'Internal server error.' }, 500)
      }
      if (url === '/api/setup/storage') {
        return jsonResponse({ status: 'not_configured', next_step: 'Choose Prepare storage in the installer.' })
      }
      if (url === '/api/staff/auth/me') {
        return jsonResponse({ detail: 'not authenticated' }, 403)
      }
      return jsonResponse({ detail: 'not stubbed' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderSetupScreen()

    await screen.findByText(/Could not read setup state\./)
    expect(
      screen.queryByRole('heading', { name: 'First setup can only be done from the station computer itself' }),
    ).toBeNull()
  })
})

describe('First setup from the station itself (loopback check passes)', () => {
  it('offers an always-actionable Prepare storage button -- no more nonce gating', async () => {
    stubUnconfiguredStationFromLoopback()
    renderSetupScreen()

    await settledStoragePanel()

    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    expect(button?.disabled).toBe(false)
  })

  it('clicking Prepare storage issues the POST, with no header or query-string ceremony required', async () => {
    const fetchMock = stubUnconfiguredStationFromLoopback()
    renderSetupScreen()

    await settledStoragePanel()
    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    fireEvent.click(button as HTMLButtonElement)

    await waitFor(() => expect(postsToStorage(fetchMock)).toHaveLength(1))
  })
})

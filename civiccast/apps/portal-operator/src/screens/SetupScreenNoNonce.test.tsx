// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * The First setup screen reached WITHOUT the installer handoff nonce.
 *
 * GauntletGate W-2 (Major) + T2 (Major) — one defect and the coverage gap that
 * let it ship, fixed together.
 *
 * W-2: the screen rendered an ENABLED primary "Prepare storage" button while
 * `POST /api/setup/storage` returns 403 for any request without the installer's
 * one-time nonce. A user who reaches the console directly — a bookmark, a
 * refresh that drops the query string, a typed URL — got a failure where the UI
 * had promised an action. The nonce gate itself is a real security control and
 * is unchanged; offering a control that cannot succeed is the defect.
 *
 * T2: every existing SetupScreen test seeds `?nonce=...` into the URL before
 * rendering, so the no-nonce state — the exact path the walkthrough took — had
 * no coverage at all, and nothing would have failed if it got worse.
 *
 * These tests render with NO nonce anywhere: no query string, no hash query,
 * no sessionStorage.
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
  // No ?nonce= in the search string, none in the hash, none in sessionStorage.
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

/** Storage is genuinely unconfigured, and the station has no admin yet. */
function stubUnconfiguredStation() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/setup/storage' && method === 'GET') {
      return jsonResponse({
        status: 'not_configured',
        message: 'CivicCast has not prepared a local database yet.',
        next_step: 'Choose Prepare storage in the installer.',
      })
    }
    if (url === '/api/setup/storage' && method === 'POST') {
      // The real backend behaviour this screen must stop walking into.
      return jsonResponse(
        {
          detail:
            'Storage setup requires the installer handoff nonce. Open the ' +
            'operator console from the CivicCast installer before preparing storage.',
        },
        403,
      )
    }
    if (url === '/api/setup/station-state') {
      return jsonResponse({ status: 'not_started', recovery_kit_acknowledged: false })
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

/**
 * Wait until the storage query has SETTLED before asserting on the button.
 *
 * Without this, the panel's `disabled={busy}` (busy = isLoading) makes every
 * assertion pass while the query is still in flight -- a green test that
 * proves nothing. The "Next step:" line only renders once storage data has
 * actually arrived, so it is the honest settle signal.
 */
async function settledStoragePanel(): Promise<void> {
  await screen.findByText('Durable storage')
  await screen.findByText(/Next step:/)
}

function postsToStorage(fetchMock: ReturnType<typeof vi.fn>) {
  // Destructure INSIDE the callback: `mock.calls` is typed as `any[][]`, so a
  // destructured tuple parameter fails `tsc -b` (which the repo's build runs)
  // even though `tsc --noEmit -p tsconfig.json` accepts it.
  return fetchMock.mock.calls.filter((call) => {
    const [url, init] = call as [RequestInfo | URL, RequestInit | undefined]
    return String(url) === '/api/setup/storage' && (init?.method ?? 'GET') === 'POST'
  })
}

describe('First setup without the installer handoff nonce', () => {
  it('does not offer an enabled Prepare storage button that is guaranteed to 403', async () => {
    stubUnconfiguredStation()
    renderSetupScreen()

    await settledStoragePanel()

    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    expect(button?.disabled).toBe(true)
  })

  it('leads with the installer instruction instead of a dead action', async () => {
    stubUnconfiguredStation()
    renderSetupScreen()

    const note = await screen.findByRole('note', { name: /installer/i })
    expect(note.textContent).toMatch(/installer/i)
  })

  it('never fires the request that would 403', async () => {
    const fetchMock = stubUnconfiguredStation()
    renderSetupScreen()

    await settledStoragePanel()

    // fireEvent, not element.click(): a raw DOM click on a React button does
    // not reliably run the handler.
    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    fireEvent.click(button as HTMLButtonElement)

    // NOT waitFor(): an assertion that is already true passes on the first
    // check and never re-runs, so it would "prove" no POST happened before the
    // mutation had a chance to fire one. Give it real time, then assert.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(postsToStorage(fetchMock)).toHaveLength(0)
  })
})

describe('First setup WITH the installer handoff nonce', () => {
  it('still offers a working Prepare storage action', async () => {
    // The guard must gate on the nonce, not simply hide the button forever —
    // the installer path is the one that has to keep working.
    window.history.replaceState(null, '', '/operator/?nonce=fresh-setup-nonce#/setup')
    stubUnconfiguredStation()
    renderSetupScreen()

    await settledStoragePanel()

    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    expect(button?.disabled).toBe(false)
  })

  it('clicking Prepare storage really does issue the POST', async () => {
    // The BASELINE for the no-nonce test above. Without this, "no POST was
    // recorded" could just mean the harness never wires clicks to the
    // mutation, and the guard would look proven while doing nothing.
    window.history.replaceState(null, '', '/operator/?nonce=fresh-setup-nonce#/setup')
    const fetchMock = stubUnconfiguredStation()
    renderSetupScreen()

    await settledStoragePanel()
    const button = prepareStorageButton()
    expect(button).not.toBeNull()
    fireEvent.click(button as HTMLButtonElement)

    await waitFor(() => expect(postsToStorage(fetchMock)).toHaveLength(1))
  })

  it('accepts a nonce carried in the hash query, not only the search string', async () => {
    window.history.replaceState(null, '', '/operator/#/setup?nonce=hash-carried-nonce')
    stubUnconfiguredStation()
    renderSetupScreen()

    await settledStoragePanel()

    expect(prepareStorageButton()?.disabled).toBe(false)
  })
})

/**
 * The in-product recovery panel (`HandoffRecoveryPanel`) only renders inside
 * this no-nonce state, so this stub answers `/api/setup/station-state` with
 * the 403 `isSetupHandoffError` shape that puts the recovery panel on
 * screen, then lets `/handoff-recovery/start` answer with a `code_file` that
 * does NOT match the component's hard-coded `C:\ProgramData\...` fallback --
 * the same way a station with `%ProgramData%` relocated would.
 */
function stubHandoffRecoverableStation(codeFile: string) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/setup/station-state' && method === 'GET') {
      return jsonResponse(
        {
          detail:
            'Storage setup requires the installer handoff nonce. Open the ' +
            'operator console from the CivicCast installer before preparing storage.',
        },
        403,
      )
    }
    if (url === '/api/setup/storage' && method === 'GET') {
      return jsonResponse({
        status: 'not_configured',
        message: 'CivicCast has not prepared a local database yet.',
        next_step: 'Choose Prepare storage in the installer.',
      })
    }
    if (url === '/api/staff/auth/me') {
      return jsonResponse({ detail: 'not authenticated' }, 403)
    }
    if (url === '/api/setup/handoff-recovery/start' && method === 'POST') {
      return jsonResponse({ code_file: codeFile, expires_in: 900 })
    }
    return jsonResponse({ detail: 'not stubbed' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('Handoff recovery panel code_file path', () => {
  // Regression coverage for a Codex review finding on PR #415: the panel
  // used to render a hard-coded `C:\ProgramData\...` literal and ignore
  // `startHandoffRecovery`'s `response.code_file` entirely, so a station
  // with `%ProgramData%` relocated pointed the operator at a file that does
  // not exist. See `civiccast.installer.handoff_recovery.recovery_dir` for
  // the backend half (`PROGRAMDATA`-derived, not `C:`-literal).
  it('renders the code_file path returned by the API, not the hard-coded C:\\ProgramData default', async () => {
    const relocatedCodeFile = 'D:\\CustomProgramData\\CivicCast\\setup-recovery\\code.txt'
    stubHandoffRecoverableStation(relocatedCodeFile)
    renderSetupScreen()

    const startButton = await screen.findByRole('button', { name: /i lost my setup link/i })
    fireEvent.click(startButton)

    const codeBlock = await screen.findByText(relocatedCodeFile)
    expect(codeBlock.textContent).toBe(relocatedCodeFile)
    expect(
      screen.queryByText('C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt'),
    ).toBeNull()
  })
})

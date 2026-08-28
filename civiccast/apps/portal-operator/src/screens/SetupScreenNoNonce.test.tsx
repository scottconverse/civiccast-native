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
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

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
function stubHandoffRecoverableStation(
  codeFile: string,
  options: { startResponses?: Array<{ status: number; body: unknown }> } = {},
) {
  const responses = options.startResponses
  let startCallCount = 0
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
      if (responses) {
        const response = responses[Math.min(startCallCount, responses.length - 1)]
        startCallCount += 1
        return jsonResponse(response.body, response.status)
      }
      return jsonResponse({ code_file: codeFile, expires_in: 900 })
    }
    return jsonResponse({ detail: 'not stubbed' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Resolves each queued deferred in order, one per real `fetch` request that
 * matches ``matchesPath`` -- lets a test observe the pending state a mutation
 * is in WHILE its request is still in flight, then release it deliberately. */
function stubHandoffRecoveryWithControlledStart(
  codeFile: string,
  matchesPath: string,
  expiresInSequence: number[] = [900],
): { fetchMock: ReturnType<typeof vi.fn>; releaseNext: () => void } {
  const releases: Array<() => void> = []
  let callCount = 0
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
    if (url === matchesPath && method === 'POST') {
      await new Promise<void>((resolve) => releases.push(resolve))
      const expiresIn = expiresInSequence[Math.min(callCount, expiresInSequence.length - 1)]
      callCount += 1
      return jsonResponse({ code_file: codeFile, expires_in: expiresIn })
    }
    return jsonResponse({ detail: 'not stubbed' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return {
    fetchMock,
    releaseNext: () => {
      const next = releases.shift()
      if (!next) throw new Error('no pending /handoff-recovery/start call to release')
      next()
    },
  }
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

    // The command-line/API recovery path lives inside a de-emphasized "For IT
    // staff" disclosure now (calm "This station hasn't been set up yet"
    // headline up top) -- open it before the button underneath is reachable.
    const disclosure = await screen.findByText('For IT staff: restore setup access')
    fireEvent.click(disclosure)

    const startButton = await screen.findByRole('button', { name: /i lost my setup link/i })
    fireEvent.click(startButton)

    const codeBlock = await screen.findByText(relocatedCodeFile)
    expect(codeBlock.textContent).toBe(relocatedCodeFile)
    expect(
      screen.queryByText('C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt'),
    ).toBeNull()
  })
})

/**
 * Field-test finding (2026-08-28, candidate 9d4477b): a station volunteer
 * who reaches the operator console before the installer hands off to it saw
 * a red "Could not read setup state" alert with admin-only command/code
 * instructions front and center -- owner verdict "I can't hand this to an
 * LPM person." The fix is copy/layout only (isSetupHandoffError's security
 * gate and the recovery mutations it protects are unchanged): the never-
 * set-up-yet state gets a calm headline and points back at the installer,
 * and the IT-only recovery path moves into a de-emphasized disclosure. A
 * genuinely broken setup-state read (a real backend error, not a missing
 * handoff) must keep the red alert -- the code can tell the two apart
 * (`isSetupHandoffError` gates strictly on a 403 whose message mentions
 * "operator console" or "setup"), so this pins that it still does.
 */
describe('First-run funnel copy: never-set-up vs. genuinely broken setup-state read', () => {
  it('shows the calm "hasn\'t been set up yet" headline for the no-handoff 403, not the red error banner', async () => {
    stubHandoffRecoverableStation('C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt')
    renderSetupScreen()

    await screen.findByRole('heading', { name: "This station hasn't been set up yet" })
    expect(screen.queryByText(/Could not read setup state\./)).toBeNull()

    // The IT-only recovery path is present but collapsed by default. jsdom
    // does not implement <details>'s native content-hiding (unlike a real
    // browser -- see e2e/setup-handoff-recovery.spec.ts's openItStaffDisclosure,
    // which proves the visible/collapsed behavior against real Chromium), so
    // this checks the one thing jsdom does model faithfully: the element's
    // own `open` state.
    const disclosure = screen.getByText('For IT staff: restore setup access').closest('details')
    expect(disclosure).not.toBeNull()
    expect((disclosure as HTMLDetailsElement).open).toBe(false)
  })

  it('keeps the red error banner for a genuinely broken setup-state read (not a missing handoff)', async () => {
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
    expect(screen.queryByRole('heading', { name: "This station hasn't been set up yet" })).toBeNull()
  })
})

/**
 * Field bug 2026-08-28: clicking "Get a new code" on a live station produced
 * NO visible response -- no pending indicator, no success confirmation, only
 * a countdown reset a distracted clerk would never notice. The mutation
 * itself worked (same `startHandoffRecovery` call the initial "I lost my
 * setup link" click already uses and already had coverage for), so the
 * defect was purely the panel's silence about its own outcome. These tests
 * pin the fix: a visible pending state while the request is in flight, an
 * explicit timestamped confirmation on success (distinguishing a first issue
 * from a regenerate), and a visible error on failure -- matching the page's
 * existing "never a dead control" standard (see the W-2 doc comment above
 * `HandoffRecoveryPanel`).
 */
describe('Handoff recovery panel visible feedback (field bug 2026-08-28)', () => {
  const codeFile = 'C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt'

  // The recovery panel's own `<form>` is the scope for these assertions:
  // `SetupScreen` also renders an unrelated top-level alert for the mocked
  // `/api/setup/station-state` 403 ("Could not read setup state...") that
  // otherwise collides with a bare `getByRole('alert')`/`getByRole('status')`
  // query and asserts on the WRONG element.
  async function recoveryForm() {
    // `findByLabelText`, not `getByLabelText`: the form (and its "Recovery
    // code" field) only exists once `startHandoffRecovery` has actually
    // resolved and the panel has re-rendered into its 'code-requested'
    // phase -- a synchronous query here would race that.
    const label = await screen.findByLabelText('Recovery code')
    const form = label.closest('form')
    if (!form) throw new Error('recovery form not found')
    return within(form)
  }

  // PR #57 moved the whole IT recovery path (including "I lost my setup
  // link") behind a collapsed "For IT staff: restore setup access"
  // disclosure -- open it first, matching the convention the code_file-path
  // test above and e2e/setup-handoff-recovery.spec.ts's openItStaffDisclosure
  // both already use.
  async function openItStaffDisclosure() {
    const disclosure = await screen.findByText('For IT staff: restore setup access')
    fireEvent.click(disclosure)
  }

  it('shows a pending label on "I lost my setup link" and then an explicit, non-regenerate confirmation', async () => {
    const { releaseNext } = stubHandoffRecoveryWithControlledStart(
      codeFile,
      '/api/setup/handoff-recovery/start',
    )
    renderSetupScreen()
    await openItStaffDisclosure()

    const startButton = await screen.findByRole('button', { name: /i lost my setup link/i })
    fireEvent.click(startButton)

    // Pending state visible WHILE the request is still in flight.
    await screen.findByRole('button', { name: /requesting a recovery code/i })

    releaseNext()

    const form = await recoveryForm()
    const confirmation = await form.findByRole('status')
    expect(confirmation.textContent).toMatch(/a recovery code was written to/i)
    expect(confirmation.textContent).toMatch(/code\.txt/)
    // The FIRST issuance is not a regenerate: no "old code" framing.
    expect(confirmation.textContent).not.toMatch(/old code/i)
  })

  it('clicking "Get a new code" shows a pending state, then an explicit regenerate confirmation with a reset countdown', async () => {
    // First code expires almost immediately; the regenerated one gets the
    // real 15-minute TTL. This makes the reset unambiguous to assert on: if
    // `expiresAt` were NOT actually reset by the second response, the panel
    // would still show "This code has expired" after the wait below instead
    // of a fresh, long countdown.
    const { releaseNext } = stubHandoffRecoveryWithControlledStart(
      codeFile,
      '/api/setup/handoff-recovery/start',
      [1, 900],
    )
    renderSetupScreen()
    await openItStaffDisclosure()

    const startButton = await screen.findByRole('button', { name: /i lost my setup link/i })
    fireEvent.click(startButton)
    // Wait for the mutation to actually reach the fetch call before
    // releasing it -- `mutate()` does not call `mutationFn` synchronously.
    await screen.findByRole('button', { name: /requesting a recovery code/i })
    releaseNext()
    const form = await recoveryForm()
    await form.findByRole('status')

    // Let the short-lived first code actually expire.
    await waitFor(() => expect(form.getByRole('alert').textContent).toMatch(/expired/i), {
      timeout: 3000,
    })

    const getNewCodeButton = form.getByRole('button', { name: 'Get a new code' })
    fireEvent.click(getNewCodeButton)

    // Pending state visible for the REGENERATE click too -- this is the
    // exact control the field report said produced nothing at all.
    await screen.findByRole('button', { name: /requesting a new code/i })
    // The stale code input is not submittable while a fresh code is in flight.
    expect((screen.getByLabelText('Recovery code') as HTMLInputElement).disabled).toBe(true)

    releaseNext()

    await waitFor(() => {
      const confirmation = form.getByRole('status')
      expect(confirmation.textContent).toMatch(/a new code was written to/i)
      expect(confirmation.textContent).toMatch(/old code no longer works/i)
    })
    // The "expired" alert is gone and a fresh, long countdown is back --
    // proof `expiresAt` was actually reset, not just redrawn with stale data.
    expect(form.queryByRole('alert')).toBeNull()
    const refreshedCountdown = await form.findByText(/this code expires in \d+ seconds?/i)
    // Anchored capture, not a bare `/\d+/`: the same paragraph also says
    // "the 8-character code below", and a loose digit match would grab the
    // "8" from that instead of the actual countdown value.
    const refreshedSecondsLeft = Number(
      refreshedCountdown.textContent?.match(/expires in (\d+) seconds?/i)?.[1],
    )
    expect(refreshedSecondsLeft).toBeGreaterThan(890)
  })

  it('shows a visible error, not silence, when "Get a new code" fails', async () => {
    stubHandoffRecoverableStation(codeFile, {
      startResponses: [
        { status: 200, body: { code_file: codeFile, expires_in: 900 } },
        {
          status: 503,
          body: { detail: 'CivicCast could not prepare a setup recovery code: disk is full' },
        },
      ],
    })
    renderSetupScreen()
    await openItStaffDisclosure()

    const startButton = await screen.findByRole('button', { name: /i lost my setup link/i })
    fireEvent.click(startButton)
    const form = await recoveryForm()
    await form.findByRole('status')

    fireEvent.click(form.getByRole('button', { name: 'Get a new code' }))

    const alert = await form.findByRole('alert')
    expect(alert.textContent).toMatch(/disk is full/i)
  })
})

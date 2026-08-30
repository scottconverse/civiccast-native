// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * First-setup form fields must expose their error state programmatically.
 *
 * GauntletGate F2 (Minor). `Field` rendered the validation error visually and
 * announced it once via a sibling `role="alert"`, but never set `aria-invalid`
 * on the input and never pointed `aria-describedby` at the error text — and the
 * error span had no `id` to point at.
 *
 * The practical failure: a clerk types 8 characters into "Admin password" and
 * tabs away. The error is announced once. Later they tab BACK onto the still-
 * invalid field — a screen reader re-announces only the label, because the
 * input never referenced the error. WCAG 2.2 SC 3.3.1 (Error Identification)
 * and 4.1.2 (Name, Role, Value) expect the state to be exposed persistently,
 * not just at the moment it first appears.
 *
 * This is the account-recovery-critical first-run form (admin password +
 * recovery kit) — the one screen where a confused submission costs the most: a
 * locked-out station.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { SetupScreen } from './SetupScreen'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
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

function stubStorageReadyStation() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/setup/storage') {
      return jsonResponse({
        status: 'ready',
        message: 'Local durable storage is ready.',
        next_step: 'Create the first admin.',
      })
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
  window.history.replaceState(null, '', '/operator/#/setup')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SetupScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function inputById(id: string): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>(`#${id}`)
  if (!input) throw new Error(`missing input #${id}`)
  return input
}

async function anInvalidAdminPassword(): Promise<HTMLInputElement> {
  stubStorageReadyStation()
  renderSetupScreen()
  await screen.findByText('Storage ready')

  const password = inputById('admin_password')
  fireEvent.change(password, { target: { value: 'tooshort' } })
  fireEvent.blur(password)
  // Wait for the ERROR, not the help text: the help line reads "Use at
  // least 12 characters" and is always present, so waiting on it settles
  // instantly and proves nothing.
  await screen.findByText(/Needs at least 12 characters/)
  return password
}

describe('Field error state is exposed to assistive technology', () => {
  it('marks an invalid input as invalid', async () => {
    const password = await anInvalidAdminPassword()

    expect(password.getAttribute('aria-invalid')).toBe('true')
  })

  it('points the input at its error text, and that text has an id to point at', async () => {
    const password = await anInvalidAdminPassword()

    const describedBy = password.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()

    // The reference must RESOLVE. A dangling aria-describedby is worse than
    // none: it reads as handled while announcing nothing.
    const target = document.getElementById((describedBy ?? '').split(/\s+/)[0])
    expect(target).not.toBeNull()
    expect(target?.textContent).toMatch(/Needs at least 12 characters/)
  })

  it('drops both attributes once the field is valid again', async () => {
    const password = await anInvalidAdminPassword()

    fireEvent.change(password, { target: { value: 'a-long-enough-password' } })
    fireEvent.blur(password)

    expect(password.getAttribute('aria-invalid')).not.toBe('true')
    expect(password.getAttribute('aria-describedby')).toBeNull()
  })

  it('leaves a never-touched field unmarked', async () => {
    stubStorageReadyStation()
    renderSetupScreen()
    await screen.findByText('Storage ready')

    const stationName = inputById('station_name')
    expect(stationName.getAttribute('aria-invalid')).not.toBe('true')
    expect(stationName.getAttribute('aria-describedby')).toBeNull()
  })
})

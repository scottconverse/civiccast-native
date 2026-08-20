// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchJson, formatDuration } from './api'

describe('public API error feedback', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('turns structured validation details into readable field feedback', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              {
                loc: ['query', 'receipt_token'],
                msg: 'String should have at least 24 characters',
              },
            ],
          }),
          { status: 422, statusText: 'Unprocessable Entity' },
        ),
      ),
    )

    await expect(fetchJson('/status')).rejects.toThrow(
      'Receipt token: String should have at least 24 characters',
    )
  })

  it('never exposes an object-coercion placeholder to a resident', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { message: 'Receipt not found.' } }), {
          status: 404,
          statusText: 'Not Found',
        }),
      ),
    )

    await expect(fetchJson('/status')).rejects.toThrow('Receipt not found.')
    await expect(fetchJson('/status')).rejects.not.toThrow('[object Object]')
  })
})

describe('public duration labels', () => {
  it('shows seconds for clips shorter than one minute', () => {
    expect(formatDuration(2)).toBe('2 sec')
    expect(formatDuration(59)).toBe('59 sec')
  })
})

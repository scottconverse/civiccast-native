// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  browseFolders: vi.fn(),
}))

import { browseFolders } from '../../api/client'
import { FolderBrowser } from './FolderBrowser'

afterEach(cleanup)

function renderBrowser(overrides: Partial<Parameters<typeof FolderBrowser>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onSelect = vi.fn()
  const onClose = vi.fn()
  return {
    ...render(
      <QueryClientProvider client={client}>
        <FolderBrowser onSelect={onSelect} onClose={onClose} {...overrides} />
      </QueryClientProvider>,
    ),
    onSelect,
    onClose,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FolderBrowser', () => {
  it('lists drive roots with no path given, since a non-technical operator has nothing to type', async () => {
    vi.mocked(browseFolders).mockResolvedValue({
      current_path: null,
      parent_path: null,
      separator: '\\',
      entries: [
        { name: 'C:\\', path: 'C:\\' },
        { name: 'D:\\', path: 'D:\\' },
      ],
      readable: true,
    })
    const { findByRole } = renderBrowser()

    expect(await findByRole('button', { name: /C:\\/ })).toBeTruthy()
    expect(await findByRole('button', { name: /D:\\/ })).toBeTruthy()
    await waitFor(() => expect(browseFolders).toHaveBeenCalledWith(undefined))
  })

  it('navigates into a folder and selecting it hands back the path', async () => {
    vi.mocked(browseFolders).mockImplementation((path) =>
      Promise.resolve(
        path === 'D:\\'
          ? {
              current_path: 'D:\\',
              parent_path: null,
              separator: '\\',
              entries: [{ name: 'incoming', path: 'D:\\incoming' }],
              readable: true,
            }
          : {
              current_path: null,
              parent_path: null,
              separator: '\\',
              entries: [{ name: 'D:\\', path: 'D:\\' }],
              readable: true,
            },
      ),
    )
    const { findByRole, onSelect } = renderBrowser()

    fireEvent.click(await findByRole('button', { name: /D:\\/ }))
    fireEvent.click(await findByRole('button', { name: /incoming/ }))
    fireEvent.click(await findByRole('button', { name: 'Use this folder' }))

    expect(onSelect).toHaveBeenCalledWith('D:\\incoming')
  })

  it('cannot select the roots picker itself -- "Use this folder" starts disabled', async () => {
    vi.mocked(browseFolders).mockResolvedValue({
      current_path: null,
      parent_path: null,
      separator: '\\',
      entries: [{ name: 'C:\\', path: 'C:\\' }],
      readable: true,
    })
    const { findByRole } = renderBrowser()

    expect(
      (await findByRole('button', { name: 'Use this folder' })) as HTMLButtonElement,
    ).toHaveProperty('disabled', true)
  })

  it('shows a clear message for an unreadable folder instead of a blank list', async () => {
    vi.mocked(browseFolders).mockResolvedValue({
      current_path: '/root-only',
      parent_path: '/',
      separator: '/',
      entries: [],
      readable: false,
      error: 'Permission denied',
    })
    const { findByText } = renderBrowser({ initialPath: '/root-only' })

    expect(await findByText(/Permission denied/)).toBeTruthy()
  })

  it('closes on Escape and on the Cancel button', async () => {
    vi.mocked(browseFolders).mockResolvedValue({
      current_path: null,
      parent_path: null,
      separator: '\\',
      entries: [],
      readable: true,
    })
    const { findByRole, onClose } = renderBrowser()
    fireEvent.click(await findByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalledOnce()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})

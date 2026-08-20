// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { CustomFieldDef, StaffIdentityResponse } from '../types/api.generated'

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
  listCustomFieldDefs: vi.fn(),
  createCustomFieldDef: vi.fn(),
  updateCustomFieldDef: vi.fn(),
  deleteCustomFieldDef: vi.fn(),
}))

import {
  ApiError,
  createCustomFieldDef,
  deleteCustomFieldDef,
  getStaffIdentity,
  listCustomFieldDefs,
  updateCustomFieldDef,
} from '../api/client'
import { CustomFieldsScreen } from './CustomFieldsScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function def(overrides: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    field_id: 'f-meeting-type',
    station_id: 'civiccast-station',
    key: 'meeting_type',
    label: 'Meeting type',
    type: 'list',
    options: ['Regular', 'Special'],
    required: false,
    searchable: true,
    api_exposed: true,
    order: 0,
    ...overrides,
  }
}

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <CustomFieldsScreen />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
  vi.mocked(listCustomFieldDefs).mockResolvedValue([])
  vi.mocked(createCustomFieldDef).mockImplementation(async (p) => def({ ...p }))
  vi.mocked(updateCustomFieldDef).mockImplementation(async (id, patch) =>
    def({ field_id: id, ...patch } as Partial<CustomFieldDef>),
  )
  vi.mocked(deleteCustomFieldDef).mockResolvedValue(undefined)
})

describe('CustomFieldsScreen access', () => {
  it('shows an access banner for a non-setup-admin role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin/i)).toBeTruthy()
  })

  it('renders the define-field form for a setup admin', async () => {
    const { findByLabelText } = renderScreen()
    expect(await findByLabelText('Field type')).toBeTruthy()
  })
})

describe('CustomFieldsScreen define form', () => {
  it('exposes all eight types in the type select', async () => {
    const { findByLabelText } = renderScreen()
    const select = (await findByLabelText('Field type')) as HTMLSelectElement
    expect(select.options.length).toBe(8)
  })

  it('reveals the options editor only for the list type', async () => {
    const { findByLabelText, queryByLabelText } = renderScreen()
    const typeSelect = (await findByLabelText('Field type')) as HTMLSelectElement
    // default type is text → no options editor
    expect(queryByLabelText('List options (one per line)')).toBeNull()
    fireEvent.change(typeSelect, { target: { value: 'list' } })
    expect(await findByLabelText('List options (one per line)')).toBeTruthy()
    // switching back to number hides it again
    fireEvent.change(typeSelect, { target: { value: 'number' } })
    expect(queryByLabelText('List options (one per line)')).toBeNull()
  })

  it('creates a field with the typed payload', async () => {
    const { findByLabelText, getByRole } = renderScreen()
    fireEvent.change(await findByLabelText('Field key'), { target: { value: 'episode_no' } })
    fireEvent.change(await findByLabelText('Field label'), { target: { value: 'Episode #' } })
    fireEvent.change(await findByLabelText('Field type'), { target: { value: 'number' } })
    fireEvent.click(getByRole('button', { name: /create field/i }))
    await waitFor(() =>
      expect(vi.mocked(createCustomFieldDef)).toHaveBeenCalledWith(
        expect.objectContaining({
          key: 'episode_no',
          label: 'Episode #',
          type: 'number',
        }),
      ),
    )
  })

  it('disables Create until key and label are present', async () => {
    const { findByRole, findByLabelText } = renderScreen()
    const create = (await findByRole('button', { name: /create field/i })) as HTMLButtonElement
    expect(create.disabled).toBe(true)
    fireEvent.change(await findByLabelText('Field key'), { target: { value: 'k' } })
    fireEvent.change(await findByLabelText('Field label'), { target: { value: 'L' } })
    expect(create.disabled).toBe(false)
  })
})

describe('CustomFieldsScreen edit (key immutability)', () => {
  it('disables the key input when editing, leaves the label editable', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def()])
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /edit meeting type/i }))
    const keyInput = (await findByLabelText('Field key')) as HTMLInputElement
    const labelInput = (await findByLabelText('Field label')) as HTMLInputElement
    expect(keyInput.disabled).toBe(true)
    expect(keyInput.value).toBe('meeting_type')
    expect(labelInput.disabled).toBe(false)
  })

  it('patches label/required without sending key', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def()])
    const { findByRole, findByLabelText } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /edit meeting type/i }))
    fireEvent.change(await findByLabelText('Field label'), { target: { value: 'Meeting category' } })
    fireEvent.click(await findByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(vi.mocked(updateCustomFieldDef)).toHaveBeenCalled())
    const [fieldId, patch] = vi.mocked(updateCustomFieldDef).mock.calls[0]
    expect(fieldId).toBe('f-meeting-type')
    expect(patch.label).toBe('Meeting category')
    expect('key' in patch).toBe(false)
  })
})

describe('CustomFieldsScreen delete confirm', () => {
  it('re-issues the delete with confirm=true after a 409', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def()])
    vi.mocked(deleteCustomFieldDef)
      .mockRejectedValueOnce(new ApiError('values exist', 409, 'Values exist; pass ?confirm=true'))
      .mockResolvedValueOnce(undefined)
    const { findByRole } = renderScreen()
    fireEvent.click(await findByRole('button', { name: /delete meeting type/i }))
    await waitFor(() =>
      expect(vi.mocked(deleteCustomFieldDef)).toHaveBeenCalledWith('f-meeting-type', false),
    )
    // a confirm control surfaces after the 409
    const confirmBtn = await findByRole('button', { name: /confirm delete/i })
    fireEvent.click(confirmBtn)
    await waitFor(() =>
      expect(vi.mocked(deleteCustomFieldDef)).toHaveBeenCalledWith('f-meeting-type', true),
    )
  })
})

describe('CustomFieldsScreen reorder', () => {
  it('moves a field up by swapping order on both rows', async () => {
    const a = def({ field_id: 'a', key: 'a', label: 'Alpha', order: 0 })
    const b = def({ field_id: 'b', key: 'b', label: 'Bravo', order: 1 })
    vi.mocked(listCustomFieldDefs).mockResolvedValue([a, b])
    const { findByRole } = renderScreen()
    // Bravo is second; moving it up should set its order to 0 (Alpha's order)
    fireEvent.click(await findByRole('button', { name: /move bravo up/i }))
    await waitFor(() => expect(vi.mocked(updateCustomFieldDef)).toHaveBeenCalled())
    const calls = vi.mocked(updateCustomFieldDef).mock.calls
    const bravoCall = calls.find(([id]) => id === 'b')
    expect(bravoCall?.[1].order).toBe(0)
  })

  it('disables Move up on the first row and Move down on the last', async () => {
    const a = def({ field_id: 'a', key: 'a', label: 'Alpha', order: 0 })
    const b = def({ field_id: 'b', key: 'b', label: 'Bravo', order: 1 })
    vi.mocked(listCustomFieldDefs).mockResolvedValue([a, b])
    const { findByRole } = renderScreen()
    const alphaUp = (await findByRole('button', { name: /move alpha up/i })) as HTMLButtonElement
    const bravoDown = (await findByRole('button', { name: /move bravo down/i })) as HTMLButtonElement
    expect(alphaUp.disabled).toBe(true)
    expect(bravoDown.disabled).toBe(true)
  })
})

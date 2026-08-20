// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { CustomFieldDef, CustomFieldValue } from '../types/api.generated'

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
  listCustomFieldDefs: vi.fn(),
  getAssetCustomFields: vi.fn(),
  putAssetCustomFields: vi.fn(),
  listStaffAssets: vi.fn(),
  getProducerActivityReport: vi.fn(),
}))

import {
  getAssetCustomFields,
  getProducerActivityReport,
  listCustomFieldDefs,
  listStaffAssets,
  putAssetCustomFields,
} from '../api/client'
import { AssetCustomFieldsEditor } from './AssetCustomFieldsEditor'

function def(overrides: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    field_id: 'f1',
    station_id: 'civiccast-station',
    key: 'k1',
    label: 'Field one',
    type: 'text',
    options: [],
    required: false,
    searchable: true,
    api_exposed: true,
    order: 0,
    ...overrides,
  }
}

function value(overrides: Partial<CustomFieldValue> = {}): CustomFieldValue {
  return {
    asset_id: 'asset-1',
    field_id: 'f1',
    value: '',
    value_num: null,
    value_date: null,
    ...overrides,
  }
}

function renderEditor(canWrite = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AssetCustomFieldsEditor assetId="asset-1" canWrite={canWrite} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listCustomFieldDefs).mockResolvedValue([])
  vi.mocked(getAssetCustomFields).mockResolvedValue([])
  vi.mocked(putAssetCustomFields).mockResolvedValue([])
  vi.mocked(listStaffAssets).mockResolvedValue([])
  vi.mocked(getProducerActivityReport).mockResolvedValue({
    generated_at: '2026-06-18T00:00:00Z',
    rows: [],
    proof_boundary: 'x',
  } as never)
})

describe('AssetCustomFieldsEditor rendering by type', () => {
  it('renders a text input for a text field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'text', label: 'Notes' })])
    const { findByLabelText } = renderEditor()
    const input = (await findByLabelText('Notes')) as HTMLInputElement
    expect(input.tagName).toBe('INPUT')
    expect(input.type).toBe('text')
  })

  it('renders a textarea for a longtext field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'longtext', label: 'Bio' })])
    const { findByLabelText } = renderEditor()
    expect(((await findByLabelText('Bio')) as HTMLElement).tagName).toBe('TEXTAREA')
  })

  it('renders a number input for a number field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'number', label: 'Episode' })])
    const { findByLabelText } = renderEditor()
    expect(((await findByLabelText('Episode')) as HTMLInputElement).type).toBe('number')
  })

  it('renders a date input for a date field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'date', label: 'Aired on' })])
    const { findByLabelText } = renderEditor()
    expect(((await findByLabelText('Aired on')) as HTMLInputElement).type).toBe('date')
  })

  it('renders a checkbox for a boolean field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'boolean', label: 'Encore' })])
    const { findByLabelText } = renderEditor()
    expect(((await findByLabelText('Encore')) as HTMLInputElement).type).toBe('checkbox')
  })

  it('renders a select with options for a list field', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([
      def({ type: 'list', label: 'Category', options: ['Gov', 'Public'] }),
    ])
    const { findByLabelText } = renderEditor()
    const select = (await findByLabelText('Category')) as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    // a blank option + the two real options
    expect(select.options.length).toBe(3)
  })
})

describe('AssetCustomFieldsEditor values + save', () => {
  it('seeds inputs from the asset values', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'text', label: 'Notes' })])
    vi.mocked(getAssetCustomFields).mockResolvedValue([value({ value: 'hello' })])
    const { findByLabelText } = renderEditor()
    expect(((await findByLabelText('Notes')) as HTMLInputElement).value).toBe('hello')
  })

  it('saves canonical-string values via putAssetCustomFields', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([
      def({ field_id: 'fn', type: 'number', label: 'Episode' }),
      def({ field_id: 'fb', type: 'boolean', label: 'Encore' }),
    ])
    const { findByLabelText, getByRole } = renderEditor()
    fireEvent.change(await findByLabelText('Episode'), { target: { value: '12' } })
    fireEvent.click(await findByLabelText('Encore'))
    fireEvent.click(getByRole('button', { name: /save custom fields/i }))
    await waitFor(() => expect(vi.mocked(putAssetCustomFields)).toHaveBeenCalled())
    const [, payload] = vi.mocked(putAssetCustomFields).mock.calls[0]
    expect(payload.values).toEqual(
      expect.arrayContaining([
        { field_id: 'fn', value: '12' },
        { field_id: 'fb', value: 'true' },
      ]),
    )
  })

  it('omits empty optional values from the payload', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ field_id: 'f1', type: 'text', label: 'Notes' })])
    const { getByRole, findByRole } = renderEditor()
    // nothing typed → save sends an empty value set (full-replace clears)
    fireEvent.click(await findByRole('button', { name: /save custom fields/i }))
    await waitFor(() => expect(vi.mocked(putAssetCustomFields)).toHaveBeenCalled())
    const [, payload] = vi.mocked(putAssetCustomFields).mock.calls[0]
    expect(payload.values).toEqual([])
    expect(getByRole('button', { name: /save custom fields/i })).toBeTruthy()
  })
})

describe('AssetCustomFieldsEditor required validation', () => {
  it('disables save and shows an alert when a required field is empty', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([
      def({ field_id: 'f1', type: 'text', label: 'Producer', required: true }),
    ])
    const { findByRole, findByLabelText } = renderEditor()
    const save = (await findByRole('button', { name: /save custom fields/i })) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(await findByRole('alert')).toBeTruthy()
    // filling it clears the block
    fireEvent.change(await findByLabelText(/Producer/), { target: { value: 'Acme' } })
    await waitFor(() => expect(save.disabled).toBe(false))
  })
})

describe('AssetCustomFieldsEditor read-only', () => {
  it('disables inputs and hides save when the operator cannot write', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([def({ type: 'text', label: 'Notes' })])
    const { findByLabelText, queryByRole } = renderEditor(false)
    expect(((await findByLabelText('Notes')) as HTMLInputElement).disabled).toBe(true)
    expect(queryByRole('button', { name: /save custom fields/i })).toBeNull()
  })
})

describe('AssetCustomFieldsEditor empty state', () => {
  it('renders a helpful note when no fields are defined', async () => {
    vi.mocked(listCustomFieldDefs).mockResolvedValue([])
    const { findByText } = renderEditor()
    expect(await findByText(/no custom fields are defined/i)).toBeTruthy()
  })
})

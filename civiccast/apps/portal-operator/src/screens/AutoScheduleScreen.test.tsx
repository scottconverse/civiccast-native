import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// vitest config has no global afterEach, so unmount each render explicitly.
afterEach(cleanup)

// --- isolated form / preview component tests (no QueryClient needed) ---

import type { RulePreview, SavedSearch, ScheduleBlock } from '../types/api.generated'
import { BlockForm, ConfirmDeleteButton, RuleForm, RulePreviewPanel, SavedSearchForm } from './AutoScheduleScreen'

describe('ConfirmDeleteButton', () => {
  it('requires a second click to confirm the delete', () => {
    const onDelete = vi.fn()
    const { getByText } = render(<ConfirmDeleteButton onDelete={onDelete} />)
    fireEvent.click(getByText('Delete'))
    expect(onDelete).not.toHaveBeenCalled()
    fireEvent.click(getByText('Confirm delete?'))
    expect(onDelete).toHaveBeenCalledTimes(1)
  })
})

describe('SavedSearchForm', () => {
  it('disables submit until a name is set, then builds the query payload', () => {
    const onSubmit = vi.fn()
    const { getByText, getByPlaceholderText, getByLabelText } = render(
      <SavedSearchForm submitting={false} onSubmit={onSubmit} />,
    )
    const submit = getByText('Create saved search') as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    fireEvent.change(getByPlaceholderText('Example: Recent council meetings'), {
      target: { value: 'Council' },
    })
    fireEvent.change(getByPlaceholderText('Example: City Council'), {
      target: { value: 'City Council' },
    })
    fireEvent.change(getByLabelText('Min length (minutes)'), { target: { value: '30' } })
    expect(submit.disabled).toBe(false)

    fireEvent.click(submit)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.name).toBe('Council')
    expect(payload.query.meeting_body).toBe('City Council')
    expect(payload.query.min_duration_seconds).toBe(1800) // 30 min -> seconds
    expect(payload.query.states).toContain('validated')
  })
})

describe('BlockForm', () => {
  it('builds start/end minute-of-day and sorted days from the inputs', () => {
    const onSubmit = vi.fn()
    const { getByText, getByPlaceholderText } = render(
      <BlockForm submitting={false} onSubmit={onSubmit} />,
    )
    const submit = getByText('Create daypart') as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    fireEvent.change(getByPlaceholderText('public'), { target: { value: 'public' } })
    fireEvent.change(getByPlaceholderText('Prime time'), { target: { value: 'Evening' } })
    expect(submit.disabled).toBe(false)

    fireEvent.click(submit)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.channel_id).toBe('public')
    expect(payload.start_minute).toBe(18 * 60) // default 18:00
    expect(payload.end_minute).toBe(22 * 60) // default 22:00
    expect(payload.days_of_week).toEqual([0, 1, 2, 3, 4]) // default weekdays, sorted
  })
})

const SEARCH: SavedSearch = {
  saved_search_id: 'ss_1',
  name: 'Council',
  query: { meeting_body: 'City Council' },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('step-6 fix-sprint behaviors', () => {
  it('BlockForm maps a midnight (00:00) end to 1440', () => {
    const onSubmit = vi.fn()
    const { getByText, getByPlaceholderText, getByDisplayValue } = render(
      <BlockForm submitting={false} onSubmit={onSubmit} />,
    )
    fireEvent.change(getByPlaceholderText('public'), { target: { value: 'public' } })
    fireEvent.change(getByPlaceholderText('Prime time'), { target: { value: 'Late night' } })
    fireEvent.change(getByDisplayValue('22:00'), { target: { value: '00:00' } }) // End -> midnight
    fireEvent.click(getByText('Create daypart'))
    expect(onSubmit.mock.calls[0][0].end_minute).toBe(1440)
  })

  it('BlockForm edit prefills a 1440 end as 00:00 and round-trips it', () => {
    const onSubmit = vi.fn()
    const block = { ...BLOCK, end_minute: 1440 }
    const { getByText, getByDisplayValue } = render(
      <BlockForm submitting={false} onSubmit={onSubmit} initial={block} />,
    )
    expect(getByDisplayValue('00:00')).toBeTruthy() // 1440 shown as 00:00
    fireEvent.click(getByText('Save changes')) // edit label, not "Create daypart"
    expect(onSubmit.mock.calls[0][0].end_minute).toBe(1440)
  })

  it('SavedSearchForm prefills from initial and uses the Save-changes label', () => {
    const { getByDisplayValue, getByText } = render(
      <SavedSearchForm submitting={false} onSubmit={vi.fn()} initial={SEARCH} />,
    )
    expect(getByDisplayValue('Council')).toBeTruthy()
    expect(getByDisplayValue('City Council')).toBeTruthy()
    expect(getByText('Save changes')).toBeTruthy()
  })

  it('SavedSearchForm renders humanized asset-state labels (not snake_case)', () => {
    const { getByText, queryByText } = render(<SavedSearchForm submitting={false} onSubmit={vi.fn()} />)
    // F1: a standalone checkbox label is sentence-cased through the shared
    // status vocabulary rather than left as bare lowercased enum words.
    expect(getByText('Waiting for media')).toBeTruthy()
    expect(queryByText('pending_ingest')).toBeNull()
  })

  it('RuleForm shows a visible window error when out of range', () => {
    const { getByLabelText, getByText, queryByText } = render(
      <RuleForm searches={[SEARCH]} blocks={[BLOCK]} submitting={false} onSubmit={vi.fn()} />,
    )
    expect(queryByText(/14 to 60 days/)).toBeNull() // default 30 is valid
    fireEvent.change(getByLabelText('Rolling window (days, 14–60)'), { target: { value: '5' } })
    expect(getByText(/14 to 60 days/)).toBeTruthy()
  })
})

const BLOCK: ScheduleBlock = {
  block_id: 'sb_1',
  channel_id: 'public',
  name: 'Evening',
  start_minute: 1080,
  end_minute: 1320,
  days_of_week: [0, 2, 4],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('RuleForm', () => {
  it('requires a name, search, block and an in-range window; submits the block channel', () => {
    const onSubmit = vi.fn()
    const { getByText, getByPlaceholderText, getByLabelText } = render(
      <RuleForm searches={[SEARCH]} blocks={[BLOCK]} submitting={false} onSubmit={onSubmit} />,
    )
    const submit = getByText('Create rule') as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    fireEvent.change(getByPlaceholderText('Fill prime with council'), { target: { value: 'Prime' } })
    fireEvent.change(getByLabelText('Saved search'), { target: { value: 'ss_1' } })
    fireEvent.change(getByLabelText('Daypart'), { target: { value: 'sb_1' } })
    expect(submit.disabled).toBe(false)

    // Out-of-range window disables submit.
    fireEvent.change(getByLabelText('Rolling window (days, 14–60)'), { target: { value: '5' } })
    expect(submit.disabled).toBe(true)
    fireEvent.change(getByLabelText('Rolling window (days, 14–60)'), { target: { value: '21' } })
    expect(submit.disabled).toBe(false)

    fireEvent.click(submit)
    const payload = onSubmit.mock.calls[0][0]
    expect(payload.name).toBe('Prime')
    expect(payload.saved_search_id).toBe('ss_1')
    expect(payload.schedule_block_id).toBe('sb_1')
    expect(payload.channel_id).toBe('public') // taken from the selected block
    expect(payload.rolling_window_days).toBe(21)
  })
})

describe('RulePreviewPanel', () => {
  it('summarizes fill count and labels each slot', () => {
    const preview: RulePreview = {
      rule_id: 'asr_1',
      channel_id: 'public',
      would_fill_count: 1,
      slots: [
        { starts_at: '2026-06-01T18:00:00Z', ends_at: '2026-06-01T19:00:00Z', action: 'fill', title: 'Meeting A' },
        { starts_at: '2026-06-02T18:00:00Z', ends_at: '2026-06-02T19:00:00Z', action: 'no_asset' },
      ],
    }
    const { container } = render(<RulePreviewPanel preview={preview} />)
    expect(container.textContent).toContain('Would schedule 1 of 2 upcoming slots.')
    expect(container.textContent).toContain('Will air')
    expect(container.textContent).toContain('No eligible video')
    expect(container.textContent).toContain('Meeting A')
  })

  it('warns when the rule points at a deleted search or daypart', () => {
    const preview: RulePreview = { rule_id: 'asr_1', channel_id: 'public', missing_dependency: true }
    const { container } = render(<RulePreviewPanel preview={preview} />)
    expect(container.textContent).toContain('no longer exists')
  })
})

// --- container role-gate tests (mocked client) ---

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getStaffIdentity: vi.fn(),
  listSavedSearches: vi.fn(),
  listScheduleBlocks: vi.fn(),
  listAutoScheduleRules: vi.fn(),
  createSavedSearch: vi.fn(),
  createScheduleBlock: vi.fn(),
  createAutoScheduleRule: vi.fn(),
  deleteSavedSearch: vi.fn(),
  deleteScheduleBlock: vi.fn(),
  deleteAutoScheduleRule: vi.fn(),
  previewAutoScheduleRule: vi.fn(),
  compileAutoSchedule: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import {
  getStaffIdentity,
  listAutoScheduleRules,
  listSavedSearches,
  listScheduleBlocks,
} from '../api/client'
import { AutoScheduleScreen } from './AutoScheduleScreen'

function identity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op', operator_display_name: 'Op', roles }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AutoScheduleScreen />
    </QueryClientProvider>,
  )
}

describe('AutoScheduleScreen container role gate', () => {
  it('shows create + compile controls for a publish operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    vi.mocked(listSavedSearches).mockResolvedValue([])
    vi.mocked(listScheduleBlocks).mockResolvedValue([])
    vi.mocked(listAutoScheduleRules).mockResolvedValue([])
    const { findByText } = renderScreen()
    expect(await findByText('Add saved search')).toBeTruthy()
    expect(await findByText('Compile now')).toBeTruthy()
  })

  it('hides write controls for a read-only support admin but still lists', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    vi.mocked(listSavedSearches).mockResolvedValue([])
    vi.mocked(listScheduleBlocks).mockResolvedValue([])
    vi.mocked(listAutoScheduleRules).mockResolvedValue([])
    const { findByText, queryByText } = renderScreen()
    // The read-only view renders its sections (no "needs role" note)...
    expect(await findByText('Saved searches')).toBeTruthy()
    // ...but offers no create or compile affordance.
    expect(queryByText('Add saved search')).toBeNull()
    expect(queryByText('Compile now')).toBeNull()
  })

  it('shows an access note for an operator without a read role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findAllByText } = renderScreen()
    const notes = await findAllByText(/requires the publish operator, setup admin, or support admin role/)
    expect(notes.length).toBeGreaterThan(0)
  })
})

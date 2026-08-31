import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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
  getPlaybackPolicy: vi.fn(),
  updatePlaybackPolicy: vi.fn(),
  getPlaybackPolicyAuditLog: vi.fn(),
}))

import {
  getPlaybackPolicy,
  getPlaybackPolicyAuditLog,
  updatePlaybackPolicy,
} from '../api/client'
import type { PlaybackPolicyConfig } from '../types/api.generated'
import { PlaybackPolicyScreen } from './PlaybackPolicyScreen'

afterEach(cleanup)

function policyFixture(overrides: Partial<PlaybackPolicyConfig> = {}): PlaybackPolicyConfig {
  return {
    subject_type: 'channel',
    subject_id: 'government',
    access_tier: 'public',
    invite_group_id: null,
    oidc_provider_id: null,
    authenticated_rss_enabled: false,
    public_record_required: false,
    public_archive_complete: false,
    preroll: { enabled: false, creatives: [], apply_to_archive_exports: false },
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(
    <QueryClientProvider client={client}>
      <PlaybackPolicyScreen />
    </QueryClientProvider>,
  )
  return { ...result, client }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getPlaybackPolicyAuditLog).mockResolvedValue({
    generated_at: '2026-08-01T00:00:00Z',
    events: [],
    proof_boundary: 'boundary',
  })
})

describe('PlaybackPolicyScreen target-id debounce and dirty-form protection', () => {
  it('does not refetch (or reset the form) on every keystroke typed into Target ID', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      vi.mocked(getPlaybackPolicy).mockResolvedValue(policyFixture())

      renderScreen()

      await vi.waitFor(() => expect(getPlaybackPolicy).toHaveBeenCalledTimes(1))

      const input = screen.getByLabelText('Target ID') as HTMLInputElement
      fireEvent.change(input, { target: { value: 'g' } })
      fireEvent.change(input, { target: { value: 'go' } })
      fireEvent.change(input, { target: { value: 'gov' } })
      fireEvent.change(input, { target: { value: 'gove' } })

      // Still only the initial fetch -- rapid keystrokes must not each fire
      // a new query.
      expect(getPlaybackPolicy).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(500)
      await vi.waitFor(() => expect(getPlaybackPolicy).toHaveBeenCalledTimes(2))
      expect(getPlaybackPolicy).toHaveBeenLastCalledWith('channel', 'gove')
    } finally {
      vi.useRealTimers()
    }
  })

  it('never overwrites an unsaved edit with a background refetch of the same subject', async () => {
    vi.mocked(getPlaybackPolicy).mockResolvedValue(policyFixture({ public_record_required: false }))

    const { client } = renderScreen()

    await screen.findByText('Playback policy')
    await vi.waitFor(() => expect(getPlaybackPolicy).toHaveBeenCalledTimes(1))
    // Wait for the fetched policy to actually land in the form (not just for
    // the fetch to have been *initiated*) before interacting -- otherwise the
    // initial-load sync effect can overwrite a click that raced it.
    await waitFor(() => expect(screen.queryByText('Updated Never')).toBeNull())

    const publicRecordCheckbox = screen.getByRole('checkbox', {
      name: 'Public-record asset',
    }) as HTMLInputElement
    expect(publicRecordCheckbox.checked).toBe(false)
    fireEvent.click(publicRecordCheckbox)
    await waitFor(() =>
      expect(
        (screen.getByRole('checkbox', { name: 'Public-record asset' }) as HTMLInputElement).checked,
      ).toBe(true),
    )

    // Force a background refetch of the SAME subject key (e.g. what
    // TanStack Query's own window-refocus refetch would trigger), still
    // resolving to the server's still-unsaved-locally data. Previously the
    // effect reset the form from every policyQuery.data change -- including
    // this kind of background refetch -- which would wipe the in-progress
    // edit above.
    await client.refetchQueries({ queryKey: ['playback-policy', 'channel', 'government'] })
    await vi.waitFor(() => expect(getPlaybackPolicy).toHaveBeenCalledTimes(2))

    expect(
      (screen.getByRole('checkbox', { name: 'Public-record asset' }) as HTMLInputElement).checked,
    ).toBe(true)
  })
})

describe('PlaybackPolicyScreen preroll completeness gate', () => {
  it('blocks Save when a second preroll row is only partially filled in, and reports which row', async () => {
    vi.mocked(getPlaybackPolicy).mockResolvedValue(
      policyFixture({
        preroll: {
          enabled: true,
          creatives: [
            {
              creative_id: 'station-card',
              kind: 'graphic',
              asset_url: '/media/preroll/station-card.png',
              duration_seconds: 10,
              accessible_label: 'Station announcement',
            },
          ],
          apply_to_archive_exports: false,
        },
      }),
    )

    vi.mocked(updatePlaybackPolicy).mockResolvedValue(policyFixture())

    renderScreen()

    await screen.findByText('Preroll 1')
    // Save is enabled while there is one complete row and no others.
    expect(screen.getByRole('button', { name: 'Save policy' })).toHaveProperty('disabled', false)

    fireEvent.click(screen.getByRole('button', { name: 'Add preroll' }))
    await screen.findByText('Preroll 2')

    // "Add preroll" auto-assigns a creative_id to the new row, so it is
    // immediately a "present" row missing its other required fields --
    // Save must block rather than silently drop it on submit.
    expect(await screen.findByText(/Preroll 2 is missing required fields\./)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Save policy' })).toHaveProperty('disabled', true)

    fireEvent.change(
      screen.getByLabelText('Asset URL', { selector: '#preroll-1-asset-url' }),
      { target: { value: '/media/preroll/second.png' } },
    )
    fireEvent.change(
      screen.getByLabelText('Accessible label', { selector: '#preroll-1-accessible-label' }),
      { target: { value: 'Second announcement' } },
    )

    // Every field required by isCreativeComplete is now filled in (duration
    // seconds defaults to '10') -- the warning clears and Save re-enables.
    await waitFor(() =>
      expect(screen.queryByText(/is missing required fields\./)).toBeNull(),
    )
    expect(screen.getByRole('button', { name: 'Save policy' })).toHaveProperty('disabled', false)

    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }))
    await waitFor(() =>
      expect(updatePlaybackPolicy).toHaveBeenCalledWith(
        'channel',
        'government',
        expect.objectContaining({
          preroll: expect.objectContaining({
            creatives: [
              expect.objectContaining({ creative_id: 'station-card' }),
              expect.objectContaining({ creative_id: 'preroll-2' }),
            ],
          }),
        }),
      ),
    )
  })
})

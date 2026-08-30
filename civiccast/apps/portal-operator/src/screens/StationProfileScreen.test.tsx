// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'

import type { StaffIdentityResponse, StationBoxProfile, StationProfile } from '../types/api.generated'

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
  getStationProfile: vi.fn(),
  getStationBoxProfile: vi.fn(),
  updateStationProfile: vi.fn(),
}))

import {
  ApiError,
  getStaffIdentity,
  getStationBoxProfile,
  getStationProfile,
  updateStationProfile,
} from '../api/client'
import { StationProfileScreen } from './StationProfileScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function profile(overrides: Partial<StationProfile> = {}): StationProfile {
  return {
    station_name: 'Pinegrove School Board',
    admin_display_name: 'Avery Admin',
    admin_username: 'avery',
    default_channel_id: 'government',
    public_base_url: null,
    station_timezone: 'America/Denver',
    storage_locations: {
      media_library: 'C:/CivicCast/media',
      recordings: 'C:/CivicCast/recordings',
      backups: 'C:/CivicCast/backups',
    },
    recovery_kit_id: 'rk_abc123',
    recovery_kit_generated_at: '2026-06-01T00:00:00Z',
    ...overrides,
  } as StationProfile
}

function boxProfile(overrides: Partial<StationBoxProfile> = {}): StationBoxProfile {
  return {
    schema_version: 1,
    generated_at: '2026-06-01T00:00:00Z',
    civiccast_version: '1.0.0-test',
    hardware: {
      cpu: { cores_physical: 8, cores_logical: 16, brand: 'Test CPU' },
      ram: { total_gb: 32, available_gb: 16 },
      disk: { path: 'C:\\', total_gb: 1000, free_gb: 500 },
      gpu: null,
      os: { kind: 'windows', system: 'Windows', release: '11', machine: 'AMD64', hostname: 'test' },
      recommended_tier: 'tier-0',
      civiccast_version: '1.0.0-test',
    },
    system_ram_total_gb: 32,
    engine: {
      gstreamer_present: true,
      gstreamer_version: '1.24.0',
      required_plugins_present: true,
      missing_plugins: [],
      opengl_45: false,
      hw_encoder: 'none',
      decklink: { card_present: false, bmd_sdk_present: false, sdk_version: null },
      ndi_sdk: { sdk_present: false, sdk_version: null },
      native_os: true,
      next_step: '',
    },
    ffmpeg: {
      detected: true,
      version: '6.0',
      supported: true,
      has_decklink: false,
      has_ndi: false,
      has_libx264: true,
      has_loudnorm: true,
      byo_sdi_binary: null,
      next_step: '',
    },
    clock: {
      timezone: 'America/Denver',
      utc_offset_minutes: -360,
      system_time: '2026-06-01T00:00:00Z',
      ntp_sync: 'synced',
      note: '',
    },
    network: { hostname: 'test', primary_interface_up: true, headend_interface_hint: null },
    backup_destination: { configured: true, reachable: true, destination: 'nas://backup', last_probe_at: null },
    release_identity: { version: '1.0.0-test', package_verified: null, proof_state: null },
    sdi: { status: 'ok', ffmpeg_detected: true, muxer_present: true, next_step: '' },
    tsduck: { installed: true, path: '/usr/bin/tsp', version: '3.40', install_hint: '' },
    ndi_sdk: { sdk_present: false, sdk_version: null },
    qualified_engine_tier: { qualifies_for: 'base', base_ok: true, sdi_broadcast_ok: false, premium_cg_ok: false, blockers: [] },
    ai_default: {
      summary_model: 'gemma4:12b',
      translate_model: 'translategemma:4b',
      caption_model: 'whisper-large-v3',
      basis: 'ram-12b',
      detected_ram_gb: 32,
      rationale: '16GB+ system RAM detected; 12B summary default.',
    },
    peg_readiness: {
      overall: 'green',
      dimensions: [
        { id: 'engine', label: 'Playout engine', color: 'green', message: 'GStreamer base engine is ready.', next_step: '' },
      ],
    },
    cable_os_verdict: {
      verdict: 'soak-pending',
      os_kind: 'windows',
      rationale:
        'Single-Windows-PC certification for 24/7 cable is pending the soak result — see MASTER §13.1.',
      decision_ref: 'MASTER §13.1',
    },
    ...overrides,
  } as StationBoxProfile
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StationProfileScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StationProfileScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getStationBoxProfile).mockResolvedValue(boxProfile())
    vi.mocked(getStationProfile).mockResolvedValue(profile())
    vi.mocked(updateStationProfile).mockResolvedValue(profile({ station_name: 'Pinegrove PEG' }))
  })

  it('shows a loading state before identity resolves', () => {
    vi.mocked(getStaffIdentity).mockReturnValue(new Promise(() => {}))
    const { getByText } = renderScreen()
    expect(getByText(/loading/i)).toBeTruthy()
  })

  it('shows an auth-required state when identity fails to load', async () => {
    vi.mocked(getStaffIdentity).mockRejectedValue(new ApiError('unauthorized', 401))
    const { findByText } = renderScreen()
    expect(await findByText(/could not verify/i)).toBeTruthy()
  })

  it('shows the access banner for a non-privileged role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin, meeting operator, or support admin/i)).toBeTruthy()
  })

  it('renders the station identity read-only for a meeting operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByLabelText } = renderScreen()
    const nameField = (await findByLabelText('Station name')) as HTMLInputElement
    expect(nameField.value).toBe('Pinegrove School Board')
    expect(nameField.disabled).toBe(true)
  })

  it('still lets a read-only meeting operator copy a storage-root path (not trapped in a disabled fieldset)', async () => {
    // PR #74 review: the Copy path buttons used to live inside a
    // <fieldset disabled={!canWrite}>, so a meeting_operator/support_admin
    // -- READ_ROLES, but not WRITE_ROLES -- could see the recordings path
    // but not click Copy path to actually use it. Recordings path fields
    // stay disabled for this role; the buttons must not.
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByLabelText, findAllByText } = renderScreen()
    const recordingsField = (await findByLabelText('Recordings path')) as HTMLInputElement
    expect(recordingsField.disabled).toBe(true)

    const copyButtons = await findAllByText('Copy path')
    for (const button of copyButtons) {
      expect((button as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it('shows the empty/not-set-up state when no profile exists yet (404)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getStationProfile).mockRejectedValue(new ApiError('not found', 404))
    const { findByText } = renderScreen()
    expect(await findByText(/complete first setup/i)).toBeTruthy()
  })

  it('shows a generic error banner for a non-404 profile load failure', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getStationProfile).mockRejectedValue(new ApiError('boom', 500, 'server exploded'))
    const { findByText } = renderScreen()
    expect(await findByText(/server exploded/i)).toBeTruthy()
  })

  it('lets a setup admin edit and save the station name', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByLabelText, findByText } = renderScreen()
    const nameField = (await findByLabelText('Station name')) as HTMLInputElement
    expect(nameField.disabled).toBe(false)
    fireEvent.change(nameField, { target: { value: 'Pinegrove PEG' } })
    const saveButton = await findByText('Save')
    fireEvent.click(saveButton)
    await waitFor(() =>
      expect(vi.mocked(updateStationProfile)).toHaveBeenCalledWith(
        expect.objectContaining({ station_name: 'Pinegrove PEG' }),
      ),
    )
    expect(await findByText(/station profile saved/i)).toBeTruthy()
  })

  it('copies the recordings path and explains why Explorer may not find it', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const { findByLabelText, findByText, findAllByText } = renderScreen()
    await findByLabelText('Recordings path')

    expect(await findByText(/you do not need file access to find a recording/i)).toBeTruthy()
    expect(await findByText(/not your personal/i)).toBeTruthy()

    const copyButtons = await findAllByText('Copy path')
    fireEvent.click(copyButtons[1]) // Recordings is the second storage-root field
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('C:/CivicCast/recordings'))
    expect(await findByText('Copied')).toBeTruthy()
  })

  it('links the storage-roots note to the manual\'s recordings-location section', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByRole } = renderScreen()
    const link = await findByRole('link', { name: /read more in the manual/i })
    expect(link.getAttribute('href')).toBe('/help#where-recordings-live')
  })

  it('shows a save-error banner when the PUT fails', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(updateStationProfile).mockRejectedValue(new ApiError('boom', 422, 'invalid timezone'))
    const { findByLabelText, findByText } = renderScreen()
    const nameField = (await findByLabelText('Station name')) as HTMLInputElement
    fireEvent.change(nameField, { target: { value: 'X' } })
    fireEvent.click(await findByText('Save'))
    expect(await findByText(/invalid timezone/i)).toBeTruthy()
  })

  it('renders the box profile readiness badge and dimensions', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    const { findByText, findAllByText } = renderScreen()
    await findByText(/GStreamer base engine is ready/i)
    // The badge text is lowercase in the DOM; visual uppercase is a CSS
    // text-transform, not literal text (never rely on CSS for assertions).
    // Both the roll-up badge and the per-dimension row say "green".
    const greens = await findAllByText('green')
    expect(greens.length).toBeGreaterThanOrEqual(2)
  })

  it('renders the exact §13.1 soak-pending cable-OS caveat verbatim', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['support_admin']))
    const { findByText } = renderScreen()
    expect(
      await findByText(
        /Single-Windows-PC certification for 24\/7 cable is pending the soak result — see MASTER §13\.1\./,
      ),
    ).toBeTruthy()
  })

  it('shows a box-profile error banner without blocking the identity panel', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getStationBoxProfile).mockRejectedValue(new ApiError('boom', 500, 'probe failed'))
    const { findByText, findByLabelText } = renderScreen()
    expect(await findByText(/probe failed/i)).toBeTruthy()
    expect(await findByLabelText('Station name')).toBeTruthy()
  })
})

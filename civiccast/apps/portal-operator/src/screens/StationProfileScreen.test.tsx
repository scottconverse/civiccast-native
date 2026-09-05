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
  acknowledgeRecoveryKit: vi.fn(),
  getStaffIdentity: vi.fn(),
  getStationProfile: vi.fn(),
  getStationBoxProfile: vi.fn(),
  regenerateRecoveryKit: vi.fn(),
  revokeOtherOperatorSessions: vi.fn(),
  updateStationProfile: vi.fn(),
}))

import {
  acknowledgeRecoveryKit,
  ApiError,
  getStaffIdentity,
  getStationBoxProfile,
  getStationProfile,
  regenerateRecoveryKit,
  revokeOtherOperatorSessions,
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

  describe('Live captions switch', () => {
    it('is on by default and saves an operator turning it off', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      vi.mocked(updateStationProfile).mockResolvedValue(
        profile({ live_captions_enabled: false }),
      )
      const { findByLabelText } = renderScreen()

      const toggle = (await findByLabelText(/show live captions on air/i)) as HTMLInputElement
      expect(toggle.checked).toBe(true)
      expect(toggle.disabled).toBe(false)

      fireEvent.click(toggle)
      fireEvent.click(await findByLabelText(/save station profile/i))

      await waitFor(() =>
        expect(vi.mocked(updateStationProfile)).toHaveBeenCalledWith(
          expect.objectContaining({ live_captions_enabled: false }),
        ),
      )
    })

    it('reads a profile saved before the setting existed as ON, never as off', async () => {
      // An absent key must not read as "the operator turned captions off":
      // live captions are an accessibility feature, so the safe default is on.
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      const before = profile()
      delete (before as unknown as Record<string, unknown>).live_captions_enabled
      vi.mocked(getStationProfile).mockResolvedValue(before)
      const { findByLabelText } = renderScreen()

      expect(((await findByLabelText(/show live captions on air/i)) as HTMLInputElement).checked).toBe(
        true,
      )
    })

    it('explains the consequence of turning it off, and links the help to the control', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      const { findByLabelText, getAllByRole, getByText } = renderScreen()

      const toggle = await findByLabelText(/show live captions on air/i)
      const helpId = toggle.getAttribute('aria-describedby')
      expect(helpId).toBe('live-captions-help')

      const help = getByText(/if playout is stuttering or channels are restarting, turn it off/i)
      expect(help.id).toBe(helpId)
      // The operator must be told what is NOT affected, or "off" reads as
      // "this station stops captioning anything at all".
      expect(help.textContent).toMatch(/captions on recordings you publish/i)
      // Its own manual link, with text distinct from the storage-roots one:
      // two links reading "Read more in the manual" on one screen are
      // ambiguous to anyone navigating by link list.
      const manualLinks = getAllByRole('link', { name: /manual/i }).map((a) =>
        a.getAttribute('href'),
      )
      expect(manualLinks).toContain('/help#live-captions-switch')
      expect(new Set(manualLinks).size).toBe(manualLinks.length)
    })

    it('is not editable by a read-only role', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
      const { findByLabelText } = renderScreen()

      expect(((await findByLabelText(/show live captions on air/i)) as HTMLInputElement).disabled).toBe(
        true,
      )
    })
  })

  describe('Security panel', () => {
    it('hides the session and recovery-kit actions for a read-only role', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
      const { findByText, queryByText } = renderScreen()
      expect(await findByText('Security')).toBeTruthy()
      expect(await findByText(/require the setup admin role/i)).toBeTruthy()
      expect(queryByText('Sign out other sessions')).toBeNull()
      expect(queryByText('Regenerate recovery kit')).toBeNull()
    })

    it('signs out other sessions and reports how many were revoked, without a second confirm click', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      vi.mocked(revokeOtherOperatorSessions).mockResolvedValue({
        status: 'revoked',
        revoked_count: 2,
        message: 'Signed out 2 other operator-console sessions. This browser stays signed in.',
        next_step: 'Sign in again on any device that should still have access.',
      })
      const { findByText } = renderScreen()

      fireEvent.click(await findByText('Sign out other sessions'))
      fireEvent.click(await findByText('Confirm — sign out other sessions'))

      expect(await findByText(/Signed out 2 other operator-console sessions/i)).toBeTruthy()
      expect(revokeOtherOperatorSessions).toHaveBeenCalledTimes(1)
    })

    it('shows an error banner when revoking other sessions fails', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      vi.mocked(revokeOtherOperatorSessions).mockRejectedValue(
        new ApiError('boom', 401, 'Invalid staff bearer token.'),
      )
      const { findByText } = renderScreen()

      fireEvent.click(await findByText('Sign out other sessions'))
      fireEvent.click(await findByText('Confirm — sign out other sessions'))

      expect(await findByText(/Invalid staff bearer token/i)).toBeTruthy()
    })

    it('regenerates the recovery kit, shows the new codes once, and requires save-or-print before Done is enabled', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      vi.mocked(regenerateRecoveryKit).mockResolvedValue({
        status: 'regenerated',
        recovery_kit: {
          kit_id: 'rk_new123',
          generated_at: '2026-08-31T00:00:00Z',
          station_name: 'Pinegrove School Board',
          admin_username: 'avery',
          recovery_codes: ['CC-NEWCODE0001', 'CC-NEWCODE0002'],
          instructions: ['Save or print this kit now.'],
          excludes: ['staff bearer token values'],
        },
        next_step: 'Save or print this new recovery kit now -- it replaces every earlier one.',
      })
      vi.mocked(acknowledgeRecoveryKit).mockResolvedValue({
        status: 'complete',
        setup_complete: true,
        operator_console_url: 'http://127.0.0.1:8000',
        next_step: 'Open System Health.',
      })
      const { findByText, findByLabelText } = renderScreen()

      fireEvent.click(await findByText('Regenerate recovery kit'))
      fireEvent.click(await findByText('Confirm — regenerate kit'))

      expect(await findByText('CC-NEWCODE0001')).toBeTruthy()
      expect(await findByText('CC-NEWCODE0002')).toBeTruthy()

      const doneButton = (await findByText('Done')) as HTMLButtonElement
      expect(doneButton.disabled).toBe(true)

      fireEvent.click(await findByText('Save kit'))
      const confirmCheckbox = await findByLabelText(
        /I have saved or printed the new recovery codes/i,
      )
      fireEvent.click(confirmCheckbox)
      expect((await findByText('Done')).hasAttribute('disabled')).toBe(false)

      fireEvent.click(await findByText('Done'))
      await waitFor(() => expect(acknowledgeRecoveryKit).toHaveBeenCalledTimes(1))
    })

    it('shows an error banner when regenerating the recovery kit fails', async () => {
      vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
      vi.mocked(regenerateRecoveryKit).mockRejectedValue(
        new ApiError('boom', 409, 'First-admin setup is not complete.'),
      )
      const { findByText } = renderScreen()

      fireEvent.click(await findByText('Regenerate recovery kit'))
      fireEvent.click(await findByText('Confirm — regenerate kit'))

      expect(await findByText(/First-admin setup is not complete/i)).toBeTruthy()
    })
  })
})

// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  ChannelProfile,
  CommissioningCheckReport,
  CommissioningProofRun,
  CommissioningReport,
  CommissioningState,
  HeadendProfile,
  StaffIdentityResponse,
} from '../types/api.generated'

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
  getCommissioningState: vi.fn(),
  runCommissioningChecks: vi.fn(),
  saveChannelCommissioningSetup: vi.fn(),
  runCommissioningOutputProof: vi.fn(),
  buildCommissioningReport: vi.fn(),
  listChannelProfiles: vi.fn(),
  listHeadendProfiles: vi.fn(),
  createSupportBundle: vi.fn(),
  downloadSupportBundle: vi.fn(),
}))

import {
  buildCommissioningReport,
  getCommissioningState,
  getStaffIdentity,
  listChannelProfiles,
  listHeadendProfiles,
  runCommissioningChecks,
  runCommissioningOutputProof,
  saveChannelCommissioningSetup,
} from '../api/client'
import { CommissioningWizardScreen } from './CommissioningWizardScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function emptyState(): CommissioningState {
  return { first_run_checks: null, channel_setup: null, proof_run: null, report: null }
}

function checkReport(overrides: Partial<CommissioningCheckReport> = {}): CommissioningCheckReport {
  return {
    generated_at: '2026-06-01T00:00:00Z',
    checks: [
      { id: 'os_version', label: 'Operating system', status: 'pass', detail: 'Windows 11', next_step: '' },
      { id: 'db', label: 'Database', status: 'fail', detail: 'not configured', next_step: 'prepare storage' },
    ],
    ready: true,
    blockers: [],
    ...overrides,
  } as CommissioningCheckReport
}

function channelProfile(): ChannelProfile {
  return {
    channel_id: 'government',
    slug: 'government',
    kind: 'government',
    branding: { display_name: 'Government Channel' },
    fallback_behavior: 'slate',
  } as unknown as ChannelProfile
}

function headendProfile(): HeadendProfile {
  return {
    profile_id: 'generic-udp-spts',
    label: 'Generic UDP SPTS',
    vendor: 'generic',
    source_urls: [],
    canonical_profile: {},
    muxrate_kbps: 4000,
    transport: 'udp-unicast',
  } as unknown as HeadendProfile
}

function proofRun(overrides: Partial<CommissioningProofRun> = {}): CommissioningProofRun {
  return {
    channel_id: 'government',
    proof_id: 'proof_1',
    started_at: '2026-06-01T00:00:00Z',
    test_pattern: 'bars',
    verdict: 'pass',
    blockers: [],
    not_claimed: ['Headend/format proof only, not physical SDI proof.'],
    ...overrides,
  } as CommissioningProofRun
}

function report(overrides: Partial<CommissioningReport> = {}): CommissioningReport {
  return {
    station_name: 'Test Station',
    channel_name: 'Government Channel',
    headend_profile_id: 'generic-udp-spts',
    output_format: '1080p30',
    completed_at: '2026-06-01T00:00:00Z',
    first_run_checks: checkReport(),
    channel_setup: {
      channel_id: 'government',
      channel_name: 'Government Channel',
      output_format: '1080p30',
      headend_profile_id: 'generic-udp-spts',
      destination: '192.168.1.100:5000',
    },
    proof_run: proofRun(),
    ready_for_broadcast: true,
    next_steps: [],
    ...overrides,
  } as CommissioningReport
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CommissioningWizardScreen />
    </QueryClientProvider>,
  )
}

describe('CommissioningWizardScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getCommissioningState).mockResolvedValue(emptyState())
    vi.mocked(listChannelProfiles).mockResolvedValue([channelProfile()])
    vi.mocked(listHeadendProfiles).mockResolvedValue([headendProfile()])
  })

  it('shows the access banner for a non-privileged role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin or support admin/i)).toBeTruthy()
  })

  it('locks screens 9-11 until their prerequisite step completes', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByText } = renderScreen()
    expect(await findByText(/complete the first-run cable checks first/i)).toBeTruthy()
    expect(await findByText(/save the channel output setup first/i)).toBeTruthy()
    expect(await findByText(/run the output proof first/i)).toBeTruthy()
  })

  it('running the cable checks refetches state and unlocks channel setup once ready', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(runCommissioningChecks).mockResolvedValue(checkReport({ ready: true }))
    // After the mutation succeeds the screen invalidates commissioning-state;
    // the second fetch reports the checks as done, unlocking screen 9.
    vi.mocked(getCommissioningState)
      .mockResolvedValueOnce(emptyState())
      .mockResolvedValue({ ...emptyState(), first_run_checks: checkReport({ ready: true }) })
    const { findByText } = renderScreen()
    fireEvent.click(await findByText('Run cable checks'))
    await waitFor(() => expect(vi.mocked(runCommissioningChecks)).toHaveBeenCalled())
    expect(await findByText(/Choose a channel/i)).toBeTruthy()
  })

  it('shows a not-ready banner and blockers when checks fail', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(runCommissioningChecks).mockResolvedValue(
      checkReport({ ready: false, blockers: ['Database: not configured'] }),
    )
    const { findByText } = renderScreen()
    const runButton = await findByText('Run cable checks')
    fireEvent.click(runButton)
    expect(await findByText(/not ready -- fix the failing checks/i)).toBeTruthy()
    expect(await findByText('Database')).toBeTruthy()
  })

  it('saves channel setup and shows a save confirmation', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getCommissioningState).mockResolvedValue({
      ...emptyState(),
      first_run_checks: checkReport({ ready: true }),
    })
    vi.mocked(saveChannelCommissioningSetup).mockResolvedValue({
      channel_id: 'government',
      channel_name: 'Government Channel',
      output_format: '1080p30',
      headend_profile_id: 'generic-udp-spts',
      destination: '192.168.1.100:5000',
    })
    const { findByLabelText, findByText } = renderScreen()
    // Wait for the async option lists to actually populate the <select>s --
    // fireEvent.change to a value with no matching <option> yet is a no-op.
    await findByText('Government Channel')
    await findByText('Generic UDP SPTS')
    const channelSelect = (await findByLabelText('Channel')) as HTMLSelectElement
    fireEvent.change(channelSelect, { target: { value: 'government' } })
    const profileSelect = (await findByLabelText('Headend profile')) as HTMLSelectElement
    fireEvent.change(profileSelect, { target: { value: 'generic-udp-spts' } })
    const destinationInput = (await findByLabelText('Destination address and port')) as HTMLInputElement
    fireEvent.change(destinationInput, { target: { value: '192.168.1.100:5000' } })
    fireEvent.click(await findByText('Save and continue'))
    await waitFor(() => expect(vi.mocked(saveChannelCommissioningSetup)).toHaveBeenCalled())
    expect(await findByText(/channel setup saved/i)).toBeTruthy()
  })

  it('runs the output proof and shows the verdict', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getCommissioningState).mockResolvedValue({
      ...emptyState(),
      first_run_checks: checkReport({ ready: true }),
      channel_setup: {
        channel_id: 'government',
        channel_name: 'Government Channel',
        output_format: '1080p30',
        headend_profile_id: 'generic-udp-spts',
        destination: '192.168.1.100:5000',
      },
    })
    vi.mocked(runCommissioningOutputProof).mockResolvedValue(proofRun())
    const { findByText } = renderScreen()
    fireEvent.click(await findByText('Start proof run'))
    await waitFor(() => expect(vi.mocked(runCommissioningOutputProof)).toHaveBeenCalled())
    expect(await findByText(/Verdict: pass/i)).toBeTruthy()
    expect(await findByText(/Headend\/format proof only/i)).toBeTruthy()
  })

  it('builds the final report and shows the ready-for-broadcast banner', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getCommissioningState).mockResolvedValue({
      first_run_checks: checkReport({ ready: true }),
      channel_setup: {
        channel_id: 'government',
        channel_name: 'Government Channel',
        output_format: '1080p30',
        headend_profile_id: 'generic-udp-spts',
        destination: '192.168.1.100:5000',
      },
      proof_run: proofRun(),
      report: null,
    })
    vi.mocked(buildCommissioningReport).mockResolvedValue(report())
    const { findByText } = renderScreen()
    fireEvent.click(await findByText('Generate report'))
    await waitFor(() => expect(vi.mocked(buildCommissioningReport)).toHaveBeenCalled())
    expect(await findByText(/ready for broadcast/i)).toBeTruthy()
  })
})

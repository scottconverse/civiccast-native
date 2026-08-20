import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type { ChannelProfile, RuntimeSafeToAirStatus, SystemResourceSample, SystemSelfTest } from '../types/api.generated'
import type { EgressStateRow } from '../api/client'
import { EgressReadinessPanel, ResourceSnapshotPanel, RuntimeSafeToAirBanner, SelfTestPanel } from './SystemHealthScreen'

// No global afterEach in vitest config → register testing-library cleanup
// explicitly so body-scoped queries don't match leftover renders.
afterEach(cleanup)

const greenStatus: RuntimeSafeToAirStatus = {
  generated_at: '2026-06-15T12:00:00Z',
  color: 'green',
  label: 'On air and healthy',
  operator_message: 'All automatic channels are on air.',
  channels: [
    { channel_id: 'public', egress_state: 'ON_AIR', on_air: true, on_healthy_slate: false, color: 'green' },
  ],
  active_critical_alerts: 0,
  active_warning_alerts: 0,
}

describe('RuntimeSafeToAirBanner', () => {
  it('renders nothing without a status', () => {
    const { container } = render(<RuntimeSafeToAirBanner status={undefined} />)
    expect(container.textContent).toBe('')
  })

  it('shows the API label, message, and per-channel state', () => {
    const { container } = render(<RuntimeSafeToAirBanner status={greenStatus} />)
    expect(container.textContent).toContain('On air and healthy')
    expect(container.textContent).toContain('All automatic channels are on air.')
    expect(container.textContent).toContain('public')
    expect(container.textContent).toContain('On air')
    expect(container.textContent).toContain('0 critical')
  })

  it('surfaces firing counts and a review-alerts action when alerts fire', () => {
    const onOpenAlerts = vi.fn()
    const { getAllByText, getByText } = render(
      <RuntimeSafeToAirBanner
        status={{
          ...greenStatus,
          color: 'red',
          label: 'A channel is off air',
          active_critical_alerts: 2,
          channels: [
            { channel_id: 'public', egress_state: 'ERROR', on_air: false, on_healthy_slate: false, color: 'red' },
          ],
        }}
        onOpenAlerts={onOpenAlerts}
      />,
    )
    expect(getByText('2 critical')).toBeTruthy()
    // F1 recurrence: this banner used to be the one screen that got the
    // egress-state translation right while the outgoing-channel-feed panels
    // kept their own copy of the same switch statement and drifted. (The red
    // channel's own status pill also happens to say "Needs attention" via
    // runtimeChannelLabel, unrelated to this fix, so this row legitimately
    // shows the phrase twice.)
    expect(getAllByText('Needs attention').length).toBeGreaterThanOrEqual(1)
    fireEvent.click(getByText('Review alerts'))
    expect(onOpenAlerts).toHaveBeenCalled()
  })

  it('explains the idle case when no channels run automatically', () => {
    const { container } = render(
      <RuntimeSafeToAirBanner status={{ ...greenStatus, channels: [] }} />,
    )
    expect(container.textContent).toContain('nothing on air to watch yet')
  })
})

describe('egress-state wording agreement across panels', () => {
  const CHANNEL = {
    channel_id: 'public',
    slug: 'public',
    kind: 'public',
    branding: { display_name: 'Public Channel' } as ChannelProfile['branding'],
    fallback_behavior: 'slate',
  } as ChannelProfile

  it('shows the identical caption for the same egress state on the safe-to-air banner and the readiness panel', () => {
    // The exact bug this guards against: RuntimeSafeToAirBanner and
    // EgressReadinessPanel are two different screens' translations of the
    // same EgressStateRow.state / ChannelRuntimeStatus.egress_state value.
    // Before the fix they disagreed ('Error' vs 'Needs attention'); the
    // post-condition is that the same condition produces the same words.
    const banner = render(
      <RuntimeSafeToAirBanner
        status={{
          ...greenStatus,
          color: 'red',
          label: 'A channel is off air',
          channels: [
            { channel_id: 'public', egress_state: 'ERROR', on_air: false, on_healthy_slate: false, color: 'red' },
          ],
        }}
      />,
    )
    expect(banner.getAllByText('Needs attention').length).toBeGreaterThanOrEqual(1)
    banner.unmount()

    const states = new Map<string, EgressStateRow | null>([
      [
        'public',
        {
          channel_id: 'public',
          state: 'ERROR',
          updated_at: '2026-06-15T12:00:00Z',
        },
      ],
    ])
    const panel = render(
      <EgressReadinessPanel
        channels={[CHANNEL]}
        states={states}
        health={new Map()}
        currency={new Map()}
        loading={false}
        error={null}
        pendingCommand={null}
        canControl={false}
        onCommand={vi.fn()}
      />,
    )
    expect(panel.getByText('Needs attention')).toBeTruthy()
    panel.unmount()
  })
})

describe('SelfTestPanel', () => {
  const selfTest: SystemSelfTest = {
    self_test_id: 'st-1',
    kind: 'daily',
    started_at: '2026-06-15T02:00:00Z',
    finished_at: '2026-06-15T02:01:00Z',
    status: 'fail',
    checks: { readiness: true, filesink_continuity: false },
    summary: 'Daily self-check found a problem.',
  }

  it('shows the empty state before any self-check has run', () => {
    const { container } = render(<SelfTestPanel selfTest={null} />)
    expect(container.textContent).toContain('has not run an automatic self-check yet')
  })

  it('renders the summary and one plain-English pill per sub-check', () => {
    const { container } = render(<SelfTestPanel selfTest={selfTest} />)
    expect(container.textContent).toContain('Daily self-check found a problem.')
    expect(container.textContent).toContain('Station readiness: ok')
    expect(container.textContent).toContain('Recording continuity: failed')
    // Skipped checks are honestly noted, not faked.
    expect(container.textContent).toContain('skipped here, not failed')
  })

  it('offers a weekly run when wired and shows a plain-English status', () => {
    const onRunWeekly = vi.fn()
    const { container, getByText } = render(
      <SelfTestPanel selfTest={selfTest} onRunWeekly={onRunWeekly} canRun />,
    )
    expect(container.textContent).toContain('Found a problem')  // friendly status pill, not "fail"
    fireEvent.click(getByText('Run weekly self-check now'))
    expect(onRunWeekly).toHaveBeenCalled()
  })

  it('runs a self-check when permitted', () => {
    const onRun = vi.fn()
    const { getByText } = render(<SelfTestPanel selfTest={null} onRun={onRun} canRun />)
    fireEvent.click(getByText('Run daily self-check now'))
    expect(onRun).toHaveBeenCalled()
  })

  it('blocks the run button and explains the role gate when not permitted', () => {
    const { container, getByText } = render(
      <SelfTestPanel selfTest={null} onRun={vi.fn()} canRun={false} />,
    )
    expect((getByText('Run daily self-check now') as HTMLButtonElement).disabled).toBe(true)
    expect(container.textContent).toContain('requires setup admin or support admin')
  })
})

describe('ResourceSnapshotPanel', () => {
  it('shows the empty state with no sample', () => {
    const { container } = render(<ResourceSnapshotPanel sample={null} />)
    expect(container.textContent).toContain('No resource sample has been taken yet.')
  })

  it('renders measured values in plain language', () => {
    const sample: SystemResourceSample = {
      sampled_at: '2026-06-15T12:00:00Z',
      cpu_percent: 42.4,
      ram_used_gb: 6,
      ram_total_gb: 16,
      media_volume_free_gb: 120.5,
      db_reachable: true,
      service_running: true,
    }
    const { container } = render(<ResourceSnapshotPanel sample={sample} />)
    expect(container.textContent).toContain('42% busy')
    expect(container.textContent).toContain('6.0 / 16.0 GB used')
    expect(container.textContent).toContain('120.5 GB free')
    expect(container.textContent).toContain('Reachable')
  })
})

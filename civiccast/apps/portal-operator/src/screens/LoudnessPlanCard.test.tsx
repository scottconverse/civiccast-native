import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { ChannelLoudnessPlan } from '../types/api.generated'
import { LoudnessPlanView } from './LoudnessPlanCard'

afterEach(cleanup)

const PLAN: ChannelLoudnessPlan = {
  channel_id: 'gov',
  baseline_target_lufs: -16,
  baseline_tolerance_lufs: 2,
  sinks: [
    {
      label: 'Cable',
      kind: 'udp-ts',
      regime: 'atsc-a85',
      effective_target_lufs: -24,
      tolerance_lufs: 2,
      standard_label: 'ATSC A/85 -24 LKFS (CALM Act)',
      short_label: 'Cable -24',
      explicit: true,
      requires_reencode: true,
    },
    {
      label: 'CDN',
      kind: 'srt',
      regime: 'streaming',
      effective_target_lufs: -16,
      tolerance_lufs: 2,
      standard_label: 'Streaming -16 LUFS (ITU-R BS.1770)',
      short_label: 'Streaming -16',
      explicit: true,
      requires_reencode: false,
    },
  ],
}

describe('LoudnessPlanView', () => {
  it('lists each sink with its regime, target, and standard', () => {
    const { container } = render(<LoudnessPlanView plan={PLAN} latestLoudnessLufs={-16.3} />)
    const text = container.textContent ?? ''
    expect(text).toContain('Cable -24')
    expect(text).toContain('-24.0 LUFS')
    expect(text).toContain('ATSC A/85 -24 LKFS (CALM Act)')
    expect(text).toContain('Streaming -16')
    expect(text).toContain('-16.0 LUFS')
    // The divergent cable sink is flagged as re-normalised.
    expect(text).toContain('re-normalised')
    // Last-measured loudness chip.
    expect(text).toContain('Measured -16.3 LUFS')
  })

  it('shows an empty state when no sinks are configured', () => {
    const { container } = render(<LoudnessPlanView plan={{ ...PLAN, sinks: [] }} />)
    expect(container.textContent).toContain('No egress outputs are configured')
  })

  it('shows a loading state', () => {
    const { container } = render(<LoudnessPlanView plan={undefined} loading />)
    expect(container.textContent).toContain('Loading the loudness plan')
  })

  it('surfaces a load error', () => {
    const { getByRole } = render(<LoudnessPlanView plan={undefined} error={new Error('nope')} />)
    expect(getByRole('alert').textContent).toContain('nope')
  })

  it('omits the measured chip when there is no measurement', () => {
    const { container } = render(<LoudnessPlanView plan={PLAN} latestLoudnessLufs={null} />)
    expect(container.textContent).not.toContain('Measured')
  })
})

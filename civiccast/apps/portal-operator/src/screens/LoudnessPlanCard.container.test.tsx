import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// The leaf LoudnessPlanView is tested elsewhere; this exercises the container's
// query wiring + the "most recent measurement wins" selection from health samples.
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getLoudnessPlan: vi.fn(),
  getEgressHealth: vi.fn(),
}))

import type { ChannelLoudnessPlan } from '../types/api.generated'
import { getEgressHealth, getLoudnessPlan } from '../api/client'
import type { EgressHealthSample } from '../api/client'
import { LoudnessPlanCard } from './LoudnessPlanCard'

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
  ],
}

function sample(sampledAt: string, lufs: number | null): EgressHealthSample {
  return {
    channel_id: 'gov',
    sampled_at: sampledAt,
    state: 'ON_AIR',
    last_loudness_lufs: lufs,
  } as unknown as EgressHealthSample
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <LoudnessPlanCard channelId="gov" />
    </QueryClientProvider>,
  )
}

describe('LoudnessPlanCard container', () => {
  it('renders the resolved per-sink plan from the API', async () => {
    vi.mocked(getLoudnessPlan).mockResolvedValue(PLAN)
    vi.mocked(getEgressHealth).mockResolvedValue([])
    const { findByText } = renderCard()
    expect(await findByText('Cable -24')).toBeTruthy()
  })

  it('shows the most recent measured loudness regardless of sample order', async () => {
    vi.mocked(getLoudnessPlan).mockResolvedValue(PLAN)
    // Out-of-order samples with a null in the mix; the newest real reading wins.
    vi.mocked(getEgressHealth).mockResolvedValue([
      sample('2026-01-01T12:00:00Z', -15.0),
      sample('2026-01-01T12:05:00Z', -16.4),
      sample('2026-01-01T12:03:00Z', null),
    ])
    const { findByText } = renderCard()
    expect(await findByText(/Measured -16\.4 LUFS/)).toBeTruthy()
  })
})

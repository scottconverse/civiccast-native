import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'

import type { CaptionStatusResponse, EgressCaptionProofSample } from '../types/api.generated'
import { CaptionStatusView } from './CaptionStatusCard'

afterEach(cleanup)

function proof(overrides: Partial<EgressCaptionProofSample> = {}): EgressCaptionProofSample {
  return {
    channel_id: 'gov',
    sampled_at: '2026-01-01T12:00:00Z',
    status: 'PASS',
    caption_status: 'on',
    mode: 'cea-708',
    decoder_name: 'ffmpeg-subcc',
    expected_cue_count: 2,
    decoded_cue_count: 2,
    matched_cue_count: 2,
    max_timing_delta_seconds: 0.1,
    proof_boundary: 'egress-caption-embed-to-emitted-stream-decode-back',
    ...overrides,
  } as EgressCaptionProofSample
}

const ON: CaptionStatusResponse = { channel_id: 'gov', caption_status: 'on', latest: proof() }
const NOT_VERIFIED: CaptionStatusResponse = {
  channel_id: 'gov',
  caption_status: 'not-verified',
  latest: null,
}

describe('CaptionStatusView', () => {
  it('shows Captions on for a proven channel and states the honesty boundary', () => {
    const { container } = render(<CaptionStatusView status={ON} proofs={[proof()]} />)
    const text = container.textContent ?? ''
    expect(text).toContain('Captions on')
    expect(text).toContain('not a claim of FCC Part')
    expect(text).toContain('2/2')
    expect(text).toContain('PASS')
  })

  it('shows Not verified and an empty proof state', () => {
    const { container } = render(<CaptionStatusView status={NOT_VERIFIED} proofs={[]} />)
    expect(container.textContent).toContain('Not verified')
    expect(container.textContent).toContain('No caption decode-back proofs yet')
  })

  it('renders a FAIL proof with its blocker and unmatched count', () => {
    const failing = proof({
      status: 'FAIL',
      caption_status: 'not-verified',
      matched_cue_count: 0,
      blocker: 'EGRESS_CAPTION_DECODE_BACK_MISMATCH',
    })
    const { container } = render(<CaptionStatusView status={NOT_VERIFIED} proofs={[failing]} />)
    expect(container.textContent).toContain('FAIL')
    expect(container.textContent).toContain('EGRESS_CAPTION_DECODE_BACK_MISMATCH')
    expect(container.textContent).toContain('0/2')
  })

  it('surfaces a load error', () => {
    const { getByRole } = render(
      <CaptionStatusView status={undefined} proofs={undefined} error={new Error('boom')} />,
    )
    expect(getByRole('alert').textContent).toContain('boom')
  })
})

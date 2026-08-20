import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type { SampleSeedStatus } from '../types/api.generated'
import { SampleSeedNoticeView } from './SampleSeedNotice'

afterEach(cleanup)

const NOT_APPLICABLE: SampleSeedStatus = {
  status: 'not_applicable',
  sample_content_enabled: false,
  initial_schedule_enabled: true,
  dismissed: false,
  message: 'Sample content was turned off during setup, so nothing was seeded.',
  next_step: 'Add real content from Assets and build your schedule from Schedule when you\'re ready.',
}

const PENDING: SampleSeedStatus = {
  status: 'pending',
  sample_content_enabled: true,
  initial_schedule_enabled: true,
  dismissed: false,
  message: 'CivicCast is preparing the sample video and starter schedule.',
  next_step: 'This finishes in the background; check back in a few seconds.',
}

const SUCCEEDED: SampleSeedStatus = {
  status: 'succeeded',
  sample_content_enabled: true,
  initial_schedule_enabled: true,
  asset_id: 'sample-welcome-abc123',
  schedule_item_id: '3f5b6c1a-1111-4444-9999-abcdefabcdef',
  dismissed: false,
  message: 'CivicCast published a sample video to the portal and created a starter schedule item.',
  next_step: 'Review it on Assets, then replace it with real content when you\'re ready.',
}

const FAILED: SampleSeedStatus = {
  status: 'failed',
  sample_content_enabled: true,
  initial_schedule_enabled: true,
  asset_id: null,
  failed_step: 'package',
  error_message: 'FFmpeg could not create the sample video.',
  dismissed: false,
  message: 'CivicCast could not finish packaging the sample video for playback: FFmpeg could not create the sample video.',
  next_step: 'Retry sample setup, or add content and a schedule manually.',
}

describe('SampleSeedNoticeView', () => {
  it('renders nothing when there is nothing to seed', () => {
    const { container } = render(
      <SampleSeedNoticeView
        status={NOT_APPLICABLE}
        canRetry
        onDismiss={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(container.textContent).toBe('')
  })

  it('renders nothing while seeding is pending', () => {
    const { container } = render(
      <SampleSeedNoticeView status={PENDING} canRetry onDismiss={vi.fn()} onRetry={vi.fn()} />,
    )
    expect(container.textContent).toBe('')
  })

  it('renders nothing on success -- the content itself is the proof', () => {
    const { container } = render(
      <SampleSeedNoticeView status={SUCCEEDED} canRetry onDismiss={vi.fn()} onRetry={vi.fn()} />,
    )
    expect(container.textContent).toBe('')
  })

  it('shows a loud, specific failure notice naming the step and the error', () => {
    const { container } = render(
      <SampleSeedNoticeView status={FAILED} canRetry onDismiss={vi.fn()} onRetry={vi.fn()} />,
    )
    expect(container.textContent).toContain('could not finish first-run sample setup')
    expect(container.textContent).toContain('packaging the sample video for playback')
    expect(container.textContent).toContain('FFmpeg could not create the sample video.')
  })

  it('fires onRetry when the operator clicks retry', () => {
    const onRetry = vi.fn()
    const { getByText } = render(
      <SampleSeedNoticeView status={FAILED} canRetry onDismiss={vi.fn()} onRetry={onRetry} />,
    )
    fireEvent.click(getByText('Retry sample setup'))
    expect(onRetry).toHaveBeenCalled()
  })

  it('fires onDismiss when the operator dismisses the notice', () => {
    const onDismiss = vi.fn()
    const { getByLabelText } = render(
      <SampleSeedNoticeView status={FAILED} canRetry onDismiss={onDismiss} onRetry={vi.fn()} />,
    )
    fireEvent.click(getByLabelText('Dismiss this notice'))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('hides the retry action when the operator lacks a role the server would accept', () => {
    const { queryByText, container } = render(
      <SampleSeedNoticeView status={FAILED} canRetry={false} onDismiss={vi.fn()} onRetry={vi.fn()} />,
    )
    expect(queryByText('Retry sample setup')).toBeNull()
    // The dismiss action still works regardless of role.
    expect(container.textContent).toContain('Dismiss')
  })

  it('stays hidden once the operator has dismissed a failed notice', () => {
    const { container } = render(
      <SampleSeedNoticeView
        status={{ ...FAILED, dismissed: true }}
        canRetry
        onDismiss={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(container.textContent).toBe('')
  })

  it('shows a retry-failed message distinct from the seeding failure itself', () => {
    const { container } = render(
      <SampleSeedNoticeView
        status={FAILED}
        canRetry
        retryError={new Error('network down')}
        onDismiss={vi.fn()}
        onRetry={vi.fn()}
      />,
    )
    expect(container.textContent).toContain('Retry failed: network down')
  })
})

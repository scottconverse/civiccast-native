import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type { DrillReport, RestoreStatus } from '../types/api.generated'
import { RestorePanel } from './SystemHealthScreen'

afterEach(cleanup)

const restore = {
  generated_at: '2026-07-15T00:00:00Z',
  status: 'needs_attention',
  message: 'A real database restore drill has not run.',
  next_step: 'Run the real database restore drill.',
} satisfies RestoreStatus

describe('RestorePanel', () => {
  it('offers the real isolated database drill separately from a storage check', () => {
    const onRun = vi.fn()
    const onRunReal = vi.fn()
    const { getByRole } = render(
      <RestorePanel
        restore={restore}
        onRun={onRun}
        onRunReal={onRunReal}
        running={false}
        runningReal={false}
        canRun
      />,
    )

    fireEvent.click(getByRole('button', { name: 'Run real database restore drill' }))

    expect(onRunReal).toHaveBeenCalledOnce()
    expect(onRun).not.toHaveBeenCalled()
  })

  it('reports the exact proven scope after the drill passes', () => {
    const realDrill = {
      restore: {
        schema_ok: true,
        errors: [],
        tables: [{}, {}, {}],
      },
      crash: {
        results: [{ name: 'restart', ok: true, detail: 'ok', duration_seconds: 0.1 }],
      },
    } as unknown as DrillReport
    const { getByText } = render(
      <RestorePanel
        restore={restore}
        realDrill={realDrill}
        onRun={vi.fn()}
        onRunReal={vi.fn()}
        running={false}
        runningReal={false}
        canRun
      />,
    )

    expect(getByText('Real database restore drill passed')).toBeTruthy()
    expect(getByText(/Verified 3 database tables in an isolated copy/)).toBeTruthy()
    expect(getByText(/media, configuration, and credentials remain separate/)).toBeTruthy()
  })
})

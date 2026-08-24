import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import { ApiError } from '../api/client'
import type { GstreamerRepairResponse } from '../types/api.generated'
import { GstreamerRepairPanel } from './SystemHealthScreen'

afterEach(cleanup)

describe('GstreamerRepairPanel', () => {
  it('is disabled and explains the role gate when the operator cannot run it', () => {
    const { getByRole, getByText } = render(
      <GstreamerRepairPanel onRun={vi.fn()} running={false} canRun={false} />,
    )
    const button = getByRole('button', {
      name: /Repair GStreamer runtime & restore full egress/i,
    }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(getByText(/requires setup admin or support admin/i)).toBeTruthy()
  })

  it('invokes onRun (the confirm dialog is the caller\'s responsibility) when clicked', () => {
    const onRun = vi.fn()
    const { getByRole } = render(<GstreamerRepairPanel onRun={onRun} running={false} canRun />)
    fireEvent.click(
      getByRole('button', { name: /Repair GStreamer runtime & restore full egress/i }),
    )
    expect(onRun).toHaveBeenCalledOnce()
  })

  it('shows a loading label and disables the button while running', () => {
    const { getByRole } = render(
      <GstreamerRepairPanel onRun={vi.fn()} running canRun />,
    )
    const button = getByRole('button', { name: /Repairing…/i })
    expect((button as HTMLButtonElement).disabled).toBe(true)
  })

  it('surfaces an already-healthy result with an ok tone', () => {
    const result: GstreamerRepairResponse = {
      triggered: false,
      closure_healthy: true,
      remedy: 'already-healthy',
      detail: 'The closure verified clean; nothing to repair.',
    }
    const { getByText } = render(
      <GstreamerRepairPanel result={result} onRun={vi.fn()} running={false} canRun />,
    )
    expect(getByText(/already healthy — nothing to repair/i)).toBeTruthy()
    expect(getByText(/The closure verified clean; nothing to repair\./i)).toBeTruthy()
  })

  it('surfaces a restage-launched result with the PID', () => {
    const result: GstreamerRepairResponse = {
      triggered: true,
      closure_healthy: false,
      remedy: 'restage-launched',
      detail: 'Launched a signed re-stage of native-app-payload.',
      pid: 4242,
    }
    const { getByText } = render(
      <GstreamerRepairPanel result={result} onRun={vi.fn()} running={false} canRun />,
    )
    expect(getByText(/signed re-stage of the GStreamer runtime was launched/i)).toBeTruthy()
    expect(getByText(/PID 4242/)).toBeTruthy()
    expect(getByText(/still degraded/i)).toBeTruthy()
  })

  it('surfaces an error state', () => {
    const { getByRole } = render(
      <GstreamerRepairPanel
        onRun={vi.fn()}
        running={false}
        canRun
        error={new ApiError('Request failed: 503', 503, 'setup_admin required.')}
      />,
    )
    expect(getByRole('alert').textContent).toContain('setup_admin required.')
  })
})

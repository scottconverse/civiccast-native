import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

import type { TsduckStatus } from '../types/api.generated'
import { TsduckStatusView } from './CableVerificationCard'

afterEach(cleanup)

const NOT_INSTALLED: TsduckStatus = { installed: false, install_hint: 'use the operator console' }
const INSTALLED: TsduckStatus = {
  installed: true,
  path: 'C:/managed/TSDuck/bin/tsp.exe',
  version: 'tsp: TSDuck ... version 3.44-4676',
  install_hint: '',
}

describe('TsduckStatusView', () => {
  it('offers a plain-English enable action when TSDuck is missing', () => {
    const onInstall = vi.fn()
    const { container, getByText } = render(
      <TsduckStatusView status={NOT_INSTALLED} canInstall onInstall={onInstall} />,
    )
    expect(container.textContent).toContain('downloads the free TSDuck toolkit for you')
    expect(container.textContent).toContain('bounded transport check')
    fireEvent.click(getByText('Enable cable verification'))
    expect(onInstall).toHaveBeenCalled()
  })

  it('shows Ready and the version when installed, with no enable button', () => {
    const { container, queryByText } = render(<TsduckStatusView status={INSTALLED} />)
    expect(container.textContent).toContain('Ready')
    expect(container.textContent).toContain('bounded TSDuck transport check')
    expect(container.textContent).toContain('3.44-4676')
    expect(queryByText('Enable cable verification')).toBeNull()
  })

  it('gates the enable action behind admin roles', () => {
    const { container, getByText } = render(
      <TsduckStatusView status={NOT_INSTALLED} canInstall={false} onInstall={vi.fn()} />,
    )
    expect((getByText('Enable cable verification') as HTMLButtonElement).disabled).toBe(true)
    expect(container.textContent).toContain('requires setup admin or support admin')
  })

  it('shows a downloading state while installing', () => {
    const { container } = render(
      <TsduckStatusView status={NOT_INSTALLED} canInstall installing onInstall={vi.fn()} />,
    )
    expect(container.textContent).toContain('Downloading TSDuck')
  })

  it('surfaces an operator-assisted report message (non-Windows)', () => {
    const { container } = render(
      <TsduckStatusView
        status={NOT_INSTALLED}
        canInstall
        onInstall={vi.fn()}
        report={{ status: 'operator-assisted', message: 'On macOS, install TSDuck with Homebrew: brew install tsduck.' }}
      />,
    )
    expect(container.textContent).toContain('brew install tsduck')
  })

  it('shows an install-specific error (not the status-load fallback) when the install throws', () => {
    const { container } = render(
      <TsduckStatusView status={NOT_INSTALLED} canInstall onInstall={vi.fn()} installError={new Error('boom')} />,
    )
    expect(container.textContent).toContain('boom')
    expect(container.textContent).not.toContain('status could not load')
  })
})

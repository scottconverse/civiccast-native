import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TopBar } from './TopBar'

describe('TopBar theme control', () => {
  it('uses a recognizable icon instead of an unexplained D/L glyph', () => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { getByRole } = render(
      <QueryClientProvider client={queryClient}>
        <TopBar />
      </QueryClientProvider>,
    )

    const toggle = getByRole('button', { name: 'Switch to dark theme' })
    expect(toggle.textContent).toBe('')
    expect(toggle.querySelector('svg')).toBeTruthy()
  })
})

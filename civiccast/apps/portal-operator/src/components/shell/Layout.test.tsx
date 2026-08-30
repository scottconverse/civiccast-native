import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { Layout } from './Layout'

function renderLayout() {
  Object.defineProperty(window, 'innerWidth', { value: 390, configurable: true })
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() {
      return document.body
    },
  })
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Layout route="live" onNavigate={vi.fn()} roles={['setup_admin']}>
          <button type="button">Main content action</button>
        </Layout>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Layout skip link and main landmark (W-3)', () => {
  it('renders a skip link as the first child, targeting the id\'d main landmark', () => {
    const { container, getByRole } = renderLayout()

    const skipLink = getByRole('link', { name: 'Skip to main content' }) as HTMLAnchorElement
    expect(skipLink.getAttribute('href')).toBe('#main-content')
    // Explicit tabIndex=0: required for WebKit/Safari, which by default
    // excludes plain links from the Tab sequence.
    expect(skipLink.tabIndex).toBe(0)
    // Visually hidden until focused (Tailwind's sr-only utility).
    expect(skipLink.className).toMatch(/\bsr-only\b/)
    expect(skipLink.className).toMatch(/\bfocus:not-sr-only\b/)

    // First child of the shell root -- i.e. the first element any keyboard
    // user reaches, before the top bar and the primary navigation.
    const root = container.firstElementChild
    expect(root?.firstElementChild).toBe(skipLink)

    const main = container.querySelector('main')
    expect(main?.getAttribute('id')).toBe('main-content')
    expect((main as HTMLElement | null)?.tabIndex).toBe(-1)
  })

  it('moves focus to main content without overwriting the route hash (regression)', () => {
    // This shell renders inside a react-router HashRouter (main.tsx), which
    // treats any hashchange as a navigation. A plain hash-link activation
    // would route to the unmatched pathname "main-content" instead of just
    // moving focus -- assert the fix's imperative-focus handler prevents
    // that by leaving the current route hash untouched.
    window.location.hash = '#/assets'
    try {
      const { getByRole, container } = renderLayout()
      const skipLink = getByRole('link', { name: 'Skip to main content' })
      const main = container.querySelector('main') as HTMLElement

      fireEvent.click(skipLink)

      expect(document.activeElement).toBe(main)
      expect(window.location.hash).toBe('#/assets')
    } finally {
      window.location.hash = ''
    }
  })
})

describe('Layout mobile navigation', () => {
  it('traps Tab focus while the mobile drawer is open', () => {
    const { getByLabelText, getByRole } = renderLayout()

    const menuButton = getByLabelText('Open navigation')
    menuButton.focus()
    fireEvent.click(menuButton)

    getByRole('dialog', { name: 'Primary navigation' })
    // The Help section (the in-product manual) is now the first nav
    // section, collapsed by default like Setup was -- same toggle
    // behavior, new label.
    const first = getByLabelText('Show Help navigation')
    const last = getByRole('link', { name: 'Report a beta issue' })
    expect(document.activeElement).toBe(first)

    last.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement).toBe(first)

    first.focus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last)

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(document.activeElement).toBe(menuButton)
  })
})

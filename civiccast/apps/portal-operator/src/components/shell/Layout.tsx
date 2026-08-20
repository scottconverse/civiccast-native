import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { TopBar } from './TopBar'
import { Sidebar } from './Sidebar'
import type { RoleName, RouteId } from './Sidebar'
import { useFocusTrap } from '../../hooks/useFocusTrap'

interface LayoutProps {
  route: RouteId | null
  onNavigate: (id: RouteId) => void
  children: ReactNode
  /** Roles held by the current operator, forwarded to the Sidebar so it can
   *  hide role-gated nav entries (UX-1, S26 gauntletgate). Undefined while
   *  identity is loading — role-gated entries fail closed in that state. */
  roles?: readonly RoleName[]
}

/** DOM id of the operator shell's `<main>` landmark. Shared by the skip
 *  link's target (W-3) and route-change focus management (UX-MAJOR-2, App.tsx)
 *  so both features move focus to the exact same element. */
export const MAIN_CONTENT_ID = 'main-content'

const MOBILE_BREAKPOINT_PX = 768

/** First focusable element on every operator screen (W-3, WCAG 2.4.1). Lets
 *  keyboard and screen-reader users jump straight past the top bar and the
 *  ~20-entry primary navigation to the screen's own content. Hidden until
 *  focused via Tailwind's `sr-only` / `focus:not-sr-only` pair (the same
 *  visually-hidden convention the operator console already uses for
 *  screen-reader-only text, e.g. AssetsScreen's `sr-only` cells) and styled
 *  with the shell's own tokens so it reads as part of the product, not a
 *  raw unstyled link. */
function SkipToContentLink() {
  // Plain hash navigation would overwrite the app's own route: this shell
  // renders inside a react-router `HashRouter` (main.tsx), which treats any
  // `hashchange` as a navigation, so activating a bare
  // `href="#main-content"` would route to the unmatched pathname
  // "main-content" and land the operator on the Page-not-found screen
  // instead of just moving focus. Move focus imperatively and suppress the
  // default hash navigation so the current route is left untouched.
  const handleActivate = (event: ReactMouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    document.getElementById(MAIN_CONTENT_ID)?.focus({ preventScroll: false })
  }
  return (
    <a
      href={`#${MAIN_CONTENT_ID}`}
      onClick={handleActivate}
      // Explicit tabIndex=0 (redundant in Chromium/Firefox, required in
      // WebKit/Safari): by default WebKit only puts form controls in the
      // Tab sequence, not plain links, unless "Full Keyboard Access" is on
      // -- without this the skip link would be unreachable by keyboard for
      // every default-configuration Safari user.
      tabIndex={0}
      className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:px-4 focus:py-2 focus:text-sm focus:font-semibold"
      style={{
        background: 'var(--cc-surface)',
        color: 'var(--cc-ink)',
        border: '1px solid var(--cc-line-strong)',
        boxShadow: 'var(--cc-shadow-lg)',
      }}
    >
      Skip to main content
    </a>
  )
}

function MobileNavigationDrawer({
  route,
  onNavigate,
  onClose,
  roles,
}: {
  route: RouteId | null
  onNavigate: (id: RouteId) => void
  onClose: () => void
  roles?: readonly RoleName[]
}) {
  const drawerRef = useRef<HTMLDivElement | null>(null)
  useFocusTrap(drawerRef)

  return (
    <>
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        className="fixed inset-0 z-40"
        style={{
          background: 'rgb(0 0 0 / 0.45)',
          top: 'var(--cc-topbar-h)',
        }}
      />
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label="Primary navigation"
        className="fixed bottom-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col"
        style={{
          top: 'var(--cc-topbar-h)',
          background: 'var(--cc-surface)',
          borderRight: '1px solid var(--cc-line)',
          boxShadow: 'var(--cc-shadow-lg)',
        }}
      >
        <Sidebar route={route} onNavigate={onNavigate} roles={roles} />
      </div>
    </>
  )
}

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < MOBILE_BREAKPOINT_PX
  })

  useEffect(() => {
    // Single subscription point — the matchMedia change handler is the
    // sole writer of `isMobile` after mount. The initial value is set
    // by the useState initializer above, so we don't need to call
    // setIsMobile() synchronously here (which would trigger a redundant
    // re-render and trip react-hooks/set-state-in-effect).
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return isMobile
}

export function Layout({ route, onNavigate, children, roles }: LayoutProps) {
  const isMobile = useIsMobile()
  const [drawerOpen, setDrawerOpen] = useState(false)

  // When the viewport grows back to desktop, the drawer state becomes
  // irrelevant — the desktop layout doesn't render it. Compute the
  // effective drawer state at render time so we don't need a
  // setState-in-effect to "auto-close" a drawer that's already off-screen.
  const effectiveDrawerOpen = isMobile && drawerOpen

  const handleNavigate = (id: RouteId) => {
    onNavigate(id)
    if (isMobile) setDrawerOpen(false)
  }

  // Close on Escape so keyboard users can dismiss the drawer.
  useEffect(() => {
    if (!effectiveDrawerOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [effectiveDrawerOpen])

  if (isMobile) {
    return (
      <div className="flex h-full flex-col">
        <SkipToContentLink />
        <TopBar
          onMenuClick={() => setDrawerOpen(true)}
          showMenuButton
        />
        <main
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
          className="flex-1 overflow-y-auto"
          style={{ background: 'var(--cc-paper)' }}
        >
          {children}
        </main>

        {effectiveDrawerOpen && (
          <MobileNavigationDrawer
            route={route}
            onNavigate={handleNavigate}
            onClose={() => setDrawerOpen(false)}
            roles={roles}
          />
        )}
      </div>
    )
  }

  return (
    <div
      className="grid h-full"
      style={{
        gridTemplateColumns: 'var(--cc-sidebar-w) 1fr',
        gridTemplateRows: 'var(--cc-topbar-h) 1fr',
      }}
    >
      <SkipToContentLink />
      <TopBar />
      <Sidebar route={route} onNavigate={onNavigate} roles={roles} />
      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="overflow-y-auto"
        style={{
          gridRow: '2',
          gridColumn: '2',
          background: 'var(--cc-paper)',
        }}
      >
        {children}
      </main>
    </div>
  )
}

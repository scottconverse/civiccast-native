import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getCivicCastVersion, getStaffIdentity } from '../../api/client'
import { ROLE_LABELS } from '../../auth/roles'

declare global {
  interface Window {
    __CIVICCAST_VERSION__?: string
  }
}

function bundledVersion(): string | undefined {
  const runtimeVersion =
    typeof window === 'undefined' ? undefined : window.__CIVICCAST_VERSION__
  return runtimeVersion ?? import.meta.env.VITE_CIVICCAST_VERSION
}

function Logo() {
  const versionQuery = useQuery({
    queryKey: ['civiccast-version'],
    queryFn: getCivicCastVersion,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  const version = versionQuery.data?.version ?? bundledVersion()
  const versionLabel = version ? `v${version}` : undefined
  return (
    <div className="flex items-center gap-2.5">
      <div
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-md text-base font-semibold"
        style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
      >
        C
      </div>
      {/* Brand wordmark; the mounted screen owns the page-level h1. */}
      <div className="m-0 text-base font-semibold tracking-tight">
        CivicCast
        {versionLabel && (
          <sup className="cc-mono ml-1 text-[10px] font-normal" style={{ color: 'var(--cc-ink-3)' }}>
            {versionLabel}
          </sup>
        )}
      </div>
    </div>
  )
}

function StreamingPill() {
  // Sprint 0.3: no live module yet; pill always idle.
  // Audit UX-007: this pill describes MEETING broadcasts only - say so,
  // because 24/7 channels can be on air while no meeting is live and the
  // old "Off air / No active broadcast" read as a contradiction.
  return (
    <div
      role="status"
      aria-label="No live meeting broadcast"
      className="flex items-center gap-2 rounded-full px-3 py-1 text-xs"
      style={{
        background: 'var(--cc-surface-2)',
        border: '1px solid var(--cc-line)',
        color: 'var(--cc-ink-2)',
      }}
    >
      <span
        aria-hidden="true"
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: 'var(--cc-ink-3)' }}
      />
      <span className="cc-truncate max-w-[220px]">No live meeting broadcast</span>
    </div>
  )
}

function Clock() {
  const [now, setNow] = useState<Date>(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30000)
    return () => clearInterval(id)
  }, [])

  const time = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

  return (
    <div className="hidden items-center gap-2 text-xs md:flex" aria-label="Local time and next event">
      <span style={{ color: 'var(--cc-ink-3)' }}>Local</span>
      <span className="cc-mono cc-tabular">{time}</span>
      <span style={{ color: 'var(--cc-ink-3)' }}>/</span>
      <span style={{ color: 'var(--cc-ink-3)' }}>Next</span>
      <span className="cc-truncate max-w-[180px]">No events scheduled</span>
    </div>
  )
}

function ThemeToggle() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const stored = document.documentElement.getAttribute('data-theme')
    return stored === 'dark' ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const label = `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-xs"
      style={{
        background: 'transparent',
        border: '1px solid var(--cc-line)',
        color: 'var(--cc-ink-2)',
      }}
    >
      {theme === 'dark' ? (
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41" />
        </svg>
      ) : (
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
        </svg>
      )}
    </button>
  )
}

function operatorInitials(name: string | undefined): string {
  if (!name) return 'OP'
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return 'OP'
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join('')
}

function OperatorBadge() {
  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const identity = identityQuery.data
  const roleTitle = identity?.roles?.map((role) => ROLE_LABELS[role]).join(', ') || 'No roles'
  return (
    <div
      title={identity ? `${identity.operator_display_name} / ${roleTitle}` : 'Operator'}
      aria-label={identity ? `${identity.operator_display_name}, ${roleTitle}` : 'Operator'}
      className="flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-xs font-semibold"
      style={{ background: 'var(--cc-brand-soft)', color: 'var(--cc-brand-2)' }}
    >
      {operatorInitials(identity?.operator_display_name)}
    </div>
  )
}

function MenuButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Open navigation"
      onClick={onClick}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md"
      style={{
        background: 'transparent',
        border: '1px solid var(--cc-line)',
        color: 'var(--cc-ink-2)',
      }}
    >
      {/* Inline three-bar SVG so we don't pull an icon library for one glyph */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>
  )
}

interface TopBarProps {
  showMenuButton?: boolean
  onMenuClick?: () => void
}

export function TopBar({ showMenuButton = false, onMenuClick }: TopBarProps = {}) {
  return (
    <header
      role="banner"
      className="flex items-center gap-3 px-3 sm:gap-4 sm:px-4"
      style={{
        height: 'var(--cc-topbar-h)',
        background: 'var(--cc-surface)',
        borderBottom: '1px solid var(--cc-line)',
        gridColumn: '1 / -1',
      }}
    >
      {showMenuButton && onMenuClick && <MenuButton onClick={onMenuClick} />}
      <Logo />
      <div className="hidden flex-1 items-center justify-center gap-3 md:flex">
        <StreamingPill />
        <Clock />
      </div>
      {/* Mobile: skip the centered streaming/clock block; the topbar
          stays compact so the hamburger + brand + theme/avatar fit. */}
      <div className="ml-auto flex items-center gap-2 md:ml-0">
        <ThemeToggle />
        <div
          aria-hidden="true"
          className="h-6 w-px"
          style={{ background: 'var(--cc-line)' }}
        />
        <OperatorBadge />
      </div>
    </header>
  )
}

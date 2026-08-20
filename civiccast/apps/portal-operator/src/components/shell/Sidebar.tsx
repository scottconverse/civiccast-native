// v1.3 foundation: the shell groups existing routes by operator job.
// Role-aware filtering: nav items with `requiredRoles` are hidden from
// identities that don't hold any of those roles. The screen-level role gate
// (e.g. PaywallScreen's Forbidden banner) is the defense-in-depth — a user
// who navigates by URL still sees the gate. See UX-1 (S26 gauntletgate).

import { useState } from 'react'

import type { StaffIdentityResponse } from '../../types/api.generated'

export type RoleName = NonNullable<StaffIdentityResponse['roles']>[number]

export type RouteId =
  | 'setup'
  | 'live'
  | 'facility'
  | 'controlroom'
  | 'controlroomsetup'
  | 'remotecontribution'
  | 'channels'
  | 'cg'
  | 'cgdesigner'
  | 'today'
  | 'schedule'
  | 'autoschedule'
  | 'guide'
  | 'assets'
  | 'contribute'
  | 'review'
  | 'summary'
  | 'publish'
  | 'playback'
  | 'analytics'
  | 'appadmin'
  | 'archive'
  | 'subscribers'
  | 'activitypub'
  | 'health'
  | 'alerts'
  | 'eas'
  | 'ai-models'
  | 'custom-fields'
  | 'reports'
  | 'epg'
  | 'underwriting'
  | 'agendas'
  | 'paywall'
  | 'recording'

interface NavItem {
  id: RouteId
  label: string
  count?: number
  disabled?: boolean
  plannedLabel?: string
  /** Roles allowed to see this entry. When undefined, the entry is visible
   *  to every authenticated operator. When set, an identity must hold AT
   *  LEAST ONE of the listed roles for the entry to render. The screen
   *  itself must still gate by role — this filter is a UX dead-end fix
   *  (UX-1, S26 gauntletgate), not a security boundary. */
  requiredRoles?: RoleName[]
}

interface NavSection {
  label: string
  summary: string
  items: NavItem[]
  collapsedByDefault?: boolean
}

const PROFILE = {
  org: 'CivicCast station',
  sub: 'Public meetings',
}

const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Setup',
    summary: 'Admin setup and station configuration',
    collapsedByDefault: true,
    items: [
      { id: 'setup', label: 'First Setup' },
      { id: 'controlroomsetup', label: 'Control Room Setup', requiredRoles: ['setup_admin'] },
      { id: 'ai-models', label: 'AI Models', requiredRoles: ['setup_admin', 'meeting_operator'] },
      { id: 'custom-fields', label: 'Custom Fields', requiredRoles: ['setup_admin'] },
      { id: 'paywall', label: 'Paywall', requiredRoles: ['setup_admin'] },
    ],
  },
  {
    label: 'Run Meeting',
    summary: 'Night-of-broadcast controls',
    items: [
      { id: 'live', label: 'Live' },
      { id: 'facility', label: 'Facility' },
      { id: 'controlroom', label: 'Control Room' },
      { id: 'remotecontribution', label: 'Remote Contribution', requiredRoles: ['setup_admin', 'support_admin', 'meeting_operator'] },
      { id: 'channels', label: 'Channels' },
      { id: 'cg', label: 'CG Board' },
      { id: 'cgdesigner', label: 'CG Designer', requiredRoles: ['publish_operator', 'setup_admin', 'support_admin'] },
      { id: 'schedule', label: 'Schedule' },
      { id: 'autoschedule', label: 'Auto-schedule', requiredRoles: ['publish_operator', 'setup_admin', 'support_admin'] },
      { id: 'guide', label: 'Program Guide' },
      {
        id: 'recording',
        label: 'Recording',
        requiredRoles: ['setup_admin', 'meeting_operator', 'support_admin'],
      },
    ],
  },
  {
    label: 'Review Records',
    summary: 'Assets, captions, summaries, agendas, and signed records',
    items: [
      { id: 'assets', label: 'Assets' },
      { id: 'contribute', label: 'Contributors' },
      { id: 'review', label: 'Review queue' },
      { id: 'summary', label: 'Summary review' },
      { id: 'agendas', label: 'Agendas', requiredRoles: ['records_clerk', 'meeting_operator'] },
    ],
  },
  {
    label: 'Publish',
    summary: 'Resident portal, archives, and notifications',
    items: [
      { id: 'publish', label: 'Publish' },
      { id: 'playback', label: 'Playback policy' },
      { id: 'analytics', label: 'Analytics' },
      { id: 'reports', label: 'Reports', requiredRoles: ['support_admin'] },
      { id: 'epg', label: 'EPG Export', requiredRoles: ['setup_admin', 'publish_operator'] },
      { id: 'underwriting', label: 'Underwriting', requiredRoles: ['setup_admin', 'publish_operator', 'support_admin'] },
      { id: 'appadmin', label: 'App Admin', requiredRoles: ['setup_admin', 'publish_operator'] },
    ],
  },
  {
    label: 'System Health',
    summary: 'Readiness, federation, and advanced health',
    collapsedByDefault: true,
    items: [
      { id: 'health', label: 'Readiness' },
      { id: 'alerts', label: 'Alerts' },
      { id: 'eas', label: 'Emergency Alerts', requiredRoles: ['setup_admin', 'support_admin', 'meeting_operator'] },
      { id: 'activitypub', label: 'Federation' },
    ],
  },
]

interface SidebarProps {
  route: RouteId | null
  onNavigate: (id: RouteId) => void
  /** Roles held by the current operator. When undefined, role-filtered
   *  items are hidden by default (fail-closed). Callers that don't have
   *  identity loaded yet should pass undefined and re-render once the
   *  identity arrives. */
  roles?: readonly RoleName[]
}

/** True when the entry should be shown to an identity holding `roles`.
 *  Entries with no `requiredRoles` are always shown; entries with
 *  `requiredRoles` need at least one match. Undefined `roles` means
 *  identity hasn't loaded yet — fail closed, hide the role-gated entry. */
function isItemVisible(item: NavItem, roles: readonly RoleName[] | undefined): boolean {
  if (!item.requiredRoles || item.requiredRoles.length === 0) return true
  if (!roles) return false
  return item.requiredRoles.some((r) => roles.includes(r))
}

function NavRow({
  item,
  active,
  onClick,
}: {
  item: NavItem
  active: boolean
  onClick: () => void
}) {
  const disabled = item.disabled ?? false
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      aria-current={active ? 'page' : undefined}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      title={disabled && item.plannedLabel ? `${item.label} is planned for a later public-beta update.` : undefined}
      className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm transition-colors"
      style={{
        background: active ? 'var(--cc-brand-soft)' : 'transparent',
        color: disabled ? 'var(--cc-ink-3)' : active ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
        opacity: disabled ? 0.55 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontWeight: active ? 500 : 400,
      }}
    >
      <span>{item.label}</span>
      {item.count != null && !disabled && (
        <span
          className="cc-mono cc-tabular rounded-full px-1.5 py-0.5 text-[10px]"
          style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
        >
          {item.count}
        </span>
      )}
      {disabled && item.plannedLabel && (
        <span
          className="cc-mono rounded-full px-1.5 py-0.5 text-[9px]"
          style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-3)' }}
        >
          {item.plannedLabel}
        </span>
      )}
    </button>
  )
}

function ProfileCard() {
  return (
    <div
      className="flex items-center gap-2.5 rounded-md px-3 py-2.5"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
    >
      <div
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-md text-xs font-semibold"
        style={{ background: 'var(--cc-brand-soft)', color: 'var(--cc-brand-2)' }}
      >
        CC
      </div>
      <div className="min-w-0">
        <div className="cc-truncate text-[10px] uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          {PROFILE.sub}
        </div>
        <div className="cc-truncate text-sm font-medium">{PROFILE.org}</div>
      </div>
    </div>
  )
}

function Section({
  label,
  summary,
  items,
  route,
  onNavigate,
  collapsedByDefault = false,
}: {
  label: string
  summary: string
  items: NavItem[]
  route: RouteId | null
  onNavigate: (id: RouteId) => void
  collapsedByDefault?: boolean
}) {
  // If every item in the section was filtered out by role gating, hide
  // the section header too — empty groups look like a load failure.
  const containsActiveRoute = items.some((item) => item.id === route)
  const [open, setOpen] = useState(!collapsedByDefault)
  const renderedOpen = open || containsActiveRoute
  if (items.length === 0) return null
  return (
    <section aria-label={label} className="px-2">
      <details
        aria-label={label}
        open={renderedOpen}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary
          aria-label={`${renderedOpen ? 'Hide' : 'Show'} ${label} navigation`}
          className="flex cursor-pointer list-none items-center justify-between px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: 'var(--cc-ink-3)' }}
          title={summary}
        >
          <span>{label}</span>
          <svg
            aria-hidden="true"
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            style={{ transform: renderedOpen ? 'rotate(180deg)' : undefined }}
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </summary>
        <div className="flex flex-col gap-0.5">
          {items.map((item) => (
            <NavRow
              key={item.id}
              item={item}
              active={route === item.id}
              onClick={() => onNavigate(item.id)}
            />
          ))}
        </div>
      </details>
    </section>
  )
}

export function Sidebar({ route, onNavigate, roles }: SidebarProps) {
  // Filter each section's items by the current identity's roles. The
  // PaywallScreen Forbidden banner remains the defense-in-depth for any
  // user who reaches the URL directly. See UX-1 (S26 gauntletgate).
  const filteredSections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => isItemVisible(item, roles)),
  }))
  return (
    <aside
      aria-label="Primary navigation"
      className="flex flex-col"
      style={{
        background: 'var(--cc-surface)',
        borderRight: '1px solid var(--cc-line)',
        gridRow: '2',
        gridColumn: '1',
      }}
    >
      <div className="p-3">
        <ProfileCard />
      </div>
      <nav className="flex-1 overflow-y-auto pb-3">
        {filteredSections.map((section) => (
          <Section
            key={section.label}
            label={section.label}
            summary={section.summary}
            items={section.items}
            collapsedByDefault={section.collapsedByDefault}
            route={route}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
      <div
        className="grid gap-2 px-4 py-3 text-[10px]"
        style={{ borderTop: '1px solid var(--cc-line)', color: 'var(--cc-ink-3)' }}
      >
        <a
          href="https://github.com/scottconverse/civiccast-native/issues/new?template=bug-report.yml&title=%5Bbeta%5D%20"
          target="_blank"
          rel="noreferrer"
          className="text-xs font-semibold underline underline-offset-2"
          style={{ color: 'var(--cc-brand)' }}
        >
          Report a beta issue
        </a>
        <span>Do not include passwords, recovery codes, staff tokens, or private meeting material.</span>
        <span className="cc-mono">Operator-first beta</span>
      </div>
    </aside>
  )
}

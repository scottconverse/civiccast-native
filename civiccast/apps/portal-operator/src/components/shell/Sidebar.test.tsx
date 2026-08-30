import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { Sidebar, type RoleName } from './Sidebar'

function renderSidebar(roles?: RoleName[], route: Parameters<typeof Sidebar>[0]['route'] = 'live') {
  return render(
    <MemoryRouter>
      <Sidebar route={route} onNavigate={vi.fn()} roles={roles} />
    </MemoryRouter>,
  )
}

describe('Sidebar role and complexity controls', () => {
  it('shows meeting operators only destinations their screen-level roles can read', () => {
    const { getByRole, queryByRole } = renderSidebar(['meeting_operator'])

    for (const label of ['AI Models', 'Remote Contribution', 'Recording', 'Agendas', 'Emergency Alerts']) {
      expect(getByRole('button', { name: label })).toBeTruthy()
    }
    for (const label of [
      'Control Room Setup',
      'Custom Fields',
      'Paywall',
      'CG Designer',
      'Auto-schedule',
      'Reports',
      'EPG Export',
      'Underwriting',
      'App Admin',
    ]) {
      expect(queryByRole('button', { name: label })).toBeNull()
    }
  })

  it.each([
    {
      role: 'setup_admin' as const,
      shown: ['Control Room Setup', 'AI Models', 'Custom Fields', 'Paywall', 'EPG Export', 'App Admin'],
      hidden: ['Agendas', 'Reports'],
    },
    {
      role: 'publish_operator' as const,
      shown: ['CG Designer', 'Auto-schedule', 'EPG Export', 'Underwriting', 'App Admin'],
      hidden: ['Control Room Setup', 'AI Models', 'Paywall', 'Recording', 'Agendas', 'Reports'],
    },
    {
      role: 'support_admin' as const,
      shown: ['Remote Contribution', 'CG Designer', 'Auto-schedule', 'Recording', 'Reports', 'Underwriting'],
      hidden: ['Control Room Setup', 'AI Models', 'Custom Fields', 'Paywall', 'Agendas', 'EPG Export', 'App Admin'],
    },
    {
      role: 'records_clerk' as const,
      shown: ['Agendas'],
      hidden: ['Control Room Setup', 'AI Models', 'Paywall', 'Remote Contribution', 'Recording', 'Reports', 'EPG Export', 'App Admin'],
    },
  ])('matches proven screen-level read gates for $role', ({ role, shown, hidden }) => {
    const { getByRole, queryByRole } = renderSidebar([role])

    for (const label of shown) expect(getByRole('button', { name: label })).toBeTruthy()
    for (const label of hidden) expect(queryByRole('button', { name: label })).toBeNull()
  })

  it('fails closed for role-gated destinations until identity roles load', () => {
    const { queryByRole } = renderSidebar()

    for (const label of ['Paywall', 'Recording', 'Agendas', 'Reports', 'EPG Export', 'App Admin']) {
      expect(queryByRole('button', { name: label })).toBeNull()
    }
  })

  it('collapses advanced groups unless the active route is inside them', () => {
    const inactive = renderSidebar(['setup_admin'], 'live')
    expect(inactive.getByRole('group', { name: 'Setup' }).hasAttribute('open')).toBe(false)
    expect(inactive.getByRole('group', { name: 'System Health' }).hasAttribute('open')).toBe(false)
    expect(inactive.getByRole('group', { name: 'Run Meeting' }).hasAttribute('open')).toBe(true)
    inactive.unmount()

    const active = renderSidebar(['setup_admin'], 'setup')
    expect(active.getByRole('group', { name: 'Setup' }).hasAttribute('open')).toBe(true)
  })

  it('exposes semantic named sections and lets operators expand advanced groups', () => {
    const { getByLabelText, getByRole } = renderSidebar(['setup_admin'], 'live')
    const setupRegion = getByRole('region', { name: 'Setup' })
    const setupGroup = getByRole('group', { name: 'Setup' })

    expect(setupRegion.contains(setupGroup)).toBe(true)
    fireEvent.click(getByLabelText('Show Setup navigation'))
    expect(setupGroup.hasAttribute('open')).toBe(true)
  })
})

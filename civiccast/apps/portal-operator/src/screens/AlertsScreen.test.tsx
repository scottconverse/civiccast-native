import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { AlertChannel, AlertChannelInput, AlertEvent, AlertRule, StaffIdentityResponse } from '../types/api.generated'
import { AlertEventRow, ChannelCard, ChannelForm, RuleRow } from './AlertsScreen'
import { formatCondition, severityTone } from './alerts-format'

// vitest config has no global afterEach, so testing-library's auto-cleanup
// never registers — unmount each render so body-scoped queries don't see
// elements left behind by the previous test.
afterEach(cleanup)
beforeEach(() => vi.clearAllMocks())

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  acknowledgeAlertEvent: vi.fn(),
  createAlertChannel: vi.fn(),
  deleteAlertChannel: vi.fn(),
  getStaffIdentity: vi.fn(),
  listAlertChannels: vi.fn(),
  listAlertEvents: vi.fn(),
  listAlertRules: vi.fn(),
  updateAlertChannel: vi.fn(),
  updateAlertRule: vi.fn(),
}))

import {
  getStaffIdentity,
  listAlertChannels,
  listAlertEvents,
  listAlertRules,
  updateAlertRule,
} from '../api/client'
import { AlertsScreen } from './AlertsScreen'

const baseEvent: AlertEvent = {
  event_id: 'evt-1',
  rule_id: 'default:off-air',
  condition: 'off-air',
  severity: 'critical',
  state: 'firing',
  resource_ref: 'public',
  summary: 'The public channel is off air.',
  source_section: 'S8',
  first_observed_at: '2026-06-15T12:00:00Z',
  last_observed_at: '2026-06-15T12:05:00Z',
  occurrence_count: 3,
}

describe('formatCondition', () => {
  it('maps machine condition codes to plain English', () => {
    expect(formatCondition('off-air')).toBe('Channel off air')
    expect(formatCondition('schema-drift')).toBe('Data format out of date')
    // Not "...failed": the backend's self-test summary deliberately avoids
    // that word on a fresh station where readiness/backup legitimately
    // aren't finished yet (civiccast/alerting/self_test.py's F-RC3-5). The
    // condition title must not contradict that softer wording.
    expect(formatCondition('self-test-fail')).toBe('Automatic self-check did not pass')
  })

  it('falls back to a humanized form for an unknown code', () => {
    expect(formatCondition('some-new-condition')).toBe('some new condition')
  })
})

describe('severityTone', () => {
  it('maps severities to tones', () => {
    expect(severityTone('critical')).toBe('err')
    expect(severityTone('warning')).toBe('warn')
    expect(severityTone('info')).toBe('info')
  })
})

describe('AlertEventRow', () => {
  it('shows plain-English condition, summary, and a repeat count', () => {
    const { container } = render(<AlertEventRow event={baseEvent} />)
    expect(container.textContent).toContain('Channel off air')
    expect(container.textContent).toContain('The public channel is off air.')
    expect(container.textContent).toContain('seen 3×')
  })

  it('calls onAck when the acknowledge button is clicked', () => {
    const onAck = vi.fn()
    const { getByText } = render(<AlertEventRow event={baseEvent} onAck={onAck} />)
    fireEvent.click(getByText('Acknowledge'))
    expect(onAck).toHaveBeenCalledWith('evt-1')
  })

  it('hides the acknowledge button once acknowledged', () => {
    const { container, queryByText } = render(
      <AlertEventRow
        event={{ ...baseEvent, acknowledged_at: '2026-06-15T12:10:00Z', acknowledged_by: 'Dana' }}
        onAck={vi.fn()}
      />,
    )
    expect(queryByText('Acknowledge')).toBeNull()
    expect(container.textContent).toContain('Acknowledged by Dana')
  })

  it('shows the alert state through the shared vocabulary, not the raw enum', () => {
    // The sibling ChannelCard pill (line 589) already translates its status
    // through stateLabel; this row's own state pill did not, one row away.
    const { getByText, queryByText } = render(<AlertEventRow event={{ ...baseEvent, state: 'firing' }} />)
    expect(getByText('Firing')).toBeTruthy()
    expect(queryByText('firing')).toBeNull()
  })

  it('shows "Resolved", not the raw enum, once an alert clears', () => {
    const { getByText, queryByText } = render(
      <AlertEventRow event={{ ...baseEvent, state: 'resolved', resolved_at: '2026-06-15T12:30:00Z' }} />,
    )
    expect(getByText('Resolved')).toBeTruthy()
    expect(queryByText('resolved')).toBeNull()
  })
})


const EMPTY_INITIAL: AlertChannelInput = {
  kind: 'email', label: '', enabled: true, target_redacted: '',
  credential_handle: null, quiet_hours_start_utc: null, quiet_hours_end_utc: null, secret: null,
}

describe('ChannelForm', () => {
  it('disables submit until both name and destination are set', () => {
    const { getByText, getByPlaceholderText } = render(
      <ChannelForm initial={EMPTY_INITIAL} submitting={false} submitLabel="Create destination" onSubmit={vi.fn()} />,
    )
    const submit = getByText('Create destination') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.change(getByPlaceholderText('Example: Station manager email'), { target: { value: 'Ops' } })
    fireEvent.change(getByPlaceholderText(/ops@city.gov/), { target: { value: 'ops@city.gov' } })
    expect(submit.disabled).toBe(false)
  })

  it('keeps submit disabled while quiet hours are not HH:MM', () => {
    const { getByText, getByPlaceholderText } = render(
      <ChannelForm initial={EMPTY_INITIAL} submitting={false} submitLabel="Create destination" onSubmit={vi.fn()} />,
    )
    fireEvent.change(getByPlaceholderText('Example: Station manager email'), { target: { value: 'Ops' } })
    fireEvent.change(getByPlaceholderText(/ops@city.gov/), { target: { value: 'ops@city.gov' } })
    const submit = getByText('Create destination') as HTMLButtonElement
    fireEvent.change(getByPlaceholderText('22:00'), { target: { value: '10pm' } })
    expect(submit.disabled).toBe(true)
    fireEvent.change(getByPlaceholderText('22:00'), { target: { value: '22:00' } })
    expect(submit.disabled).toBe(false)
  })

  it('builds a payload with a write-only secret (value input is a password field)', () => {
    const onSubmit = vi.fn()
    const { getByText, getByPlaceholderText } = render(
      <ChannelForm initial={EMPTY_INITIAL} submitting={false} submitLabel="Create destination" onSubmit={onSubmit} />,
    )
    fireEvent.change(getByPlaceholderText('Example: Station manager email'), { target: { value: 'Pager' } })
    fireEvent.change(getByPlaceholderText(/ops@city.gov/), { target: { value: 'https://hooks/x' } })
    fireEvent.click(getByText('Add secret field'))
    fireEvent.change(getByPlaceholderText('key (e.g. smtp_password)'), { target: { value: 'smtp_password' } })
    const valueInput = getByPlaceholderText('value') as HTMLInputElement
    expect(valueInput.type).toBe('password')  // never plain-text
    fireEvent.change(valueInput, { target: { value: 'pw' } })
    fireEvent.click(getByText('Create destination'))
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit.mock.calls[0][0].secret).toEqual({ smtp_password: 'pw' })
  })

  it('shows a "secret is stored" indicator when editing a channel that has one', () => {
    const { container } = render(
      <ChannelForm
        initial={{ ...EMPTY_INITIAL, label: 'x', target_redacted: 'y', credential_handle: 'ch-1' }}
        submitting={false}
        submitLabel="Save changes"
        onSubmit={vi.fn()}
      />,
    )
    expect(container.textContent).toContain('A connection secret is already stored')
  })
})

const baseChannel: AlertChannel = {
  channel_id: 'ch-1', kind: 'email', label: 'Ops email', enabled: true,
  target_redacted: 'ops@city.gov', credential_handle: 'ch-1', created_at: '2026-06-15T12:00:00Z',
}

describe('ChannelCard delete confirm', () => {
  it('requires two clicks to delete (a misclick must not remove a destination)', () => {
    const onDelete = vi.fn()
    const { getByText } = render(
      <ChannelCard channel={baseChannel} onUpdate={vi.fn()} onDelete={onDelete} updating={false} deleting={false} />,
    )
    fireEvent.click(getByText('Delete'))
    expect(onDelete).not.toHaveBeenCalled()  // first click only arms
    fireEvent.click(getByText('Confirm delete?'))
    expect(onDelete).toHaveBeenCalledWith('ch-1')
  })
})

describe('ChannelCard last-delivery-status pill', () => {
  it('shows the shared vocabulary phrase for an undeliverable channel, not the raw enum', () => {
    // baseChannel never sets last_delivery_status, so this render path
    // (AlertsScreen.tsx:589) had no coverage at all before this test.
    const { getByText, queryByText } = render(
      <ChannelCard
        channel={{ ...baseChannel, last_delivery_status: 'dead_letter' }}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        updating={false}
        deleting={false}
      />,
    )
    expect(getByText('Undeliverable')).toBeTruthy()
    expect(queryByText('dead_letter')).toBeNull()
  })
})

const baseRule: AlertRule = {
  rule_id: 'default:off-air', condition: 'off-air', enabled: true, severity: 'critical',
  channel_ids: [], re_alert_after_seconds: 900, updated_at: '2026-06-15T12:00:00Z', updated_by: 'system',
}

describe('RuleRow', () => {
  it('disables Save when re-alert minutes is not a number', () => {
    const { getByText, getByDisplayValue } = render(
      <RuleRow rule={baseRule} onSave={vi.fn()} saving={false} />,
    )
    fireEvent.change(getByDisplayValue('15'), { target: { value: 'soon' } })
    expect((getByText('Save') as HTMLButtonElement).disabled).toBe(true)
  })
})

function alertIdentity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op-1', operator_display_name: 'Dana', roles }
}

function renderAlertsScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AlertsScreen />
    </QueryClientProvider>,
  )
}

describe('AlertsScreen destination assignment', () => {
  it('saves selected destinations with existing and stale ids preserved, then refetches the rule', async () => {
    const original = { ...baseRule, channel_ids: ['ch-1', 'ch-deleted'] }
    let saved = original
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['setup_admin']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    vi.mocked(listAlertRules).mockImplementation(async () => [saved])
    vi.mocked(listAlertChannels).mockResolvedValue([
      baseChannel,
      { ...baseChannel, channel_id: 'ch-2', label: 'Duty phone', kind: 'sms' },
    ])
    vi.mocked(updateAlertRule).mockImplementation(async (_ruleId, payload) => {
      saved = {
        ...saved,
        enabled: payload.enabled ?? saved.enabled,
        severity: payload.severity ?? saved.severity,
        re_alert_after_seconds: payload.re_alert_after_seconds ?? saved.re_alert_after_seconds,
        notify_on_resolve: payload.notify_on_resolve ?? saved.notify_on_resolve,
        channel_ids: payload.channel_ids ?? saved.channel_ids,
        updated_at: '2026-06-15T12:01:00Z',
      }
      return saved
    })

    const { findByLabelText, findByRole, findByText } = renderAlertsScreen()
    const stale = await findByLabelText('Unavailable destination ch-deleted') as HTMLInputElement
    expect(stale.checked).toBe(true)
    expect(await findByLabelText('Ops email') as HTMLInputElement).toHaveProperty('checked', true)
    fireEvent.click(await findByLabelText('Duty phone'))
    fireEvent.click(await findByRole('button', { name: 'Save' }))

    await waitFor(() => expect(updateAlertRule).toHaveBeenCalledWith(baseRule.rule_id, {
      enabled: true,
      severity: 'critical',
      re_alert_after_seconds: 900,
      notify_on_resolve: false,
      channel_ids: ['ch-1', 'ch-deleted', 'ch-2'],
    }))
    await waitFor(() => expect(listAlertRules).toHaveBeenCalledTimes(2))
    expect(await findByText('Unavailable destination ch-deleted')).toBeTruthy()
    expect((await findByLabelText('Duty phone') as HTMLInputElement).checked).toBe(true)
  })

  it('omits channel_ids when saving an unrelated rule setting', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['setup_admin']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    vi.mocked(listAlertRules).mockResolvedValue([{ ...baseRule, channel_ids: ['ch-1'] }])
    vi.mocked(listAlertChannels).mockResolvedValue([baseChannel])
    vi.mocked(updateAlertRule).mockResolvedValue(baseRule)

    const { findByLabelText, findByRole } = renderAlertsScreen()
    fireEvent.change(await findByLabelText('Severity'), { target: { value: 'warning' } })
    fireEvent.click(await findByRole('button', { name: 'Save' }))

    await waitFor(() => expect(updateAlertRule).toHaveBeenCalledWith(baseRule.rule_id, {
      enabled: true,
      severity: 'warning',
      re_alert_after_seconds: 900,
      notify_on_resolve: false,
    }))
  })

  it('shows configured rules read-only to support admins and explains setup-admin write access', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['support_admin']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    vi.mocked(listAlertRules).mockResolvedValue([baseRule])
    vi.mocked(listAlertChannels).mockResolvedValue([baseChannel])

    const { findByText, queryByRole } = renderAlertsScreen()
    expect(await findByText('Channel off air')).toBeTruthy()
    expect(await findByText(/changing alert rules requires the setup admin role/)).toBeTruthy()
    expect(queryByRole('button', { name: 'Save' })).toBeNull()
    expect(queryByRole('button', { name: 'Add destination' })).toBeNull()
  })

  it('states when there are no configured rules or destinations', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['setup_admin']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    vi.mocked(listAlertRules).mockResolvedValue([])
    vi.mocked(listAlertChannels).mockResolvedValue([])
    const { findByText } = renderAlertsScreen()
    expect(await findByText(/No alert rules are configured/)).toBeTruthy()
    expect(await findByText(/No alert destinations yet/)).toBeTruthy()
  })

  it('shows access-checking and access-error states without querying admin routes', async () => {
    let rejectIdentity!: (error: Error) => void
    vi.mocked(getStaffIdentity).mockImplementation(() => new Promise((_resolve, reject) => {
      rejectIdentity = reject
    }))
    const { getByText, findAllByText } = renderAlertsScreen()
    expect(getByText(/Checking your access to alert rules/)).toBeTruthy()
    rejectIdentity(new Error('session expired'))
    expect((await findAllByText(/Your access could not be checked/)).length).toBe(2)
    expect(listAlertRules).not.toHaveBeenCalled()
    expect(listAlertChannels).not.toHaveBeenCalled()
  })

  it('keeps rule editing routes closed to roles that cannot read alerts', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['meeting_operator']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    const { findAllByText } = renderAlertsScreen()
    expect((await findAllByText(/Viewing alert rules requires the setup admin or support admin role/)).length).toBe(1)
    expect((await findAllByText(/Viewing alert destinations requires the setup admin or support admin role/)).length).toBe(1)
    expect(listAlertRules).not.toHaveBeenCalled()
    expect(listAlertChannels).not.toHaveBeenCalled()
  })

  it('shows assigned ids when destinations fail to load and preserves them on other saves', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(alertIdentity(['setup_admin']))
    vi.mocked(listAlertEvents).mockResolvedValue([])
    vi.mocked(listAlertRules).mockResolvedValue([{ ...baseRule, channel_ids: ['ch-still-assigned'] }])
    vi.mocked(listAlertChannels).mockRejectedValue(new Error('destination query failed'))
    vi.mocked(updateAlertRule).mockResolvedValue(baseRule)

    const { findAllByText, findByLabelText, findByRole, findByText } = renderAlertsScreen()
    expect((await findAllByText(/destination query failed/)).length).toBeGreaterThan(0)
    expect(await findByText(/Current destination ids: ch-still-assigned/)).toBeTruthy()
    fireEvent.change(await findByLabelText('Severity'), { target: { value: 'warning' } })
    fireEvent.click(await findByRole('button', { name: 'Save' }))

    await waitFor(() => expect(updateAlertRule).toHaveBeenCalledWith(baseRule.rule_id, {
      enabled: true,
      severity: 'warning',
      re_alert_after_seconds: 900,
      notify_on_resolve: false,
    }))
  })
})

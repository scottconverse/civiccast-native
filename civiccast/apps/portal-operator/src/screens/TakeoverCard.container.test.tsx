import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  getTakeoverState: vi.fn(),
  listTakeoverAudit: vi.fn(),
  beginTakeover: vi.fn(),
  handbackTakeover: vi.fn(),
}))

import type { ManualRouteState, TakeoverSession } from '../types/api.generated'
import { beginTakeover, getTakeoverState, listTakeoverAudit } from '../api/client'
import { TakeoverCard } from './TakeoverCard'

afterEach(cleanup)

const SESSION: TakeoverSession = {
  session_id: 'takeover-1',
  channel_id: 'public',
  source_ref: 'public:local',
  source_label: 'Live: Council chamber',
  operator_id: 'dana',
  operator_name: 'Dana',
  took_over_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  source_plan_json: '{}',
}

function idle(canTakeover = true): ManualRouteState {
  return { channel_id: 'public', active_session: null, can_takeover: canTakeover, can_return: false }
}
function live(): ManualRouteState {
  return { channel_id: 'public', active_session: SESSION, can_takeover: false, can_return: true }
}

function renderCard(props: { canManage: boolean; canViewAudit: boolean }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TakeoverCard channelId="public" canManage={props.canManage} canViewAudit={props.canViewAudit} />
    </QueryClientProvider>,
  )
}

describe('TakeoverCard', () => {
  it('offers Take live to a manager on an idle channel', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(idle())
    vi.mocked(listTakeoverAudit).mockResolvedValue([])
    const { findByText } = renderCard({ canManage: true, canViewAudit: false })
    expect((await findByText('Take live')) as HTMLButtonElement).toBeTruthy()
  })

  it('hides Take live from a non-manager and explains the role', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(idle())
    const { findByText, queryByText } = renderCard({ canManage: false, canViewAudit: false })
    expect(await findByText(/requires the meeting operator or setup admin role/)).toBeTruthy()
    expect(queryByText('Take live')).toBeNull()
  })

  it('disables Take live when no live source is ready', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(idle(false))
    const { findByText } = renderCard({ canManage: true, canViewAudit: false })
    const btn = (await findByText('Take live')) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(await findByText(/No live source is ready yet/)).toBeTruthy()
  })

  it('take live is a two-step confirm that calls the API', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(idle())
    vi.mocked(beginTakeover).mockResolvedValue(SESSION)
    const { findByText, getByPlaceholderText } = renderCard({ canManage: true, canViewAudit: false })
    fireEvent.click(await findByText('Take live'))
    expect(beginTakeover).not.toHaveBeenCalled() // first click only arms
    fireEvent.change(getByPlaceholderText(/emergency council session/), {
      target: { value: 'emergency session' },
    })
    fireEvent.click(await findByText('Confirm take live'))
    await waitFor(() =>
      expect(beginTakeover).toHaveBeenCalledWith('public', { reason: 'emergency session' }),
    )
  })

  it('shows the live badge and a Return control when live', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(live())
    const { findByText } = renderCard({ canManage: true, canViewAudit: false })
    expect(await findByText(/Live takeover — Dana/)).toBeTruthy()
    expect(await findByText('Return to schedule')).toBeTruthy()
  })

  it('shows the audit history only to admins', async () => {
    vi.mocked(getTakeoverState).mockResolvedValue(idle())
    vi.mocked(listTakeoverAudit).mockResolvedValue([{ ...SESSION, returned_at: new Date().toISOString() }])
    const admin = renderCard({ canManage: true, canViewAudit: true })
    expect(await admin.findByText('Takeover history')).toBeTruthy()
    cleanup()

    vi.mocked(getTakeoverState).mockResolvedValue(idle())
    const nonAdmin = renderCard({ canManage: true, canViewAudit: false })
    await nonAdmin.findByText('Take live')
    expect(nonAdmin.queryByText('Takeover history')).toBeNull()
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'

afterEach(cleanup)

import type { CgFeedItem } from '../types/api.generated'
import { FeedApprovalList } from './FeedApprovalQueue'

function item(overrides: Partial<CgFeedItem> = {}): CgFeedItem {
  return {
    item_id: 'i1', title: 'Story A', summary: 'a summary', starts_at: null,
    url: null, approved: false, tags: [], ...overrides,
  }
}

describe('FeedApprovalList', () => {
  it('offers Approve on a pending item and fires the callback', () => {
    const onApprove = vi.fn()
    const { getByText } = render(
      <FeedApprovalList items={[item()]} canApprove busyItemId={null} onApprove={onApprove} />,
    )
    expect(getByText('1 pending · 0 approved')).toBeTruthy()
    fireEvent.click(getByText('Approve'))
    expect(onApprove).toHaveBeenCalledWith('i1')
  })

  it('shows an Approved badge (no button) for an approved item', () => {
    const { getByText, queryByText } = render(
      <FeedApprovalList items={[item({ approved: true })]} canApprove busyItemId={null} onApprove={vi.fn()} />,
    )
    expect(getByText('Approved')).toBeTruthy()
    expect(queryByText('Approve')).toBeNull()
    expect(getByText('0 pending · 1 approved')).toBeTruthy()
  })

  it('shows a read-only Pending badge when the operator cannot approve', () => {
    const { getByText, queryByText } = render(
      <FeedApprovalList items={[item()]} canApprove={false} busyItemId={null} onApprove={vi.fn()} />,
    )
    expect(getByText('Pending')).toBeTruthy()
    expect(queryByText('Approve')).toBeNull()
  })

  it('disables the Approve button for the item currently being approved', () => {
    const { getByText } = render(
      <FeedApprovalList items={[item()]} canApprove busyItemId="i1" onApprove={vi.fn()} />,
    )
    expect((getByText('Approve') as HTMLButtonElement).disabled).toBe(true)
  })

  it('renders an empty state', () => {
    const { getByText } = render(
      <FeedApprovalList items={[]} canApprove busyItemId={null} onApprove={vi.fn()} />,
    )
    expect(getByText(/No items in this feed/)).toBeTruthy()
  })
})

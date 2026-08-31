// Confirmation copy for the outgoing-feed commands, shared by the Channels
// screen and the System Health ("Safe to broadcast") readiness panel so both
// surfaces ask the same question in the same voice before touching a live
// feed. The copy names the concrete resident-facing consequence.

import type { EgressCommandAction } from '../api/client'

export interface FeedCommandConfirmCopy {
  title: string
  body: string
  confirmLabel: string
  tone: 'danger' | 'brand'
}

export function feedCommandConfirmCopy(
  action: EgressCommandAction,
  channelName: string,
): FeedCommandConfirmCopy {
  switch (action) {
    case 'start':
      return {
        title: `Start the outgoing feed for ${channelName}?`,
        body: `${channelName} goes live to its configured outputs and becomes visible to residents.`,
        confirmLabel: 'Start feed',
        tone: 'brand',
      }
    case 'stop':
      return {
        title: `Stop the outgoing feed for ${channelName}?`,
        body: `This takes ${channelName} off the air. Residents watching lose the stream until the feed is started again.`,
        confirmLabel: 'Stop feed',
        tone: 'danger',
      }
    case 'reload':
      return {
        title: `Restart the outgoing feed for ${channelName}?`,
        body: `The stream drops briefly for residents while ${channelName} restarts.`,
        confirmLabel: 'Restart feed',
        tone: 'danger',
      }
    case 'drain':
      return {
        title: `Finish the current item, then stop ${channelName}?`,
        body: `${channelName} plays out its current item and then goes off the air until the feed is started again.`,
        confirmLabel: 'Finish, then stop',
        tone: 'danger',
      }
  }
}

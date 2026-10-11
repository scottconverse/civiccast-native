// Copyright (c) The CivicCast Authors

import type { ContributionMediaControlAction } from '../api/client'

export function sendVdoDirectorControl(
  director: Pick<Window, 'postMessage'>,
  targetOrigin: string,
  streamId: string,
  action: ContributionMediaControlAction,
): void {
  const targetGuest: Record<string, unknown> = {
    function: 'targetGuest',
    target: streamId,
  }
  if (action === 'disconnect') {
    targetGuest.action = 'hangup'
  } else {
    targetGuest.action = action.startsWith('audio_') ? 'audio' : 'video'
    // v30.2 targetGuest treats false as mute and true as unmute.
    targetGuest.value = action.endsWith('_unmute')
  }
  director.postMessage(targetGuest, targetOrigin)
}

// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// The pre-action confirmation for "Apply a headend preset" on the Channels
// screen. Kept in a non-component module so it can be tested word for word:
// the copy is the consent the operator gives, and it must describe what the
// backend actually does (review round 3 delta, MAJOR 1 -- it used to promise
// "the channel's cable and other outputs keep running unchanged" while the
// apply route restarts a channel standing by on its slate, which terminates
// the one worker producing EVERY output, cable headend feed included).
//
// What POST .../config/headend-profile does, by channel state (see
// `HeadendProfileApplyResponse` in civiccast/egress/router.py):
// - standing by on its slate -> restarted now; every output drops for a few
//   seconds while the pipeline rebuilds (`restart_queued`);
// - a program on air -> nothing interrupted; lands at the next Stop/Start
//   (`restart_required`);
// - not running -> lands at the next start (`next_start`).

import type { PendingConfirm } from '../components/ConfirmDialog'

export const LOCAL_HLS_PROFILE_ID = 'local-rehearsal-hls'

export interface HeadendApplyPayload {
  profile_id: string
  destination_uri: string
  muxrate_kbps: number | null
  keep_existing_sinks: boolean
}

// One sentence, shared by every variant, that states the interruption before
// the click. The words "including the cable feed" are load-bearing: a PEG
// channel's slate is exactly what cable subscribers see between meetings.
export const HEADEND_RESTART_CONSEQUENCE =
  'If the channel is standing by on its slate, it is restarted right away to put the change on air: every output, including the cable feed, drops for a few seconds while the pipeline rebuilds. If a program is on air, nothing is interrupted and the change takes effect when you next Stop and Start the channel.'

export function headendApplyConfirm(
  payload: HeadendApplyPayload,
  channelName: string,
): Omit<PendingConfirm, 'run'> {
  const isLocalHls = payload.profile_id === LOCAL_HLS_PROFILE_ID
  if (isLocalHls) {
    return {
      title: 'Enable web preview for this channel?',
      body: payload.keep_existing_sinks
        ? `Adds an HLS web output so residents can watch ${channelName} in the portal; the channel's cable and other outputs stay configured. ${HEADEND_RESTART_CONSEQUENCE}`
        : `Adds an HLS web output so residents can watch ${channelName} in the portal, and removes the channel's other outputs — only the web preview is configured afterwards. ${HEADEND_RESTART_CONSEQUENCE}`,
      confirmLabel: 'Enable web preview',
      tone: 'brand',
    }
  }
  return {
    title: 'Apply this headend preset?',
    body: payload.keep_existing_sinks
      ? `Sends ${channelName}'s outgoing feed to the selected headend profile; the channel's other outputs stay configured alongside it. ${HEADEND_RESTART_CONSEQUENCE}`
      : `Sends ${channelName}'s outgoing feed to the selected headend profile and removes the channel's other outputs — only the headend feed is configured afterwards. ${HEADEND_RESTART_CONSEQUENCE}`,
    confirmLabel: 'Apply preset',
    tone: 'brand',
  }
}

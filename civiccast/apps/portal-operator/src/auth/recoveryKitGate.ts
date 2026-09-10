// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
/**
 * The one-time first-setup recovery kit, held until the operator confirms it.
 *
 * beta.5 clean-machine walkthrough (2026-09-09): the kit vanished within
 * seconds of appearing, before Save/Print, and the next paint said
 * "Recovery kit never confirmed". The kit only ever lived in SetupScreen's
 * React state, the server never re-serves the codes, and ANY unmount of the
 * screen -- a Sidebar click, App.tsx's missing-session bounce back to
 * /setup, a reload -- threw it away for good. The `beforeunload` guard only
 * covered reload/close.
 *
 * This module is the fix's single source of truth: the setup response
 * (codes included) plus the admin password the kit prints are written to
 * sessionStorage the moment first-admin setup succeeds and removed only
 * when the acknowledge call succeeds (or the station reports the kit is
 * already confirmed). sessionStorage is tab-scoped and dies with the tab --
 * the same lifetime as the on-screen kit it protects. While a pending kit
 * exists the shell locks navigation and bounces every other route back to
 * /setup, so the operator cannot leave the kit without confirming it.
 */
import { useSyncExternalStore } from 'react'

import type { FirstAdminSetupResponse } from '../types/api.generated'

export const PENDING_RECOVERY_KIT_KEY = 'civiccast.pendingRecoveryKit'

const CHANGE_EVENT = 'civiccast:pending-recovery-kit-change'

export interface PendingRecoveryKit {
  setup: FirstAdminSetupResponse
  /** The routine password the kit prints; never stored server-side in readable form. */
  admin_password: string
  /** Epoch ms when the kit was stored; lets the setup screen discard a kit
   *  left over from a station that has since been reset. */
  stored_at: number
}

function rawSnapshot(): string | null {
  try {
    return window.sessionStorage.getItem(PENDING_RECOVERY_KIT_KEY)
  } catch {
    return null
  }
}

function parse(raw: string | null): PendingRecoveryKit | null {
  if (raw == null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PendingRecoveryKit>
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      !parsed.setup ||
      typeof parsed.setup !== 'object' ||
      !Array.isArray(parsed.setup.recovery_kit?.recovery_codes) ||
      typeof parsed.admin_password !== 'string'
    ) {
      return null
    }
    return {
      setup: parsed.setup,
      admin_password: parsed.admin_password,
      stored_at: typeof parsed.stored_at === 'number' ? parsed.stored_at : 0,
    }
  } catch {
    return null
  }
}

function notify() {
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function readPendingRecoveryKit(): PendingRecoveryKit | null {
  if (typeof window === 'undefined') return null
  return parse(rawSnapshot())
}

export function storePendingRecoveryKit(
  kit: Omit<PendingRecoveryKit, 'stored_at'>,
): PendingRecoveryKit {
  const record: PendingRecoveryKit = { ...kit, stored_at: Date.now() }
  try {
    window.sessionStorage.setItem(PENDING_RECOVERY_KIT_KEY, JSON.stringify(record))
  } catch {
    // Storage unavailable -- the kit still renders from React state for this mount.
  }
  notify()
  return record
}

export function clearPendingRecoveryKit(): void {
  try {
    window.sessionStorage.removeItem(PENDING_RECOVERY_KIT_KEY)
  } catch {
    // Nothing persisted to clear.
  }
  notify()
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

function serverSnapshot(): string | null {
  return null
}

/**
 * True while a first-setup recovery kit is waiting to be confirmed in this
 * tab. Re-renders subscribers when the kit is stored or cleared.
 */
export function useRecoveryKitGateActive(): boolean {
  const raw = useSyncExternalStore(subscribe, rawSnapshot, serverSnapshot)
  return parse(raw) != null
}

/** Plain-language reason shown on every navigation control the gate disables. */
export const RECOVERY_KIT_GATE_REASON =
  'Save or print your recovery kit and confirm it on First Setup before leaving that screen.'

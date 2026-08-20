// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Toast context + hook. Split out from Toast.tsx so the JSX module
// exports only React components — required for Vite's react-refresh
// fast-refresh purity rule.

import { createContext, useContext } from 'react'

export type ToastTone = 'success' | 'error' | 'info'

export interface ToastInput {
  tone: ToastTone
  message: string
  detail?: string | null
  durationMs?: number
}

export interface ToastContextValue {
  push: (input: ToastInput) => void
}

export const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error('useToast must be used within a <ToastProvider>')
  }
  return ctx
}

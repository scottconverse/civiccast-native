// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Portal-level toast/snackbar.
//
// Closes audit-team v0.3.0 findings UX-001, UX-007, UX-014, UX-005, ENG-007:
// the trim editor and schedule drawer were unmounting silently on save with
// no confirmation surface; UX-014 was the dead "Saved" button label that
// vanished with the unmounting dialog; ENG-007 was the cancel-mutation path
// with no error UI; UX-005 was the trim editor not closing on Escape.
// One queue, one z-layer above modals. Toasts auto-dismiss after their
// duration; the operator can also dismiss explicitly.
//
// The hook + context types live in ./toast-context.ts so this module can
// keep react-refresh fast-refresh purity (component-only exports).

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  ToastContext,
  type ToastInput,
  type ToastTone,
} from './toast-context'

interface Toast {
  id: number
  tone: ToastTone
  message: string
  detail: string | null
  durationMs: number
}

const DEFAULT_DURATION_MS = 4500

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const idRef = useRef(0)

  const dismiss = useCallback((id: number) => {
    setToasts((curr) => curr.filter((t) => t.id !== id))
  }, [])

  const push = useCallback((input: ToastInput) => {
    idRef.current += 1
    const toast: Toast = {
      id: idRef.current,
      tone: input.tone,
      message: input.message,
      detail: input.detail ?? null,
      durationMs: input.durationMs ?? DEFAULT_DURATION_MS,
    }
    setToasts((curr) => [...curr, toast])
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: number) => void
}) {
  if (toasts.length === 0) return null
  return (
    <div
      // z-index sits above the trim editor (z-50) and schedule drawer.
      // aria-live polite so screen readers announce success/error
      // without interrupting the operator's current focus.
      className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <ToastView key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  )
}

function ToastView({
  toast,
  onDismiss,
}: {
  toast: Toast
  onDismiss: (id: number) => void
}) {
  useEffect(() => {
    const handle = window.setTimeout(() => onDismiss(toast.id), toast.durationMs)
    return () => window.clearTimeout(handle)
  }, [toast.id, toast.durationMs, onDismiss])

  const palette = TONE_PALETTE[toast.tone]
  return (
    <div
      role={toast.tone === 'error' ? 'alert' : 'status'}
      aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}
      className="pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-md px-4 py-3 shadow-lg"
      style={{
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.border}`,
      }}
    >
      <span aria-hidden="true" className="mt-0.5 text-base font-bold">
        {palette.glyph}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{toast.message}</div>
        {toast.detail && (
          <div
            className="mt-0.5 text-xs"
            style={{ color: palette.detailFg }}
          >
            {toast.detail}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="shrink-0 rounded px-1 text-base leading-none"
        style={{ color: palette.detailFg }}
      >
        ✕
      </button>
    </div>
  )
}

const TONE_PALETTE: Record<
  ToastTone,
  { bg: string; fg: string; detailFg: string; border: string; glyph: string }
> = {
  success: {
    bg: 'var(--cc-paper)',
    fg: 'var(--cc-ink)',
    detailFg: 'var(--cc-ink-2)',
    border: 'var(--cc-brand)',
    glyph: '✓',
  },
  error: {
    bg: 'var(--cc-paper)',
    fg: 'var(--cc-ink)',
    detailFg: 'var(--cc-ink-2)',
    border: 'var(--cc-danger, #b91c1c)',
    glyph: '!',
  },
  info: {
    bg: 'var(--cc-paper)',
    fg: 'var(--cc-ink)',
    detailFg: 'var(--cc-ink-2)',
    border: 'var(--cc-line-strong)',
    glyph: 'i',
  },
}

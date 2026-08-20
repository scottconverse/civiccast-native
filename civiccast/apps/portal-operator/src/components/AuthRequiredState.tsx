export function AuthRequiredState({ error, context = 'staff identity' }: { error: unknown; context?: string }) {
  return (
    <div
      role="alert"
      className="rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-warn)' }}
    >
      Could not verify your {context} ({apiMessage(error, 'request failed')}). Sign in again from
      the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then
      retry once the local API is running.
    </div>
  )
}

function apiMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail
  }
  if (error instanceof Error) return error.message
  return fallback
}

// Small shared display helpers for the operator console.

/** Human-readable duration: "30s" / "45m" / "1h 0m" (operator-friendly,
 * not raw seconds). Used for egress "On air" time on System Health + Channels. */
export function humanizeDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0s'
  const total = Math.floor(seconds)
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

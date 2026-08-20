// Non-component helpers for the live-takeover card (mirrors commit-format.ts)
// so the screen file only exports components and React Fast Refresh stays happy.

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** "live for N min" duration since the takeover started. */
export function elapsedSinceLabel(iso: string, nowMs: number): string {
  const minutes = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 60_000))
  if (minutes < 1) return 'just now'
  if (minutes === 1) return '1 min'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  return rem === 0 ? `${hours} hr` : `${hours} hr ${rem} min`
}

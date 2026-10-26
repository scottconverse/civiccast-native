import { useState } from 'react'

export function EmbedCopyPanel({ kind, identity }: { kind: 'asset' | 'channel'; identity: string }) {
  const [snippet, setSnippet] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function copy() {
    setBusy(true); setMessage(null); setSnippet('')
    try {
      const path = kind === 'channel' ? `/api/public/embed/channel/${encodeURIComponent(identity)}` : `/api/public/embed/${encodeURIComponent(identity)}`
      const response = await fetch(path, { cache: 'no-store' })
      const result = await response.json() as { embed_html?: string; detail?: string }
      if (!response.ok || !result.embed_html) throw new Error(result.detail ?? 'The embed could not be prepared.')
      setSnippet(result.embed_html)
      try { await navigator.clipboard.writeText(result.embed_html); setMessage('Embed copied. Paste it into your website’s HTML embed block.') }
      catch { setMessage('Select and copy the embed below, then paste it into your website’s HTML embed block.') }
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : 'The embed could not be prepared.') }
    finally { setBusy(false) }
  }
  return <section aria-label="Website playback embed" className="grid gap-2 rounded-md border p-3">
    <button type="button" disabled={busy} onClick={() => { void copy() }}>{busy ? 'Preparing embed…' : 'Copy website embed'}</button>
    <p className="m-0 text-xs">Public playback only. Captions remain available in the player. Private or paywalled video cannot be embedded.</p>
    {message && <p role="status">{message}</p>}
    {snippet && <textarea readOnly aria-label="Website embed HTML" value={snippet} onFocus={(event) => event.target.select()} />}
  </section>
}

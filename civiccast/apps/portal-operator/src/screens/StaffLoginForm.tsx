import { useState } from 'react'
import type { FormEvent } from 'react'
import type { StaffLoginResult } from '../api/staffAccounts'

const panelStyle = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }
const fieldStyle = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }

export function StaffLoginForm({
  onLogin,
  onAuthenticated,
}: {
  onLogin: (username: string, password: string) => Promise<StaffLoginResult>
  onAuthenticated: (result: StaffLoginResult) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      onAuthenticated(await onLogin(username.trim(), password))
      setPassword('')
    } catch (reason) {
      const detail = reason && typeof reason === 'object' && 'detail' in reason
        ? (reason as { detail?: unknown }).detail
        : undefined
      setError(typeof detail === 'string' ? detail : reason instanceof Error ? reason.message : 'Could not sign in.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="grid max-w-md gap-3 rounded-lg p-4" style={panelStyle}>
      <div>
        <h2 className="m-0 text-base font-semibold">Staff sign-in</h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Use the username and password provided by your station administrator.
        </p>
      </div>
      <label className="grid gap-1 text-xs">
        <span>Username</span>
        <input
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          className="rounded-md px-2 py-1.5"
          style={fieldStyle}
        />
      </label>
      <label className="grid gap-1 text-xs">
        <span>Password</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="rounded-md px-2 py-1.5"
          style={fieldStyle}
        />
      </label>
      <button
        type="submit"
        disabled={submitting || !username.trim() || !password}
        className="rounded-md px-3 py-2 text-xs font-semibold"
        style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
      >
        {submitting ? 'Signing in…' : 'Sign in'}
      </button>
      {error && <p role="alert" className="m-0 text-xs text-red-700">{error}</p>}
    </form>
  )
}

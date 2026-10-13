import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { STAFF_ROLES } from '../api/staffAccounts'
import type {
  StaffAccount,
  StaffAccountPatch,
  StaffAccountsApi,
  StaffCreatePayload,
  StaffRole,
} from '../api/staffAccounts'

const panelStyle = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }
const insetStyle = { background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }
const fieldStyle = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message
  return fallback
}

function RoleChoices({
  value,
  onChange,
}: {
  value: StaffRole[]
  onChange: (roles: StaffRole[]) => void
}) {
  return (
    <fieldset className="grid gap-1 sm:grid-cols-2" aria-label="Staff roles">
      <legend className="mb-1 text-xs font-semibold" style={{ color: 'var(--cc-ink-2)' }}>
        Roles
      </legend>
      {STAFF_ROLES.map((role) => (
        <label key={role} className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={value.includes(role)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...value, role]
                  : value.filter((candidate) => candidate !== role),
              )
            }
          />
          <span>{role.replaceAll('_', ' ')}</span>
        </label>
      ))}
    </fieldset>
  )
}

function StaffAccountRow({
  account,
  saving,
  onSave,
  onResetPassword,
}: {
  account: StaffAccount
  saving: boolean
  onSave: (operatorId: string, payload: StaffAccountPatch) => void
  onResetPassword: (operatorId: string, password: string) => void
}) {
  const [roles, setRoles] = useState(account.roles)
  const [enabled, setEnabled] = useState(account.enabled)
  const [password, setPassword] = useState('')
  const isFirstAdmin = account.account_type === 'first_admin' || account.immutable

  return (
    <article className="grid gap-3 rounded-md p-3" style={insetStyle}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="m-0 text-sm font-semibold">{account.display_name}</h3>
          <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {account.username} · {isFirstAdmin ? 'First administrator' : account.enabled ? 'Enabled' : 'Access disabled'}
          </p>
        </div>
        {isFirstAdmin && (
          <span className="rounded px-2 py-1 text-[10px]" style={{ background: 'var(--cc-surface-3)' }}>
            Password recovery stays in First Setup
          </span>
        )}
      </div>
      {isFirstAdmin ? (
        <div className="flex flex-wrap gap-1">
          {account.roles.map((role) => (
            <span key={role} className="rounded px-2 py-1 text-[10px]" style={{ background: 'var(--cc-surface-3)' }}>
              {role.replaceAll('_', ' ')}
            </span>
          ))}
        </div>
      ) : (
        <>
          <RoleChoices value={roles} onChange={setRoles} />
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            Allow this person to sign in
          </label>
          <div className="flex flex-wrap items-end gap-2">
            <button
              type="button"
              disabled={saving || roles.length === 0}
              onClick={() => onSave(account.operator_id, { roles, enabled })}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              Save access
            </button>
            <label className="grid min-w-[14rem] gap-1 text-xs">
              <span style={{ color: 'var(--cc-ink-3)' }}>Set a new password</span>
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="rounded-md px-2 py-1.5"
                style={fieldStyle}
              />
            </label>
            <button
              type="button"
              disabled={saving || password.length < 12}
              onClick={() => {
                onResetPassword(account.operator_id, password)
                setPassword('')
              }}
              className="rounded-md px-3 py-1.5 text-xs font-semibold"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
            >
              Reset password
            </button>
          </div>
        </>
      )}
    </article>
  )
}

export function StaffAccountsScreen({ api }: { api: StaffAccountsApi }) {
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [roles, setRoles] = useState<StaffRole[]>([])
  const [actionError, setActionError] = useState<string | null>(null)
  const accountsQuery = useQuery({ queryKey: ['staff-accounts'], queryFn: api.listAccounts, retry: false })
  const sessionsQuery = useQuery({ queryKey: ['staff-sessions'], queryFn: api.listSessions, retry: false })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['staff-accounts'] })
    void queryClient.invalidateQueries({ queryKey: ['staff-sessions'] })
  }
  const createMutation = useMutation({
    mutationFn: (payload: StaffCreatePayload) => api.createAccount(payload),
    onSuccess: () => {
      setActionError(null)
      setUsername('')
      setDisplayName('')
      setPassword('')
      setRoles([])
      refresh()
    },
    onError: (error) => setActionError(errorMessage(error, 'Could not add the staff account.')),
  })
  const updateMutation = useMutation({
    mutationFn: ({ operatorId, patch }: { operatorId: string; patch: StaffAccountPatch }) =>
      api.updateAccount(operatorId, patch),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (error) => setActionError(errorMessage(error, 'Could not update staff access.')),
  })
  const resetMutation = useMutation({
    mutationFn: ({ operatorId, password: nextPassword }: { operatorId: string; password: string }) =>
      api.resetPassword(operatorId, nextPassword),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (error) => setActionError(errorMessage(error, 'Could not reset the password.')),
  })
  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => api.revokeSession(sessionId),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (error) => setActionError(errorMessage(error, 'Could not revoke the session.')),
  })

  function addAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createMutation.mutate({
      username: username.trim(),
      display_name: displayName.trim(),
      password,
      roles,
    })
  }

  return (
    <main className="grid gap-5">
      <header>
        <h1 className="m-0 text-xl font-semibold">Staff accounts</h1>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          Add station staff, set their roles, and end access when a session or account should no longer be active.
        </p>
      </header>
      {actionError && <p role="alert" className="m-0 rounded-md p-3 text-sm text-red-700" style={insetStyle}>{actionError}</p>}

      <section className="grid gap-3 rounded-lg p-4" style={panelStyle} aria-labelledby="staff-add-heading">
        <div>
          <h2 id="staff-add-heading" className="m-0 text-base font-semibold">Add staff</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Passwords need at least 12 characters. Each person should receive only the roles needed for their work.
          </p>
        </div>
        <form onSubmit={addAccount} className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-xs">
            <span>Username</span>
            <input required autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
          </label>
          <label className="grid gap-1 text-xs">
            <span>Display name</span>
            <input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
          </label>
          <label className="grid gap-1 text-xs">
            <span>Temporary password</span>
            <input required type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
          </label>
          <RoleChoices value={roles} onChange={setRoles} />
          <div className="sm:col-span-2">
            <button
              type="submit"
              disabled={createMutation.isPending || roles.length === 0}
              className="rounded-md px-3 py-2 text-xs font-semibold"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              {createMutation.isPending ? 'Adding…' : 'Add staff account'}
            </button>
          </div>
        </form>
      </section>

      <section className="grid gap-3" aria-labelledby="staff-account-list-heading">
        <h2 id="staff-account-list-heading" className="m-0 text-base font-semibold">Accounts</h2>
        {accountsQuery.isLoading && <p className="m-0 text-sm">Loading staff accounts…</p>}
        {accountsQuery.error && <p role="alert" className="m-0 text-sm text-red-700">{errorMessage(accountsQuery.error, 'Could not load staff accounts.')}</p>}
        {accountsQuery.data?.map((account) => (
          <StaffAccountRow
            key={account.operator_id}
            account={account}
            saving={updateMutation.isPending || resetMutation.isPending}
            onSave={(operatorId, patch) => updateMutation.mutate({ operatorId, patch })}
            onResetPassword={(operatorId, nextPassword) => resetMutation.mutate({ operatorId, password: nextPassword })}
          />
        ))}
      </section>

      <section className="grid gap-3 rounded-lg p-4" style={panelStyle} aria-labelledby="staff-session-heading">
        <div>
          <h2 id="staff-session-heading" className="m-0 text-base font-semibold">Signed-in sessions</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Sessions expire after 12 hours. Revoking a session ends access from that browser or device.
          </p>
        </div>
        {sessionsQuery.isLoading && <p className="m-0 text-sm">Loading sessions…</p>}
        {sessionsQuery.error && <p role="alert" className="m-0 text-sm text-red-700">{errorMessage(sessionsQuery.error, 'Could not load sessions.')}</p>}
        {sessionsQuery.data?.length === 0 && <p className="m-0 text-sm">There are no saved station sessions.</p>}
        {sessionsQuery.data?.map((session) => (
          <div key={session.session_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md p-3 text-xs" style={insetStyle}>
            <div>
              <p className="m-0 font-semibold">{session.operator_display_name}{session.current ? ' · this browser' : ''}</p>
              <p className="m-0" style={{ color: 'var(--cc-ink-3)' }}>
                {session.roles.map((role) => role.replaceAll('_', ' ')).join(', ')} · expires {new Date(session.expires_at).toLocaleString()}
                {session.expired ? ' · expired' : ''}
              </p>
            </div>
            <button
              type="button"
              disabled={session.expired || revokeMutation.isPending}
              onClick={() => revokeMutation.mutate(session.session_id)}
              className="rounded-md px-3 py-1.5 font-semibold"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
            >
              Revoke session
            </button>
          </div>
        ))}
      </section>
    </main>
  )
}

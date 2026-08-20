import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  getStaffIdentity,
  getTsduckStatus,
  installTsduck,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type { TsduckInstallReport, TsduckStatus } from '../types/api.generated'

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function reportTone(status: TsduckInstallReport['status']): 'ok' | 'warn' | 'err' {
  if (status === 'installed' || status === 'already-installed') return 'ok'
  if (status === 'failed') return 'err'
  return 'warn' // operator-assisted / unsupported
}

const TONE_BG: Record<'ok' | 'warn' | 'err', string> = {
  ok: 'var(--cc-ok-soft)',
  warn: 'var(--cc-warn-soft)',
  err: 'var(--cc-err-soft)',
}

// Presentational only (no data fetching) so it unit-tests without a network.
export function TsduckStatusView({
  status,
  loading,
  installing,
  report,
  error,
  installError,
  canInstall,
  onInstall,
}: {
  status: TsduckStatus | undefined
  loading?: boolean
  installing?: boolean
  report?: TsduckInstallReport
  error?: unknown
  installError?: unknown
  canInstall?: boolean
  onInstall?: () => void
}) {
  const installed = status?.installed ?? false
  return (
    <section
      aria-label="Cable verification"
      className="grid gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-base font-semibold">Cable verification</h2>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
          style={{ background: installed ? 'var(--cc-ok-soft)' : 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
        >
          {loading ? 'Checking…' : installed ? 'Ready' : 'Not set up'}
        </span>
      </div>
      <p className="m-0 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
        {installed
          ? 'CivicCast can run a bounded TSDuck transport check before provider validation.'
          : 'Turn this on and CivicCast downloads the free TSDuck toolkit for you — no separate setup, no admin rights — so it can run a bounded transport check on your cable channels before provider validation.'}
      </p>
      {installed && status?.version && (
        <p className="m-0 cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {status.version}
        </p>
      )}
      {!installed && (
        <button
          type="button"
          onClick={onInstall}
          disabled={!canInstall || installing}
          className="w-fit rounded-md px-3 py-2 text-sm font-semibold"
          style={{
            background: canInstall ? 'var(--cc-ink)' : 'var(--cc-surface-3)',
            color: canInstall ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)',
          }}
        >
          {installing ? 'Downloading TSDuck… this can take a few minutes' : 'Enable cable verification'}
        </button>
      )}
      {!installed && !canInstall && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Enabling cable verification requires setup admin or support admin.
        </p>
      )}
      {report && (
        <div className="rounded-md p-2 text-xs" style={{ background: TONE_BG[reportTone(report.status)], color: 'var(--cc-ink)' }}>
          {report.message}
        </div>
      )}
      {Boolean(installError) && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(installError, 'Could not install cable verification.')}
        </div>
      )}
      {Boolean(error) && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Cable verification status could not load.')}
        </div>
      )}
    </section>
  )
}

export function CableVerificationCard() {
  const queryClient = useQueryClient()
  const install = useMutation({
    mutationFn: installTsduck,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tsduck-status'] })
      void queryClient.invalidateQueries({ queryKey: ['headend-readiness'] })
    },
  })
  const statusQuery = useQuery({
    queryKey: ['tsduck-status'],
    queryFn: getTsduckStatus,
    retry: false,
    // While an install is running, poll so a server-side completion is reflected
    // even if the long POST connection was dropped.
    refetchInterval: install.isPending ? 4000 : false,
  })
  const identityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  // Fail CLOSED: only enable the privileged install action once identity is known
  // AND carries an admin role. An errored/loading identity is NOT authorized
  // (the server gate still enforces; this keeps the UI honest).
  const canInstall =
    identityQuery.isSuccess &&
    (hasOperatorRole(identityQuery.data, 'setup_admin') ||
      hasOperatorRole(identityQuery.data, 'support_admin'))
  return (
    <TsduckStatusView
      status={statusQuery.data}
      loading={statusQuery.isLoading}
      installing={install.isPending}
      report={install.data}
      error={statusQuery.error}
      installError={install.error}
      canInstall={canInstall}
      onInstall={() => install.mutate()}
    />
  )
}

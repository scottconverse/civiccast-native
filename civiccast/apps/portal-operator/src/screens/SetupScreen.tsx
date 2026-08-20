import { useEffect, useMemo, useRef, useState } from 'react'
import type { Ref } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  acknowledgeRecoveryKit,
  ApiError,
  completeHandoffRecovery,
  configureBackup,
  completePublicFirstAdminSetup,
  getBackupStatus,
  hasSetupNonce,
  getPublicStorageState,
  getProviderReadiness,
  getStaffIdentity,
  getStationSetupState,
  loginStationAdmin,
  preparePublicStorage,
  provisionR2Concierge,
  recoverStationAdmin,
  recordProviderProof,
  saveProviderCredentials,
  startHandoffRecovery,
  testProviderConnection,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { AuthRequiredState } from '../components/AuthRequiredState'
import { SourceUploadWizard } from '../components/setup/SourceUploadWizard'
import { readinessLabel, stateLabel, toneForReadiness } from './status-language'
import type {
  BackupStatus,
  FirstAdminSetupRequest,
  FirstAdminSetupResponse,
  ManagedStorageStatus,
  ProviderConnectionTestResponse,
  ProviderReadinessItem,
  R2ConciergeResponse,
  StationAuthResponse,
  StationLoginRequest,
  StationRecoveryRequest,
} from '../types/api.generated'

const STORAGE_HANDOFF_NOTE_ID = 'storage-installer-handoff-note'

// Setup-wizard provider ids that expose a live "Test connection" (CDN
// providers). Pairs with the backend's CDN_CREDENTIAL_PROVIDER_IDS.
const CDN_TEST_PROVIDER_IDS: readonly string[] = ['cloudflare-r2', 'bunny']

const INITIAL_FORM: FirstAdminSetupRequest = {
  station_name: '',
  admin_display_name: '',
  admin_username: '',
  admin_password: '',
  recovery_kit_destination: '',
  default_channel_id: 'government',
  public_base_url: null,
}

const INITIAL_LOGIN: StationLoginRequest = {
  admin_username: '',
  admin_password: '',
}

const INITIAL_RECOVERY: StationRecoveryRequest = {
  admin_username: '',
  recovery_code: '',
  new_admin_password: '',
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? error.message
  if (error instanceof Error) return error.message
  return fallback
}

function isSetupHandoffError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  const message = `${error.detail ?? ''} ${error.message}`.toLowerCase()
  return error.status === 403 && (message.includes('operator console') || message.includes('setup'))
}

function Field({
  id,
  label,
  help,
  value,
  secret = false,
  inputRef,
  onChange,
  onBlur,
  error,
}: {
  id: string
  label: string
  help: string
  value: string
  secret?: boolean
  inputRef?: Ref<HTMLInputElement>
  onChange: (value: string) => void
  onBlur?: () => void
  error?: string
}) {
  const [revealed, setRevealed] = useState(false)
  return (
    <label className="grid gap-1 text-sm" htmlFor={id}>
      <span className="font-semibold">{label}</span>
      <span className="flex gap-2">
        <input
          id={id}
          ref={inputRef}
          type={secret && !revealed ? 'password' : 'text'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          // GauntletGate F2: role="alert" announces the error ONCE, when it
          // first appears. These two attributes make it part of the field's
          // accessible description, so it is re-announced every time the field
          // regains focus -- WCAG 2.2 SC 3.3.1 / 4.1.2. This is the
          // account-recovery-critical first-run form; a confused submission
          // here is a locked-out station.
          className="flex-1 rounded-md px-3 py-2"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
        {secret && (
          <button
            type="button"
            onClick={() => setRevealed((current) => !current)}
            aria-pressed={revealed}
            className="rounded-md px-3 py-2 text-xs font-semibold"
            style={{
              background: 'var(--cc-surface-2)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          >
            {revealed ? 'Hide' : 'Show'}
          </button>
        )}
      </span>
      {error && (
        <span
          id={`${id}-error`}
          role="alert"
          className="text-xs"
          style={{ color: 'var(--cc-err)' }}
        >
          {error}
        </span>
      )}
      <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        {help}
      </span>
    </label>
  )
}

function RecoveryKitPanel({
  setup,
  onAcknowledge,
  ackPending,
  ackError,
}: {
  setup: FirstAdminSetupResponse
  onAcknowledge: () => void
  ackPending: boolean
  ackError: unknown
}) {
  const [kitActionTaken, setKitActionTaken] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const printable = useMemo(
    () =>
      [
        `CivicCast recovery kit: ${setup.profile.station_name}`,
        `Admin: ${setup.profile.admin_username}`,
        `Kit: ${setup.recovery_kit.kit_id}`,
        '',
        'Recovery codes:',
        ...setup.recovery_kit.recovery_codes.map((code) => `- ${code}`),
        '',
        ...setup.recovery_kit.instructions,
      ].join('\n'),
    [setup],
  )

  const download = () => {
    const blob = new Blob([printable], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `civiccast-recovery-kit-${setup.recovery_kit.kit_id}.txt`
    anchor.click()
    URL.revokeObjectURL(url)
    setKitActionTaken(true)
  }

  const print = () => {
    window.print()
    setKitActionTaken(true)
  }

  return (
    <section
      className="grid gap-4 rounded-md p-4"
      style={{ background: 'var(--cc-ok-soft)', border: '1px solid var(--cc-ok)' }}
    >
      <div>
        <h2 className="m-0 text-base font-semibold">Recovery kit ready</h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          These codes are shown once and CivicCast cannot show them again. If the admin password
          is ever lost, these codes are the only way back in. Save or print them now.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {setup.recovery_kit.recovery_codes.map((code) => (
          <div
            key={code}
            className="cc-mono rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-surface)' }}
          >
            {code}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={print}
          className="rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
        >
          Print kit
        </button>
        <button
          type="button"
          onClick={download}
          className="rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          Save kit
        </button>
      </div>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Save kit downloads a plain-text file to this browser&apos;s Downloads folder. Print kit
        opens your system print dialog. CivicCast keeps only scrambled verification copies of
        these codes and can never show them again.
      </p>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!kitActionTaken}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          I have saved or printed these recovery codes and stored them away from this computer.
          {!kitActionTaken && (
            <span className="block text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Use Print kit or Save kit first.
            </span>
          )}
        </span>
      </label>
      <div>
        <button
          type="button"
          disabled={!confirmed || ackPending}
          onClick={onAcknowledge}
          className="rounded-md px-4 py-2 text-sm font-semibold"
          style={{
            background: !confirmed || ackPending ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
            color: !confirmed || ackPending ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
          }}
        >
          {ackPending ? 'Recording confirmation...' : 'Continue to the console'}
        </button>
      </div>
      {ackError != null && (
        <div
          role="alert"
          className="rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
        >
          {apiMessage(ackError, 'Could not record the confirmation. Try again.')}
        </div>
      )}
    </section>
  )
}

type SignedInPanelAuth = {
  status: StationAuthResponse['status'] | 'complete'
  profile: StationAuthResponse['profile']
}

function titleCase(value: string | undefined | null): string {
  if (!value) return 'Not set'
  return value
    .replaceAll('_', ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(' ')
}

function operationModeLabel(value: string | undefined | null): string {
  if (value === 'test') return 'Test mode'
  if (value === 'on_air') return 'On-air mode'
  return titleCase(value)
}

function dashboardReadyLabel(value: string | undefined | null): string {
  // Route the dashboard readiness state through the shared lifecycle vocabulary
  // (PE-3) rather than a local title-caser: stateLabel already renders
  // 'not_ready' -> 'Not ready' and 'ready' -> 'Ready', keeping one source of
  // truth for status words. 'Not set' is preserved for an absent value.
  return stateLabel(value, 'Not set')
}

function CommissioningDefaultsPanel({
  profile,
  className,
}: {
  profile: StationAuthResponse['profile'] | null | undefined
  className?: string
}) {
  if (!profile) return null
  const channels = profile.channel_profiles ?? []
  const storage = profile.storage_locations
  const roles = profile.default_roles ?? []
  const channelCount = profile.channel_count ?? (channels.length || 1)
  return (
    <section
      className={`grid gap-3 rounded-md p-4 ${className ?? ''}`.trim()}
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">First-run defaults</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Generated station settings recorded during setup.
          </p>
        </div>
        <span
          className="rounded-md px-2.5 py-1 text-xs font-semibold"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          {channelCount} channel{channelCount === 1 ? '' : 's'}
        </span>
      </div>
      <div className="grid gap-2 text-sm md:grid-cols-3">
        <div>
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Timezone
          </div>
          <div>{profile.station_timezone ?? 'local'}</div>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Mode
          </div>
          <div>{operationModeLabel(profile.operation_mode)}</div>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Dashboard commissioning
          </div>
          <div>{dashboardReadyLabel(profile.dashboard_ready_state)}</div>
        </div>
      </div>
      {channels.length > 0 && (
        <div className="grid gap-2">
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Channels
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            {channels.map((channel) => (
              <div
                key={channel.channel_id}
                className="rounded-md p-3 text-sm"
                style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
              >
                <div className="font-semibold">{channel.display_name}</div>
                <div className="mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
                  {channel.channel_id}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {storage && (
        <div className="grid gap-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
            Storage
          </div>
          <div className="break-all">Media: {storage.media_library}</div>
          <div className="break-all">Recordings: {storage.recordings}</div>
          <div className="break-all">Backups: {storage.backups}</div>
        </div>
      )}
      <div className="grid gap-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <div>Sample content: {profile.sample_content_enabled ? 'enabled' : 'disabled'}</div>
        <div>Initial schedule: {profile.initial_schedule_enabled ? 'enabled' : 'disabled'}</div>
        {roles.length > 0 && <div>Default roles: {roles.map(titleCase).join(', ')}</div>}
      </div>
    </section>
  )
}

function SignedInPanel({ auth }: { auth: SignedInPanelAuth }) {
  return (
    <>
      <section
        className="rounded-md p-4"
        style={{ background: 'var(--cc-ok-soft)', border: '1px solid var(--cc-ok)' }}
      >
        <h2 className="m-0 text-base font-semibold">
          {auth.status === 'recovered'
            ? 'Account recovered'
            : auth.status === 'complete'
              ? 'Setup complete'
              : 'Signed in'}
        </h2>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          CivicCast saved a fresh console token in this browser for {auth.profile.admin_display_name}.
        </p>
        <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Next step: open System Health and confirm readiness before the meeting.
        </p>
      </section>
      <CommissioningDefaultsPanel profile={auth.profile} />
    </>
  )
}

function StorageSetupPanel({
  storage,
  error,
  isLoading,
  isPreparing,
  onPrepare,
}: {
  storage?: ManagedStorageStatus
  error: unknown
  isLoading: boolean
  isPreparing: boolean
  onPrepare: () => void
}) {
  const ready = storage?.status === 'ready'
  const busy = isLoading || isPreparing
  // GauntletGate W-2: every /api/setup/* mutation 403s without the installer's
  // one-time handoff nonce. A console reached directly -- a bookmark, a refresh
  // that drops the query string, a typed URL -- has no nonce, and offering an
  // enabled primary action there hands the user a guaranteed failure. The nonce
  // gate is a good security control; presenting a dead button is not.
  const canPrepare = hasSetupNonce()
  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{
        background: ready ? 'var(--cc-ok-soft)' : 'var(--cc-surface)',
        border: `1px solid ${ready ? 'var(--cc-ok)' : 'var(--cc-line)'}`,
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-base font-semibold">Durable storage</h2>
          <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            {ready
              ? 'CivicCast has a local database for meeting records, captions, summaries, and subscriptions.'
              : 'Prepare the local database before creating the first admin.'}
          </p>
        </div>
        {ready ? (
          <div
            role="status"
            aria-live="polite"
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ink)' }}
          >
            Storage ready
          </div>
        ) : (
          <button
            type="button"
            disabled={busy || !canPrepare}
            aria-describedby={canPrepare ? undefined : STORAGE_HANDOFF_NOTE_ID}
            onClick={onPrepare}
            className="rounded-md px-4 py-2 text-sm font-semibold"
            style={{
              background: busy || !canPrepare ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
              color: busy || !canPrepare ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
            }}
          >
            {isPreparing ? 'Preparing...' : 'Prepare storage'}
          </button>
        )}
      </div>
      {!ready && !canPrepare && (
        <div
          id={STORAGE_HANDOFF_NOTE_ID}
          role="note"
          aria-label="Restore the setup handoff the Windows installer creates"
          className="rounded-md p-3 text-xs"
          style={{
            background: 'var(--cc-warn-soft)',
            border: '1px solid var(--cc-warn)',
            color: 'var(--cc-ink)',
          }}
        >
          <strong className="block text-sm">Restore the setup handoff the Windows installer creates</strong>
          <span>
            Preparing storage needs the one-time handoff the Windows installer creates, and this
            page was opened without it. Nothing is wrong with the station, but reopening CivicCast
            will not recreate it. On the station, run{' '}
            <code>
              &quot;C:\Program Files\CivicCast (Native)\CivicCast Native.exe&quot;
              --civiccast-restore-setup-handoff
            </code>{' '}
            as an administrator and approve the Windows prompt, then use{' '}
            <strong>Open operator console</strong> and prepare storage from there.
          </span>
        </div>
      )}
      {storage && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Next step: {storage.next_step}
        </p>
      )}
      {error != null && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(error, 'Storage setup failed.')}
        </div>
      )}
    </section>
  )
}

function ReadinessPill({ status }: { status: BackupStatus['status'] | ProviderReadinessItem['status'] }) {
  const tone = toneForReadiness(status)
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
      style={{
        background: tone === 'ok'
          ? 'var(--cc-ok-soft)'
          : tone === 'err'
            ? 'var(--cc-err-soft)'
            : 'var(--cc-warn-soft)',
        color: 'var(--cc-ink)',
      }}
    >
      {readinessLabel(status)}
    </span>
  )
}

export function BackupSetupPanel() {
  const queryClient = useQueryClient()
  const [destination, setDestination] = useState<string | null>(null)
  const backupQuery = useQuery({
    queryKey: ['backup-status'],
    queryFn: getBackupStatus,
    retry: false,
  })
  const backupMutation = useMutation({
    mutationFn: configureBackup,
    onSuccess: (response) => {
      setDestination((current) => response.destination ?? current ?? '')
      void queryClient.invalidateQueries({ queryKey: ['backup-status'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      void queryClient.invalidateQueries({ queryKey: ['provider-readiness'] })
    },
  })
  const backup = backupQuery.data
  const resolvedDestination = destination ?? backup?.destination ?? ''

  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="m-0 text-base font-semibold">Backup destination</h2>
          <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Choose the folder or drive CivicCast should verify before meetings.
          </p>
        </div>
        {backup && <ReadinessPill status={backup.status} />}
      </div>
      {backup && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {backup.message} <strong>Next step.</strong> {backup.next_step}
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid gap-1 text-sm" htmlFor="backup-destination">
          <span className="font-semibold">Backup folder</span>
          <input
            id="backup-destination"
            value={resolvedDestination}
            placeholder={backup?.destination ?? 'D:\\CivicCastBackups'}
            onChange={(event) => setDestination(event.target.value)}
            className="rounded-md px-3 py-2"
            style={{
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          />
        </label>
        <button
          type="button"
          disabled={backupMutation.isPending || resolvedDestination.trim() === ''}
          onClick={() => backupMutation.mutate({ destination: resolvedDestination.trim() })}
          className="self-end rounded-md px-4 py-2 text-sm font-semibold"
          style={{
            background: resolvedDestination.trim() === '' ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
            color: resolvedDestination.trim() === '' ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
          }}
        >
          {backupMutation.isPending ? 'Verifying...' : 'Verify backup'}
        </button>
      </div>
      {(backupQuery.error || backupMutation.error) && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(backupQuery.error ?? backupMutation.error, 'Backup setup failed.')}
        </div>
      )}
    </section>
  )
}

const _R2_SIGNUP_URL = 'https://dash.cloudflare.com/sign-up'
const _R2_TOKEN_URL = 'https://dash.cloudflare.com/profile/api-tokens'

export function R2ConciergeCard({ canManageProviders }: { canManageProviders: boolean }) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState('')
  const [result, setResult] = useState<R2ConciergeResponse | null>(null)
  const mutation = useMutation({
    mutationFn: () => provisionR2Concierge({ token }),
    onSuccess: (response) => {
      setResult(response)
      if (response.status === 'ok') {
        setToken('')
        void queryClient.invalidateQueries({ queryKey: ['provider-readiness'] })
        void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      }
    },
  })
  const canProvision = canManageProviders && token.trim() !== '' && !mutation.isPending

  return (
    <div
      className="mt-3 grid gap-2 rounded-md p-3 text-xs"
      style={{ background: 'var(--cc-surface)', border: '1px dashed var(--cc-line)' }}
    >
      <div>
        <div className="font-semibold">CDN concierge (recommended)</div>
        <p className="m-0 mt-1" style={{ color: 'var(--cc-ink-3)' }}>
          Your station&apos;s internet can serve about 200 viewers directly. For big meetings,
          CivicCast rents overflow capacity from Cloudflare -- free until the night everyone shows
          up. You do not need to know what a CDN is: make a free Cloudflare account, create one
          token, and paste it below. CivicCast does everything else.
        </p>
      </div>
      <ol className="m-0 grid gap-1 pl-4" style={{ color: 'var(--cc-ink-3)' }}>
        <li>
          <a href={_R2_SIGNUP_URL} target="_blank" rel="noreferrer" className="font-semibold">
            Create a free Cloudflare account
          </a>{' '}
          (skip this if you already have one).
        </li>
        <li>
          <a href={_R2_TOKEN_URL} target="_blank" rel="noreferrer" className="font-semibold">
            Create an API token
          </a>{' '}
          scoped to R2 Edit, then copy it.
        </li>
        <li>Paste the token below and click &quot;Provision for me&quot;.</li>
      </ol>
      <label className="grid gap-1" htmlFor="r2-concierge-token">
        <span className="font-semibold">Cloudflare API token</span>
        <input
          id="r2-concierge-token"
          type="password"
          autoComplete="off"
          value={token}
          disabled={!canManageProviders}
          onChange={(event) => setToken(event.target.value)}
          className="rounded-md px-3 py-2"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
        />
      </label>
      <button
        type="button"
        disabled={!canProvision}
        onClick={() => mutation.mutate()}
        className="justify-self-start rounded-md px-3 py-2 text-sm font-semibold"
        style={{
          background: canProvision ? 'var(--cc-brand)' : 'var(--cc-surface-3)',
          color: canProvision ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)',
        }}
      >
        {mutation.isPending ? 'Provisioning...' : 'Provision for me'}
      </button>
      {mutation.error && (
        <div role="alert" className="rounded-md p-2" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(mutation.error, 'Provisioning could not run.')}
        </div>
      )}
      {result?.status === 'ok' && (
        <div role="status" className="rounded-md p-2" style={{ background: 'var(--cc-ok-soft)', color: 'var(--cc-ok)' }}>
          {result.message}
          {result.public_base_url ? ` Media will be served from ${result.public_base_url}.` : ''}
        </div>
      )}
      {result?.status === 'failed' && result.error_code === 'r2_not_enabled' && (
        <div className="grid gap-2 rounded-md p-2" style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}>
          <div>{result.message}</div>
          {result.deep_link && (
            <a href={result.deep_link} target="_blank" rel="noreferrer" className="font-semibold">
              Enable R2 on Cloudflare
            </a>
          )}
          <button
            type="button"
            disabled={!canProvision}
            onClick={() => mutation.mutate()}
            className="justify-self-start rounded-md px-3 py-2 text-sm font-semibold"
            style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)', border: '1px solid var(--cc-line)' }}
          >
            Retry
          </button>
        </div>
      )}
      {result?.status === 'failed' && result.error_code !== 'r2_not_enabled' && (
        <div role="alert" className="rounded-md p-2" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {result.message}
        </div>
      )}
    </div>
  )
}

function ProviderReadinessPanel({ canManageProviders }: { canManageProviders: boolean }) {
  const queryClient = useQueryClient()
  const [providerValues, setProviderValues] = useState<Record<string, Record<string, string>>>({})
  const [proofValues, setProofValues] = useState<Record<string, string>>({})
  const [proofReviewed, setProofReviewed] = useState<Record<string, boolean>>({})
  const [savedProvider, setSavedProvider] = useState<string | null>(null)
  const [savedProof, setSavedProof] = useState<string | null>(null)
  const [connectionResults, setConnectionResults] = useState<
    Record<string, ProviderConnectionTestResponse>
  >({})
  const providerQuery = useQuery({
    queryKey: ['provider-readiness'],
    queryFn: getProviderReadiness,
    retry: false,
  })
  const credentialMutation = useMutation({
    mutationFn: saveProviderCredentials,
    onSuccess: (response) => {
      setSavedProvider(response.provider_id)
      setProviderValues((current) => ({ ...current, [response.provider_id]: {} }))
      void queryClient.invalidateQueries({ queryKey: ['provider-readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const proofMutation = useMutation({
    mutationFn: recordProviderProof,
    onSuccess: (response) => {
      setSavedProof(response.provider_id)
      setProofValues((current) => ({ ...current, [response.provider_id]: '' }))
      setProofReviewed((current) => ({ ...current, [response.provider_id]: false }))
      void queryClient.invalidateQueries({ queryKey: ['provider-readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const connectionMutation = useMutation({
    mutationFn: (providerId: string) => testProviderConnection(providerId),
    onSuccess: (result) => {
      setConnectionResults((current) => ({ ...current, [result.provider_id]: result }))
    },
  })
  const items = providerQuery.data?.items ?? []

  const updateProviderValue = (providerId: string, fieldId: string, value: string) => {
    setProviderValues((current) => ({
      ...current,
      [providerId]: {
        ...(current[providerId] ?? {}),
        [fieldId]: value,
      },
    }))
  }

  const submitProvider = (providerId: string) => {
    if (!canManageProviders) return
    credentialMutation.mutate({
      provider_id: providerId,
      values: providerValues[providerId] ?? {},
    })
  }

  const submitProof = (providerId: string) => {
    if (!canManageProviders) return
    proofMutation.mutate({
      provider_id: providerId,
      evidence_reference: proofValues[providerId] ?? '',
      redaction_reviewed: true,
    })
  }

  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <h2 className="m-0 text-base font-semibold">Provider setup</h2>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Required items protect the local tester path. Optional providers can wait.
        </p>
      </div>
      {!canManageProviders && (
        <div
          role="status"
          className="rounded-md p-3 text-xs"
          style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)' }}
        >
          Setup admin role required to save provider details or proof. Readiness remains visible.
        </div>
      )}
      {providerQuery.isLoading && (
        <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Checking provider setup...
        </div>
      )}
      {providerQuery.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(providerQuery.error, 'Provider readiness could not load.')}
        </div>
      )}
      <div className="grid gap-2 md:grid-cols-2">
        {items.map((item) => {
          const whatYouNeed = item.what_you_need ?? []
          const setupSteps = item.setup_steps ?? []
          const credentialFields = item.credential_fields ?? []
          const itemValues = providerValues[item.id] ?? {}
          const proofReference = proofValues[item.id] ?? ''
          const connectionResult = connectionResults[item.id]
          const canRecordProof =
            canManageProviders &&
            item.status === 'needs_live_proof' &&
            item.proof_status === 'needs_live_proof' &&
            proofReference.trim() !== '' &&
            proofReviewed[item.id] === true
          const canSave =
            canManageProviders &&
            credentialFields.length > 0 &&
            credentialFields
              .filter((field) => field.required)
              .every((field) => (itemValues[field.id] ?? '').trim() !== '')
          return (
            <article
              key={item.id}
              className="rounded-md p-3"
              style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="m-0 text-sm font-semibold">{item.label}</h3>
                <ReadinessPill status={item.status} />
              </div>
              <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                {item.message}
              </p>
              <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                <strong>{item.required ? 'Required' : 'Optional'}.</strong> {item.next_step}
              </p>
              {(whatYouNeed.length > 0 || setupSteps.length > 0 || item.proof_requirement) && (
              <details className="mt-3 rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface)' }}>
                <summary className="cursor-pointer font-semibold">Setup guide</summary>
                {whatYouNeed.length > 0 && (
                  <div className="mt-2">
                    <div className="font-semibold">What you need</div>
                    <ul className="m-0 mt-1 grid gap-1 pl-4" style={{ color: 'var(--cc-ink-3)' }}>
                      {whatYouNeed.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {setupSteps.length > 0 && (
                  <div className="mt-2">
                    <div className="font-semibold">Steps</div>
                    <ol className="m-0 mt-1 grid gap-1 pl-4" style={{ color: 'var(--cc-ink-3)' }}>
                      {setupSteps.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ol>
                  </div>
                )}
                {item.setup_url && (
                  <a
                    href={item.setup_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-block font-semibold"
                  >
                    Open provider setup
                  </a>
                )}
                {item.proof_requirement && (
                  <p className="m-0 mt-2" style={{ color: 'var(--cc-ink-3)' }}>
                    <strong>Proof required.</strong> {item.proof_requirement}
                  </p>
                )}
                {item.evidence_reference && (
                  <p className="m-0 mt-2" style={{ color: 'var(--cc-ok)' }}>
                    <strong>Proof evidence.</strong> {item.evidence_reference}
                  </p>
                )}
              </details>
            )}
              {item.status === 'needs_live_proof' && item.proof_status === 'needs_live_proof' && (
                <div className="mt-3 grid gap-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface)' }}>
                  <div>
                    <div className="font-semibold">Record redacted proof</div>
                    <p className="m-0 mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                      Save only a file path, URL, or release evidence reference after secrets have been removed.
                    </p>
                  </div>
                  <label className="grid gap-1" htmlFor={`${item.id}-proof-reference`}>
                    <span className="font-semibold">Evidence reference</span>
                    <input
                      id={`${item.id}-proof-reference`}
                      type="text"
                      value={proofReference}
                      disabled={!canManageProviders}
                      onChange={(event) =>
                        setProofValues((current) => ({ ...current, [item.id]: event.target.value }))
                      }
                      className="rounded-md px-3 py-2"
                      style={{
                        background: 'var(--cc-surface)',
                        border: '1px solid var(--cc-line)',
                        color: 'var(--cc-ink)',
                      }}
                    />
                  </label>
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={proofReviewed[item.id] === true}
                      disabled={!canManageProviders}
                      onChange={(event) =>
                        setProofReviewed((current) => ({ ...current, [item.id]: event.target.checked }))
                      }
                    />
                    <span>I reviewed the proof and removed tokens, passwords, private keys, and resident data.</span>
                  </label>
                  <button
                    type="button"
                    disabled={!canRecordProof || proofMutation.isPending}
                    onClick={() => submitProof(item.id)}
                    className="justify-self-start rounded-md px-3 py-2 text-sm font-semibold"
                    style={{
                      background: canRecordProof ? 'var(--cc-brand)' : 'var(--cc-surface-3)',
                      color: canRecordProof ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)',
                    }}
                  >
                    {proofMutation.isPending && proofMutation.variables?.provider_id === item.id
                      ? 'Recording...'
                      : 'Record proof'}
                  </button>
                  {savedProof === item.id && (
                    <div role="status" className="rounded-md p-2" style={{ background: 'var(--cc-ok-soft)' }}>
                      Proof evidence saved. Provider readiness will refresh.
                    </div>
                  )}
                </div>
              )}
              {item.id === 'cloudflare-r2' && (
                <R2ConciergeCard canManageProviders={canManageProviders} />
              )}
              {credentialFields.length > 0 && (
                <div className="mt-3 grid gap-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-surface)' }}>
                  <div>
                    <div className="font-semibold">
                      {item.id === 'cloudflare-r2' ? 'Or enter R2 details manually' : 'Save provider details'}
                    </div>
                    <p className="m-0 mt-1" style={{ color: 'var(--cc-ink-3)' }}>
                      CivicCast stores these locally and never shows secret values again.
                    </p>
                  </div>
                  {credentialFields.map((field) => (
                    <label key={field.id} className="grid gap-1" htmlFor={`${item.id}-${field.id}`}>
                      <span className="font-semibold">{field.label}</span>
                      <input
                        id={`${item.id}-${field.id}`}
                        type={field.secret ? 'password' : 'text'}
                        autoComplete="off"
                        value={itemValues[field.id] ?? ''}
                        disabled={!canManageProviders}
                        onChange={(event) => updateProviderValue(item.id, field.id, event.target.value)}
                        className="rounded-md px-3 py-2"
                        style={{
                          background: 'var(--cc-surface)',
                          border: '1px solid var(--cc-line)',
                          color: 'var(--cc-ink)',
                        }}
                      />
                      <span style={{ color: 'var(--cc-ink-3)' }}>{field.help_text}</span>
                    </label>
                  ))}
                  <button
                    type="button"
                    disabled={!canSave || credentialMutation.isPending}
                    onClick={() => submitProvider(item.id)}
                    className="justify-self-start rounded-md px-3 py-2 text-sm font-semibold"
                    style={{
                      background: canSave ? 'var(--cc-brand)' : 'var(--cc-surface-3)',
                      color: canSave ? 'var(--cc-brand-ink)' : 'var(--cc-ink-3)',
                    }}
                  >
                    {credentialMutation.isPending && credentialMutation.variables?.provider_id === item.id
                      ? 'Saving...'
                      : 'Save details'}
                  </button>
                  {savedProvider === item.id && (
                    <div role="status" className="rounded-md p-2" style={{ background: 'var(--cc-ok-soft)' }}>
                      Details saved. Run live proof before marking this provider ready.
                    </div>
                  )}
                  {CDN_TEST_PROVIDER_IDS.includes(item.id) && (
                    <div className="grid gap-2">
                      <button
                        type="button"
                        disabled={!canManageProviders || connectionMutation.isPending}
                        onClick={() => connectionMutation.mutate(item.id)}
                        className="justify-self-start rounded-md px-3 py-2 text-sm font-semibold"
                        style={{
                          background: 'var(--cc-surface-3)',
                          color: 'var(--cc-ink)',
                          border: '1px solid var(--cc-line)',
                        }}
                      >
                        {connectionMutation.isPending && connectionMutation.variables === item.id
                          ? 'Testing...'
                          : 'Test connection'}
                      </button>
                      <p className="m-0" style={{ color: 'var(--cc-ink-3)' }}>
                        Save details first, then test that these credentials reach the CDN.
                      </p>
                      {connectionResult && (
                        <div
                          role="status"
                          className="rounded-md p-2"
                          style={{
                            background:
                              connectionResult.status === 'ok'
                                ? 'var(--cc-ok-soft)'
                                : 'var(--cc-err-soft)',
                            color:
                              connectionResult.status === 'ok' ? 'var(--cc-ok)' : 'var(--cc-err)',
                          }}
                        >
                          {connectionResult.message}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </article>
          )
        })}
      </div>
      {credentialMutation.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(credentialMutation.error, 'Provider details could not be saved.')}
        </div>
      )}
      {proofMutation.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(proofMutation.error, 'Provider proof could not be saved.')}
        </div>
      )}
      {connectionMutation.error && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(connectionMutation.error, 'Connection test could not run.')}
        </div>
      )}
      {providerQuery.data && (
        <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          {providerQuery.data.next_step}
        </p>
      )}
    </section>
  )
}

function CostForecastPanel() {
  const [hours, setHours] = useState(2)
  const [meetings, setMeetings] = useState(4)
  const [viewers, setViewers] = useState(250)
  const gbPerHour = 2
  const storedGb = hours * meetings * gbPerHour
  const watchedGb = storedGb * viewers
  const estimatedBandwidth = watchedGb * 0.005

  return (
    <section
      className="grid gap-3 rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <h2 className="m-0 text-base font-semibold">Storage and viewing estimate</h2>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          A plain estimate for budgeting tester meetings. Actual provider bills may vary.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="grid gap-1 text-sm" htmlFor="forecast-hours">
          <span className="font-semibold">Hours per meeting</span>
          <input
            id="forecast-hours"
            type="number"
            min="1"
            max="12"
            value={hours}
            onChange={(event) => setHours(Number(event.target.value))}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="forecast-meetings">
          <span className="font-semibold">Meetings per month</span>
          <input
            id="forecast-meetings"
            type="number"
            min="1"
            max="60"
            value={meetings}
            onChange={(event) => setMeetings(Number(event.target.value))}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="forecast-viewers">
          <span className="font-semibold">Average viewers</span>
          <input
            id="forecast-viewers"
            type="number"
            min="1"
            max="100000"
            value={viewers}
            onChange={(event) => setViewers(Number(event.target.value))}
            className="rounded-md px-3 py-2"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)' }}>
          <div className="cc-mono text-lg font-semibold">{storedGb.toFixed(0)} GB</div>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>stored each month</div>
        </div>
        <div className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)' }}>
          <div className="cc-mono text-lg font-semibold">{watchedGb.toFixed(0)} GB</div>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>viewer bandwidth</div>
        </div>
        <div className="rounded-md p-3" style={{ background: 'var(--cc-surface-2)' }}>
          <div className="cc-mono text-lg font-semibold">${estimatedBandwidth.toFixed(2)}</div>
          <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>rough CDN estimate</div>
        </div>
      </div>
    </section>
  )
}

function StationAdminTools({ canManageProviders }: { canManageProviders: boolean }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="xl:col-span-2">
        <SourceUploadWizard />
      </div>
      <BackupSetupPanel />
      <CostForecastPanel />
      <div className="xl:col-span-2">
        <ProviderReadinessPanel canManageProviders={canManageProviders} />
      </div>
    </div>
  )
}

// Fallback only, for the default-`%PROGRAMDATA%` case and the sliver of a
// render before `startHandoffRecovery`'s response lands. The API's
// `code_file` (see `HandoffRecoveryPanel`'s `codeFile` state) is the real
// path and MUST be preferred: `civiccast.installer.handoff_recovery.
// recovery_dir` builds it from the live `PROGRAMDATA` env var, so a station
// with `%ProgramData%` relocated writes the challenge file somewhere this
// literal does not point to.
const HANDOFF_RECOVERY_CODE_FILE = 'C:\\ProgramData\\CivicCast\\setup-recovery\\code.txt'
const SUPPORT_ISSUE_URL =
  'https://github.com/scottconverse/civiccast/issues/new?template=bug-report.yml&title=%5Bbeta%5D%20'

function isServiceDegradedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503
}

function isRateLimitedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 429
}

function SupportLink() {
  return (
    <>
      See <span className="cc-mono">SUPPORT.md</span> or{' '}
      <a href={SUPPORT_ISSUE_URL} target="_blank" rel="noreferrer" className="underline underline-offset-2">
        open a support issue
      </a>
      .
    </>
  )
}

/**
 * W-2: in-product recovery for a lost or expired setup link, for the
 * clerk who is the actual first-run operator at most stations -- not just
 * someone comfortable running an installer command line. Proves the same
 * thing the setup link's nonce already proves (administrator of this
 * computer) via a disposable, single-use code an administrator reads from a
 * protected file on the station itself. On success it resumes the ordinary
 * setup flow exactly as if the setup link had worked -- see
 * `completeHandoffRecovery` in `../api/client`.
 */
function HandoffRecoveryPanel({ onRecovered }: { onRecovered: () => void }) {
  const queryClient = useQueryClient()
  const [phase, setPhase] = useState<'idle' | 'code-requested'>('idle')
  const [code, setCode] = useState('')
  const [codeFile, setCodeFile] = useState<string | null>(null)
  const [expiresAt, setExpiresAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (phase !== 'code-requested') return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  const startMutation = useMutation({
    mutationFn: startHandoffRecovery,
    onSuccess: (response) => {
      setExpiresAt(Date.now() + response.expires_in * 1000)
      setNow(Date.now())
      setCode('')
      setCodeFile(response.code_file)
      setPhase('code-requested')
    },
  })

  const completeMutation = useMutation({
    mutationFn: completeHandoffRecovery,
    onSuccess: (response) => {
      window.sessionStorage.setItem('civiccast.setupNonce', response.setup_nonce)
      setPhase('idle')
      setCode('')
      setCodeFile(null)
      setExpiresAt(null)
      void queryClient.invalidateQueries({ queryKey: ['station-setup-state'] })
      void queryClient.invalidateQueries({ queryKey: ['setup-storage-state'] })
      onRecovered()
    },
  })

  const isExpired = phase === 'code-requested' && expiresAt !== null && now >= expiresAt
  const secondsLeft = expiresAt !== null ? Math.max(0, Math.round((expiresAt - now) / 1000)) : 0

  if (phase === 'idle') {
    return (
      <div className="mt-3">
        <button
          type="button"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
          className="rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          I lost my setup link
        </button>
        {startMutation.isError && (
          <p role="alert" className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-err)' }}>
            {isServiceDegradedError(startMutation.error) ? (
              <>
                CivicCast could not prepare a recovery code right now. <SupportLink />
              </>
            ) : isRateLimitedError(startMutation.error) ? (
              apiMessage(startMutation.error, 'Too many recovery attempts. Wait before trying again.')
            ) : (
              apiMessage(startMutation.error, 'Could not start setup recovery.')
            )}
          </p>
        )}
      </div>
    )
  }

  return (
    <form
      className="mt-3 grid gap-2 rounded-md p-3"
      style={{ background: 'var(--cc-surface-3)', border: '1px solid var(--cc-line)' }}
      onSubmit={(event) => {
        event.preventDefault()
        completeMutation.mutate({ code: code.trim() })
      }}
    >
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Prove you are an administrator of this computer. On this computer, open this file:
      </p>
      <code
        className="cc-mono block overflow-x-auto rounded p-2 text-xs"
        style={{ background: 'var(--cc-surface)', color: 'var(--cc-ink)' }}
      >
        {codeFile ?? HANDOFF_RECOVERY_CODE_FILE}
      </code>
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Windows will ask for administrator permission to open it. Then type the 8-character code
        below.{' '}
        {!isExpired && (
          <>
            This code expires in {secondsLeft} second{secondsLeft === 1 ? '' : 's'}.
          </>
        )}
      </p>
      <label className="grid gap-1 text-sm" htmlFor="handoff-recovery-code">
        <span className="font-semibold">Recovery code</span>
        <input
          id="handoff-recovery-code"
          value={code}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          disabled={isExpired}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={completeMutation.isError ? true : undefined}
          aria-describedby={completeMutation.isError ? 'handoff-recovery-code-error' : undefined}
          className="cc-mono rounded-md px-3 py-2"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
        />
      </label>
      {isExpired ? (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          This code has expired. Request a new one below.
        </div>
      ) : (
        <button
          type="submit"
          disabled={completeMutation.isPending || code.trim().length === 0}
          className="rounded-md px-3 py-2 text-sm font-semibold"
          style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
        >
          Continue
        </button>
      )}
      <button
        type="button"
        onClick={() => startMutation.mutate()}
        disabled={startMutation.isPending}
        className="justify-self-start text-xs font-semibold underline underline-offset-2"
        style={{ color: 'var(--cc-brand)' }}
      >
        Get a new code
      </button>
      {completeMutation.isError && (
        <div
          id="handoff-recovery-code-error"
          role="alert"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
        >
          {isServiceDegradedError(completeMutation.error) ? (
            <>
              CivicCast verified your administrator code, but this station has no setup link
              configured. <SupportLink />
            </>
          ) : (
            'That code did not work. It may be mistyped or expired -- check the file again, or get a new code above.'
          )}
        </div>
      )}
      {startMutation.isError && (
        <div role="alert" className="rounded-md p-2 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {isRateLimitedError(startMutation.error)
            ? apiMessage(startMutation.error, 'Too many recovery attempts. Wait before trying again.')
            : apiMessage(startMutation.error, 'Could not prepare a new code.')}
        </div>
      )}
    </form>
  )
}

export function SetupScreen({ onAuthenticated }: { onAuthenticated?: () => void }) {
  const queryClient = useQueryClient()
  const stationNameRef = useRef<HTMLInputElement | null>(null)
  const [form, setForm] = useState<FirstAdminSetupRequest>(INITIAL_FORM)
  const [confirmPassword, setConfirmPassword] = useState('')
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const markTouched = (key: string) => setTouched((current) => ({ ...current, [key]: true }))
  const [loginForm, setLoginForm] = useState<StationLoginRequest>(INITIAL_LOGIN)
  const [recoveryForm, setRecoveryForm] = useState<StationRecoveryRequest>(INITIAL_RECOVERY)
  const [completed, setCompleted] = useState<FirstAdminSetupResponse | null>(null)
  const [authenticated, setAuthenticated] = useState<StationAuthResponse | null>(null)

  const stateQuery = useQuery({
    queryKey: ['station-setup-state'],
    queryFn: getStationSetupState,
    retry: false,
  })
  const storageQuery = useQuery({
    queryKey: ['setup-storage-state'],
    queryFn: getPublicStorageState,
    retry: false,
  })
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canManageProviders =
    !staffIdentityQuery.isSuccess ||
    hasOperatorRole(staffIdentityQuery.data, 'setup_admin')
  const storageMutation = useMutation({
    mutationFn: preparePublicStorage,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['setup-storage-state'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const mutation = useMutation({
    mutationFn: completePublicFirstAdminSetup,
    onSuccess: (response) => {
      window.localStorage.setItem('civiccast.staffToken', response.operator_console_token)
      window.sessionStorage.setItem('civiccast.staffToken', response.operator_console_token)
      setCompleted(response)
      void queryClient.resetQueries({ queryKey: ['staff-identity'] })
      void queryClient.invalidateQueries({ queryKey: ['station-setup-state'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
    },
  })
  const loginMutation = useMutation({
    mutationFn: loginStationAdmin,
    onSuccess: (response) => {
      window.localStorage.setItem('civiccast.staffToken', response.operator_console_token)
      window.sessionStorage.setItem('civiccast.staffToken', response.operator_console_token)
      setAuthenticated(response)
      void queryClient.resetQueries({ queryKey: ['staff-identity'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      onAuthenticated?.()
    },
  })
  const recoveryMutation = useMutation({
    mutationFn: recoverStationAdmin,
    onSuccess: (response) => {
      window.localStorage.setItem('civiccast.staffToken', response.operator_console_token)
      window.sessionStorage.setItem('civiccast.staffToken', response.operator_console_token)
      setAuthenticated(response)
      setRecoveryForm(INITIAL_RECOVERY)
      void queryClient.resetQueries({ queryKey: ['staff-identity'] })
      void queryClient.invalidateQueries({ queryKey: ['system-health'] })
      onAuthenticated?.()
    },
  })
  const [kitAcknowledged, setKitAcknowledged] = useState(false)
  const ackMutation = useMutation({
    mutationFn: acknowledgeRecoveryKit,
    onSuccess: () => {
      setKitAcknowledged(true)
      void queryClient.invalidateQueries({ queryKey: ['station-setup-state'] })
    },
  })

  const storageReady = storageQuery.data?.status === 'ready'
  const recoveryKitAcknowledged = kitAcknowledged || stateQuery.data?.recovery_kit_acknowledged === true
  const kitGateActive = Boolean(completed) && !recoveryKitAcknowledged
  const showAdminTools =
    Boolean(stateQuery.data?.setup_complete || completed || authenticated) && !kitGateActive

  useEffect(() => {
    if (!kitGateActive) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [kitGateActive])

  useEffect(() => {
    if (!stateQuery.data?.setup_complete && storageReady) {
      stationNameRef.current?.focus()
    }
  }, [stateQuery.data?.setup_complete, storageReady])

  const update = (key: keyof FirstAdminSetupRequest, value: string) => {
    setForm((current) => ({
      ...current,
      [key]: key === 'public_base_url' && value.trim() === '' ? null : value,
    }))
  }

  const passwordsMismatch = form.admin_password !== confirmPassword

  const disabled =
    mutation.isPending ||
    form.station_name.trim() === '' ||
    form.admin_display_name.trim() === '' ||
    form.admin_username.trim() === '' ||
    form.admin_password.length < 12 ||
    passwordsMismatch ||
    form.recovery_kit_destination.trim() === ''

  return (
    <div className="grid gap-5 px-6 py-5">
      <header className="max-w-3xl">
        <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--cc-ink-3)' }}>
          Setup
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">First setup</h1>
        <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Create the station identity, first local admin, and recovery kit before a public meeting.
        </p>
      </header>

      {stateQuery.isLoading && (
        <div className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-surface-2)' }}>
          Checking setup state...
        </div>
      )}

      {stateQuery.error && (
        <div role="alert" className="rounded-md p-4 text-sm" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          Could not read setup state. {apiMessage(stateQuery.error, 'Try again.')}
        </div>
      )}

      {stateQuery.error && isSetupHandoffError(stateQuery.error) && (
        <section
          className="rounded-md p-4 text-sm"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          <h2 className="m-0 text-base font-semibold">Restore the setup handoff the Windows installer creates</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            The first setup page needs the one-time operator handoff created by the Windows
            installer, and this page was opened without it. Nothing is wrong with the station, and{' '}
            <strong>simply reopening CivicCast will not fix it</strong> &mdash; an ordinary launch
            cannot read the protected value that the handoff is built from.
          </p>
          <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            On the station itself, run CivicCast once with the recovery switch and approve the
            Windows administrator prompt:
          </p>
          <code
            className="mt-2 block overflow-x-auto rounded p-2 text-xs"
            style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink)' }}
          >
            &quot;C:\Program Files\CivicCast (Native)\CivicCast Native.exe&quot;
            --civiccast-restore-setup-handoff
          </code>
          <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            It restores the handoff for the Windows account that runs it, then{' '}
            <strong>Open operator console</strong> works normally. You must be an administrator of
            that computer; the command refuses rather than revealing anything if you are not.
          </p>
          <p className="m-0 mt-3 text-xs font-semibold" style={{ color: 'var(--cc-ink) ' }}>
            Or, without a command line:
          </p>
          <HandoffRecoveryPanel onRecovered={() => void stateQuery.refetch()} />
        </section>
      )}

      {!stateQuery.error && !stateQuery.data?.setup_complete && (
        <StorageSetupPanel
          storage={storageQuery.data}
          error={storageQuery.error ?? storageMutation.error}
          isLoading={storageQuery.isLoading}
          isPreparing={storageMutation.isPending}
          onPrepare={() => storageMutation.mutate()}
        />
      )}

      {stateQuery.data?.setup_complete && !completed && (
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          {stateQuery.data.recovery_kit_acknowledged === false && (
            <section
              role="alert"
              className="rounded-md p-4 lg:col-span-2"
              style={{
                background: 'var(--cc-warn-soft, var(--cc-err-soft))',
                border: '1px solid var(--cc-warn, var(--cc-err))',
              }}
            >
              <h2 className="m-0 text-base font-semibold">Recovery kit never confirmed</h2>
              <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
                CivicCast has no record that this station&apos;s recovery codes were saved or
                printed. They were shown once during setup and cannot be shown again. Find the
                saved or printed kit now — without those codes, a lost admin password locks this
                station out permanently.
              </p>
              <button
                type="button"
                disabled={ackMutation.isPending}
                onClick={() => ackMutation.mutate()}
                className="mt-3 rounded-md px-3 py-2 text-sm font-semibold"
                style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
              >
                I found the kit — it is stored safely
              </button>
            </section>
          )}
          <section
            className="rounded-md p-4 lg:col-span-2"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            <h2 className="m-0 text-base font-semibold">Setup complete</h2>
            <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
              {stateQuery.data.profile?.station_name ?? 'This station'} already has a first admin and recovery kit.
            </p>
            <p className="m-0 mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Sign in with the local admin password if this browser lost its console token.
            </p>
          </section>
          <CommissioningDefaultsPanel profile={stateQuery.data.profile} className="lg:col-span-2" />

          <form
            className="grid gap-3 rounded-md p-4"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            onSubmit={(event) => {
              event.preventDefault()
              loginMutation.mutate(loginForm)
            }}
          >
            <div>
              <h2 className="m-0 text-base font-semibold">Admin sign-in</h2>
              <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Creates a fresh console token for this browser.
              </p>
            </div>
            <label className="grid gap-1 text-sm" htmlFor="login-admin-username">
              <span className="font-semibold">Admin username</span>
              <input
                id="login-admin-username"
                value={loginForm.admin_username}
                onChange={(event) => setLoginForm((current) => ({ ...current, admin_username: event.target.value }))}
                className="rounded-md px-3 py-2"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            <label className="grid gap-1 text-sm" htmlFor="login-admin-password">
              <span className="font-semibold">Admin password</span>
              <input
                id="login-admin-password"
                type="password"
                value={loginForm.admin_password}
                onChange={(event) => setLoginForm((current) => ({ ...current, admin_password: event.target.value }))}
                className="rounded-md px-3 py-2"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            <button
              type="submit"
              disabled={loginMutation.isPending || loginForm.admin_username.trim() === '' || loginForm.admin_password === ''}
              className="rounded-md px-4 py-2 text-sm font-semibold"
              style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
            >
              Sign in
            </button>
            {loginMutation.error && (
              <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
                {apiMessage(loginMutation.error, 'Sign-in failed.')}
              </div>
            )}
          </form>

          <form
            className="grid gap-3 rounded-md p-4"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            onSubmit={(event) => {
              event.preventDefault()
              recoveryMutation.mutate(recoveryForm)
            }}
          >
            <div>
              <h2 className="m-0 text-base font-semibold">Use recovery code</h2>
              <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Consumes one printed code and sets a new admin password.
              </p>
            </div>
            <label className="grid gap-1 text-sm" htmlFor="recover-admin-username">
              <span className="font-semibold">Admin username</span>
              <input
                id="recover-admin-username"
                value={recoveryForm.admin_username}
                onChange={(event) => setRecoveryForm((current) => ({ ...current, admin_username: event.target.value }))}
                className="rounded-md px-3 py-2"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            <label className="grid gap-1 text-sm" htmlFor="recover-code">
              <span className="font-semibold">Recovery code</span>
              <input
                id="recover-code"
                value={recoveryForm.recovery_code}
                onChange={(event) => setRecoveryForm((current) => ({ ...current, recovery_code: event.target.value }))}
                className="cc-mono rounded-md px-3 py-2"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            <label className="grid gap-1 text-sm" htmlFor="recover-new-password">
              <span className="font-semibold">New admin password</span>
              <input
                id="recover-new-password"
                type="password"
                value={recoveryForm.new_admin_password}
                onChange={(event) => setRecoveryForm((current) => ({ ...current, new_admin_password: event.target.value }))}
                className="rounded-md px-3 py-2"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
              />
            </label>
            <button
              type="submit"
              disabled={
                recoveryMutation.isPending ||
                recoveryForm.admin_username.trim() === '' ||
                recoveryForm.recovery_code.trim() === '' ||
                recoveryForm.new_admin_password.length < 12
              }
              className="rounded-md px-4 py-2 text-sm font-semibold"
              style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
            >
              Recover account
            </button>
            {recoveryMutation.error && (
              <AuthRequiredState error={recoveryMutation.error} context="recovery authority" />
            )}
          </form>
        </div>
      )}

      {!stateQuery.error && !stateQuery.data?.setup_complete && !storageReady && (
        <section
          className="rounded-md p-4 text-sm"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          <h2 className="m-0 text-base font-semibold">Create the first admin after storage is ready</h2>
          <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
            CivicCast will show the station setup form as soon as the local database is prepared.
          </p>
        </section>
      )}

      {!stateQuery.error && !stateQuery.data?.setup_complete && storageReady && (
        <form
          className="grid gap-4 rounded-md p-4 lg:grid-cols-2"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate(form)
          }}
        >
          <Field
            id="station_name"
            label="Station name"
            help="The name residents will recognize."
            value={form.station_name}
            onChange={(value) => update('station_name', value)}
            onBlur={() => markTouched('station_name')}
            error={touched.station_name && form.station_name.trim() === '' ? 'Station name is required.' : undefined}
            inputRef={stationNameRef}
          />
          <Field
            id="admin_display_name"
            label="Admin display name"
            help="The person responsible for setup and recovery."
            value={form.admin_display_name}
            onChange={(value) => update('admin_display_name', value)}
            onBlur={() => markTouched('admin_display_name')}
            error={
              touched.admin_display_name && form.admin_display_name.trim() === ''
                ? 'Admin display name is required.'
                : undefined
            }
          />
          <Field
            id="admin_username"
            label="Admin username"
            help="A local sign-in name for the first admin."
            value={form.admin_username}
            onChange={(value) => update('admin_username', value)}
            onBlur={() => markTouched('admin_username')}
            error={touched.admin_username && form.admin_username.trim() === '' ? 'Admin username is required.' : undefined}
          />
          <Field
            id="admin_password"
            label="Admin password"
            help={`Use at least 12 characters (${form.admin_password.length}/12).`}
            value={form.admin_password}
            secret
            onChange={(value) => update('admin_password', value)}
            onBlur={() => markTouched('admin_password')}
            error={
              touched.admin_password && form.admin_password.length < 12
                ? `Needs at least 12 characters (${form.admin_password.length}/12 so far).`
                : undefined
            }
          />
          <Field
            id="confirm_password"
            label="Confirm admin password"
            help="Retype the password above to confirm it."
            value={confirmPassword}
            secret
            onChange={setConfirmPassword}
            onBlur={() => markTouched('confirm_password')}
            error={touched.confirm_password && passwordsMismatch ? 'Passwords do not match.' : undefined}
          />
          <Field
            id="recovery_kit_destination"
            label="Where will you keep the recovery kit?"
            help="A note for your records (e.g. 'printed, stored in the clerk safe') — not a file path. After you submit, you'll get one chance to save or print the recovery kit."
            value={form.recovery_kit_destination}
            onChange={(value) => update('recovery_kit_destination', value)}
            onBlur={() => markTouched('recovery_kit_destination')}
            error={
              touched.recovery_kit_destination && form.recovery_kit_destination.trim() === ''
                ? 'Tell us where the recovery kit will be kept.'
                : undefined
            }
          />
          <Field
            id="public_base_url"
            label="Resident portal URL"
            help="Optional for local rehearsal; set before public launch."
            value={form.public_base_url ?? ''}
            onChange={(value) => update('public_base_url', value)}
          />
          <div className="lg:col-span-2">
            <button
              type="submit"
              disabled={disabled}
              className="rounded-md px-4 py-2 text-sm font-semibold"
              style={{
                background: disabled ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
                color: disabled ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
              }}
            >
              Create first admin
            </button>
          </div>
          {mutation.error && (
            <div role="alert" className="lg:col-span-2 rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
              {apiMessage(mutation.error, 'First setup failed.')}
            </div>
          )}
        </form>
      )}

      {completed && kitGateActive && (
        <RecoveryKitPanel
          setup={completed}
          onAcknowledge={() => ackMutation.mutate()}
          ackPending={ackMutation.isPending}
          ackError={ackMutation.error}
        />
      )}
      {completed && !kitGateActive && <SignedInPanel auth={{ status: 'complete', profile: completed.profile }} />}
      {authenticated && !kitGateActive && <SignedInPanel auth={authenticated} />}
      {showAdminTools && <StationAdminTools canManageProviders={canManageProviders} />}
    </div>
  )
}

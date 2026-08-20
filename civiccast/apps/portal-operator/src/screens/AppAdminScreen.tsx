import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createAppBuild,
  downloadAppBuild,
  getAppPlatformConfig,
  getStaffIdentity,
  listAppBuilds,
  listStoreSubmissions,
  updateStoreSubmission,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import type {
  AppBuildRecord,
  BuildRequest,
  StoreSubmissionMetadata,
  StoreSubmissionUpdate,
} from '../types/api.generated'
import {
  APP_TARGETS,
  BUILD_TIERS,
  SUBMISSION_STATUSES,
  formatBuiltAt,
  humanize,
  shortSha,
  submissionSummary,
} from './app-admin-format'

const POLL_MS = 30_000

const panelStyle = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }
const insetStyle = { background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }
const fieldStyle = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

function apiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail ?? fallback
  if (error instanceof Error) return error.message
  return fallback
}

function AccessNote() {
  return (
    <div className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}>
      Viewing and managing OTT app builds requires the setup admin or publish operator role.
    </div>
  )
}

// --- New build --------------------------------------------------------------

export function NewBuildForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean
  onSubmit: (payload: BuildRequest) => void
}) {
  const [appTarget, setAppTarget] = useState<BuildRequest['app_target']>('web_pwa')
  const [tier, setTier] = useState<'unbranded' | 'branded'>('unbranded')
  return (
    <div className="grid gap-2 rounded-md p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" style={insetStyle}>
      <label className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Platform target</span>
        <select aria-label="Platform target" value={appTarget} onChange={(e) => setAppTarget(e.target.value as BuildRequest['app_target'])} className="rounded-md px-2 py-1.5" style={fieldStyle}>
          {APP_TARGETS.map((t) => (
            <option key={t} value={t}>
              {humanize(t)}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Tier</span>
        <select aria-label="Tier" value={tier} onChange={(e) => setTier(e.target.value as 'unbranded' | 'branded')} className="rounded-md px-2 py-1.5" style={fieldStyle}>
          {BUILD_TIERS.map((t) => (
            <option key={t} value={t}>
              {humanize(t)}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={submitting}
        onClick={() => onSubmit({ app_target: appTarget, build_tier: tier })}
        className="rounded-md px-3 py-1.5 text-xs font-semibold"
        style={{
          background: submitting ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
          color: submitting ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
        }}
      >
        {submitting ? 'Building…' : 'Queue build'}
      </button>
    </div>
  )
}

// --- Store submission row ---------------------------------------------------

export function StoreSubmissionRow({
  submission,
  saving,
  canWrite,
  onSave,
}: {
  submission: StoreSubmissionMetadata
  saving: boolean
  canWrite: boolean
  onSave: (appTarget: string, payload: StoreSubmissionUpdate) => void
}) {
  const [status, setStatus] = useState(submission.submission_status)
  const [packageId, setPackageId] = useState(submission.package_id ?? '')
  const [publishedUrl, setPublishedUrl] = useState(submission.published_url ?? '')
  const [versionName, setVersionName] = useState(submission.version_name ?? '')
  return (
    <div className="grid gap-2 rounded-md p-3 text-sm" style={insetStyle}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{humanize(submission.app_target)}</span>
        <span className="cc-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
          {submissionSummary(submission)}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Status</span>
          <select aria-label={`${submission.app_target} status`} value={status} disabled={!canWrite} onChange={(e) => setStatus(e.target.value as StoreSubmissionMetadata['submission_status'])} className="rounded-md px-2 py-1.5" style={fieldStyle}>
            {SUBMISSION_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Version name</span>
          <input aria-label={`${submission.app_target} version`} value={versionName} readOnly={!canWrite} onChange={(e) => setVersionName(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Package ID</span>
          <input aria-label={`${submission.app_target} package`} value={packageId} readOnly={!canWrite} onChange={(e) => setPackageId(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Published URL</span>
          <input aria-label={`${submission.app_target} url`} value={publishedUrl} readOnly={!canWrite} onChange={(e) => setPublishedUrl(e.target.value)} className="rounded-md px-2 py-1.5" style={fieldStyle} />
        </label>
      </div>
      {canWrite && (
        <div>
          <button
            type="button"
            disabled={saving}
            onClick={() =>
              onSave(submission.app_target, {
                submission_status: status,
                package_id: packageId.trim() || null,
                published_url: publishedUrl.trim() || null,
                // version_name is non-nullable on the record, so only send it
                // when set — omitting it preserves the stored value.
                ...(versionName.trim() ? { version_name: versionName.trim() } : {}),
              })
            }
            className="rounded-md px-2.5 py-1 text-[11px] font-semibold"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  )
}

// --- Container --------------------------------------------------------------

export function AppAdminScreen() {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)

  const identityQuery = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity, retry: false })
  const canQueue = identityQuery.isSuccess && hasOperatorRole(identityQuery.data, 'setup_admin')
  const canWrite =
    canQueue || (identityQuery.isSuccess && hasOperatorRole(identityQuery.data, 'publish_operator'))
  const canRead = canWrite

  const configQuery = useQuery({ queryKey: ['app-platform-config'], queryFn: getAppPlatformConfig, refetchInterval: POLL_MS, enabled: canRead })
  const buildsQuery = useQuery({ queryKey: ['app-builds'], queryFn: () => listAppBuilds(), refetchInterval: POLL_MS, enabled: canRead, retry: false })
  const submissionsQuery = useQuery({ queryKey: ['store-submissions'], queryFn: listStoreSubmissions, refetchInterval: POLL_MS, enabled: canRead, retry: false })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['app-builds'] })
    void queryClient.invalidateQueries({ queryKey: ['store-submissions'] })
  }

  const buildMutation = useMutation({
    mutationFn: (payload: BuildRequest) => createAppBuild(payload),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (err) => setActionError(apiMessage(err, 'Could not queue the build.')),
  })
  const submissionMutation = useMutation({
    mutationFn: ({ appTarget, payload }: { appTarget: string; payload: StoreSubmissionUpdate }) =>
      updateStoreSubmission(appTarget, payload),
    onSuccess: () => {
      setActionError(null)
      refresh()
    },
    onError: (err) => setActionError(apiMessage(err, 'Could not update the submission.')),
  })

  const handleDownload = async (record: AppBuildRecord) => {
    try {
      const blob = await downloadAppBuild(record.record_id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${record.app_target}-${record.record_id}.zip`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setActionError(apiMessage(err, 'Could not download the artifact.'))
    }
  }

  const profile = configQuery.data?.build_profile
  const builds = buildsQuery.data ?? []
  const submissions = submissionsQuery.data ?? []

  return (
    <div className="grid min-w-0 gap-5 overflow-x-hidden px-4 py-5 sm:px-6">
      <header>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">App Admin</h1>
        <p className="m-0 mt-1 max-w-3xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Build the OTT app shells for each platform and track their store submissions. Apps read the
          station config at runtime — branding + content update without a rebuild.
        </p>
      </header>

      {!identityQuery.isSuccess && !identityQuery.isError && (
        <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
      )}
      {identityQuery.isError && (
        <div role="alert" className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          Could not verify your access — {apiMessage(identityQuery.error, 'identity check failed')}.
        </div>
      )}
      {!canRead && identityQuery.isSuccess && <AccessNote />}
      {actionError && (
        <div role="alert" className="rounded-md p-3 text-sm" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {actionError}
        </div>
      )}

      {canRead && (
        <>
          {/* Build profile (read-only; edit via Channel & Settings) */}
          <section className="rounded-md p-4" style={panelStyle} aria-label="Build profile">
            <h2 className="m-0 text-base font-semibold">Build profile</h2>
            {profile ? (
              <div className="mt-2 grid gap-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
                <div>App name: <strong>{profile.app_name}</strong></div>
                <div>Tier: {humanize(profile.tier)}</div>
                <div>Store-ready: {profile.store_ready ? 'yes' : 'no'}</div>
                {profile.icon_url && <div className="cc-mono break-all text-[11px]">icon: {profile.icon_url}</div>}
              </div>
            ) : (
              <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
            )}
          </section>

          {/* New build */}
          <section className="rounded-md p-4" style={panelStyle} aria-label="New build">
            <h2 className="m-0 text-base font-semibold">New build</h2>
            {canQueue ? (
              <div className="mt-3">
                <NewBuildForm submitting={buildMutation.isPending} onSubmit={(p) => buildMutation.mutate(p)} />
              </div>
            ) : (
              <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
                Queueing a build requires the setup admin role.
              </div>
            )}
          </section>

          {/* Build history */}
          <section className="rounded-md p-4" style={panelStyle} aria-label="Build history">
            <h2 className="m-0 text-base font-semibold">Build history</h2>
            <div className="mt-3 grid gap-2">
              {buildsQuery.isError && (
                <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
                  Could not load builds — {apiMessage(buildsQuery.error, 'request failed')}.
                </div>
              )}
              {!buildsQuery.isError && builds.length === 0 && (
                <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No builds yet.</div>
              )}
              {builds.map((record) => (
                <div key={record.record_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md p-3 text-sm" style={insetStyle}>
                  <div className="min-w-0">
                    <div className="font-semibold">{humanize(record.app_target)} · {humanize(record.build_tier)}</div>
                    <div className="cc-mono text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
                      {formatBuiltAt(record.built_at)} · sha {shortSha(record.artifact_sha256)} · {record.built_by}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleDownload(record)}
                    className="rounded-md px-2.5 py-1 text-[11px] font-medium"
                    style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-ink-2)', background: 'var(--cc-surface)' }}
                  >
                    Download
                  </button>
                </div>
              ))}
            </div>
          </section>

          {/* Store submissions */}
          <section className="rounded-md p-4" style={panelStyle} aria-label="Store submissions">
            <h2 className="m-0 text-base font-semibold">Store submissions</h2>
            <p className="m-0 mt-1 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
              CivicCast makes no calls to app stores — record submission status here after submitting offline.
            </p>
            <div className="mt-3 grid gap-2">
              {submissionsQuery.isError && (
                <div role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
                  Could not load submissions — {apiMessage(submissionsQuery.error, 'request failed')}.
                </div>
              )}
              {!submissionsQuery.isError && submissions.length === 0 && (
                <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>No submissions tracked yet.</div>
              )}
              {submissions.map((submission) => (
                <StoreSubmissionRow
                  key={submission.app_target}
                  submission={submission}
                  saving={submissionMutation.isPending}
                  canWrite={canWrite}
                  onSave={(appTarget, payload) => submissionMutation.mutate({ appTarget, payload })}
                />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}

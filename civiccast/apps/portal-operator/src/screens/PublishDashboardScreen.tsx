import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  approvePublishAsset,
  getStaffIdentity,
  listPublishAssets,
  retryPublishSurface,
} from '../api/client'
import { hasOperatorRole } from '../auth/roles'
import { ConfirmDialog } from '../components/ConfirmDialog'
import type {
  PublishApprovalRequest,
  PublishAssetStatus,
  PublishDashboardState,
  PublishSurfaceStatus,
} from '../types/publish'
import { stateLabel } from './status-language'

const FILTERS: ReadonlyArray<{
  id: 'all' | PublishDashboardState
  label: string
}> = [
  { id: 'all', label: 'All' },
  { id: 'failed_needs_action', label: stateLabel('failed_needs_action') },
  { id: 'draft', label: stateLabel('draft') },
  { id: 'archive_pending', label: stateLabel('archive_pending') },
  { id: 'archive_verified', label: stateLabel('archive_verified') },
  { id: 'reach_degraded', label: stateLabel('reach_degraded') },
  { id: 'complete', label: stateLabel('complete') },
]

const STATE_TONE: Record<PublishDashboardState, { bg: string; fg: string }> = {
  draft: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
  preflight_blocked: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  publishing: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
  portal_live: { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)' },
  reach_degraded: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  archive_pending: { bg: 'var(--cc-warn-soft)', fg: 'var(--cc-ink)' },
  archive_verified: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  complete: { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)' },
  failed_needs_action: { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)' },
}

function fmtDate(iso: string | null): string {
  if (iso == null) return 'Not public yet'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function StatePill({ asset }: { asset: PublishAssetStatus }) {
  const tone = STATE_TONE[asset.dashboard_state]
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {stateLabel(asset.dashboard_state)}
    </span>
  )
}

function SurfaceDot({ surface }: { surface: PublishSurfaceStatus }) {
  const tone =
    surface.state === 'succeeded' || surface.state === 'overridden'
      ? { bg: 'var(--cc-ok-soft)', fg: 'var(--cc-ink)', symbol: 'OK' }
      : surface.state === 'failed' || surface.state === 'blocked'
        ? { bg: 'var(--cc-err-soft)', fg: 'var(--cc-ink)', symbol: '!' }
        : surface.state === 'running' || surface.state === 'pending'
          ? { bg: 'var(--cc-info-soft)', fg: 'var(--cc-ink)', symbol: '...' }
          : { bg: 'var(--cc-surface-3)', fg: 'var(--cc-ink-3)', symbol: '-' }

  return (
    <span
      aria-hidden="true"
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.symbol}
    </span>
  )
}

interface SurfaceRowProps {
  surface: PublishSurfaceStatus
  checked: boolean
  overrideChecked: boolean
  overrideText: string
  disabled: boolean
  canPublish: boolean
  onToggleSurface: (surfaceId: string, checked: boolean) => void
  onToggleOverride: (surfaceId: string, checked: boolean) => void
  onOverrideText: (surfaceId: string, value: string) => void
  onRetrySurface: (surfaceId: string) => void
}

function SurfaceRow({
  surface,
  checked,
  overrideChecked,
  overrideText,
  disabled,
  canPublish,
  onToggleSurface,
  onToggleOverride,
  onOverrideText,
  onRetrySurface,
}: SurfaceRowProps) {
  const canApprove =
    surface.state === 'pending' ||
    surface.state === 'failed' ||
    surface.state === 'blocked'
  const canOverride = surface.required && surface.kind === 'archive' && canApprove
  return (
    <div
      className="grid gap-3 rounded-md p-3 sm:grid-cols-[1fr_1.5fr]"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex min-w-0 items-start gap-2">
        <SurfaceDot surface={surface} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{surface.label}</span>
            {surface.required && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
              >
                Required
              </span>
            )}
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
            >
              {surface.approval}
            </span>
          </div>
          <div className="cc-mono mt-0.5 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
            {surface.kind} / {stateLabel(surface.state)}
          </div>
          {/* GauntletGate TW-1: a surface completed by a simulated provider used
              to render an ordinary-looking archive.org URL, so a clerk could
              approve it and believe the meeting was legally archived when
              nothing was written. Say so before showing the target. */}
          {surface.simulated && (
            <div
              role="note"
              className="mt-2 rounded-md px-2 py-1.5 text-[11px] font-semibold"
              style={{ background: 'var(--cc-warn-soft)', color: 'var(--cc-ink)', border: '1px solid var(--cc-warn)' }}
            >
              Simulated — nothing was actually archived. This is not the legal
              archive copy. Ask an admin to enable the real provider.
            </div>
          )}
          {(surface.url || surface.path || surface.verification_hash) && (
            <div className="cc-mono mt-2 grid gap-1 text-[10px]" style={{ color: 'var(--cc-ink-3)' }}>
              {surface.url && (
                <div>
                  {surface.simulated ? 'Simulated target: ' : 'URL: '}
                  {surface.url}
                </div>
              )}
              {surface.path && (
                <div>
                  {surface.simulated ? 'Simulated path: ' : 'Path: '}
                  {surface.path}
                </div>
              )}
              {surface.verification_hash && <div>Hash: {surface.verification_hash}</div>}
            </div>
          )}
        </div>
      </div>
      <div className="grid gap-2 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <div>{surface.message}</div>
        <div>
          <strong style={{ color: 'var(--cc-ink)' }}>Next step.</strong>{' '}
          {surface.next_step}
        </div>
        {canApprove && (
          <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--cc-ink)' }}>
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled || overrideChecked || !canPublish}
              onChange={(event) => onToggleSurface(surface.id, event.currentTarget.checked)}
            />
            Approve this surface
          </label>
        )}
        {canOverride && (
          <div className="grid gap-2">
            <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--cc-ink)' }}>
              <input
                type="checkbox"
                checked={overrideChecked}
                disabled={disabled || !canPublish}
                onChange={(event) => onToggleOverride(surface.id, event.currentTarget.checked)}
              />
              Use audit-logged archive override for this platform
            </label>
            {overrideChecked && (
              <textarea
                aria-label={`Override justification for ${surface.label}`}
                className="min-h-20 rounded-md px-3 py-2 text-xs"
                style={{
                  background: 'var(--cc-surface)',
                  border: '1px solid var(--cc-line)',
                  color: 'var(--cc-ink)',
                }}
                value={overrideText}
                disabled={disabled || !canPublish}
                onChange={(event) => onOverrideText(surface.id, event.currentTarget.value)}
                placeholder={`Explain why ${surface.label} is being overridden and where the approval is recorded.`}
              />
            )}
          </div>
        )}
        {surface.state === 'failed' && (
          <button
            type="button"
            disabled={disabled || !canPublish}
            onClick={() => onRetrySurface(surface.id)}
            className="w-fit rounded-md px-3 py-1.5 text-xs font-semibold"
            style={{
              background: 'var(--cc-ink)',
              color: 'var(--cc-ink-inv)',
              border: '1px solid var(--cc-line)',
            }}
          >
            Retry this surface
          </button>
        )}
      </div>
    </div>
  )
}

interface AssetPanelProps {
  asset: PublishAssetStatus
  isApproving: boolean
  canPublish: boolean
  error: Error | null
  onApprove: (assetId: string, payload: PublishApprovalRequest) => void
  onRetrySurface: (assetId: string, surfaceId: string) => void
}

function AssetPanel({
  asset,
  isApproving,
  canPublish,
  error,
  onApprove,
  onRetrySurface,
}: AssetPanelProps) {
  const approvableSurfaceIds = useMemo(
    () =>
      asset.surfaces
        .filter((surface) =>
          ['pending', 'failed', 'blocked'].includes(surface.state),
        )
        .map((surface) => surface.id),
    [asset.surfaces],
  )
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(approvableSurfaceIds),
  )
  const [overrideIds, setOverrideIds] = useState<Set<string>>(() => new Set())
  // Publishing is resident-facing and immediate — the button stages this
  // confirmation before the approval request is sent.
  const [confirmingPublish, setConfirmingPublish] = useState(false)
  const [overrideText, setOverrideText] = useState<Record<string, string>>({})
  const currentSurfaceIds = useMemo(
    () => new Set(approvableSurfaceIds),
    [approvableSurfaceIds],
  )
  const activeSelected = useMemo(
    () =>
      new Set(
        Array.from(selected).filter((surfaceId) => currentSurfaceIds.has(surfaceId)),
      ),
    [currentSurfaceIds, selected],
  )
  const activeOverrideIds = useMemo(
    () =>
      new Set(
        Array.from(overrideIds).filter((surfaceId) =>
          currentSurfaceIds.has(surfaceId),
        ),
      ),
    [currentSurfaceIds, overrideIds],
  )

  const overrides = Array.from(activeOverrideIds).map((surfaceId) => ({
    surface_id: surfaceId,
    justification: overrideText[surfaceId]?.trim() ?? '',
  }))
  const overrideMissingJustification = overrides.some(
    (override) => override.justification.length < 20,
  )
  const approvedSurfaceIds = Array.from(activeSelected).filter(
    (surfaceId) =>
      approvableSurfaceIds.includes(surfaceId) && !activeOverrideIds.has(surfaceId),
  )
  const blockedSelectedSurface = asset.surfaces.find(
    (surface) =>
      surface.state === 'blocked' &&
      activeSelected.has(surface.id) &&
      !activeOverrideIds.has(surface.id),
  )
  const canSubmit =
    approvableSurfaceIds.length > 0 &&
    canPublish &&
    !isApproving &&
    (approvedSurfaceIds.length > 0 || overrides.length > 0) &&
    !overrideMissingJustification &&
    blockedSelectedSurface == null
  const errorDetail =
    error instanceof ApiError && error.detail ? error.detail : error?.message

  function setSurfaceChecked(surfaceId: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(
        Array.from(current).filter((candidate) => currentSurfaceIds.has(candidate)),
      )
      if (checked) next.add(surfaceId)
      else next.delete(surfaceId)
      return next
    })
  }

  function setOverrideChecked(surfaceId: string, checked: boolean) {
    setOverrideIds((current) => {
      const next = new Set(
        Array.from(current).filter((candidate) => currentSurfaceIds.has(candidate)),
      )
      if (checked) {
        next.add(surfaceId)
        setSurfaceChecked(surfaceId, false)
      } else {
        next.delete(surfaceId)
        setSurfaceChecked(surfaceId, true)
      }
      return next
    })
  }

  function submitApproval() {
    onApprove(asset.asset_id, {
      operator_id: 'operator-dashboard',
      operator_display_name: 'Operator dashboard',
      approved_surface_ids: approvedSurfaceIds,
      overrides,
    })
  }

  return (
    <article
      className="rounded-md p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="m-0 text-base font-semibold">{asset.title}</h2>
          <div className="cc-mono mt-0.5 text-[11px]" style={{ color: 'var(--cc-ink-3)' }}>
            {asset.asset_id}
          </div>
        </div>
        <StatePill asset={asset} />
      </div>
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3" style={{ color: 'var(--cc-ink-2)' }}>
        <div>
          <div className="font-semibold" style={{ color: 'var(--cc-ink)' }}>
            Canonical
          </div>
          {asset.canonical_public ? 'Portal public' : 'Portal pending'}
        </div>
        <div>
          <div className="font-semibold" style={{ color: 'var(--cc-ink)' }}>
            Archive
          </div>
          {asset.archive_verified
            ? 'IA and local NAS verified'
            : asset.public_record_required
              ? 'IA and local NAS required'
              : 'Not required'}
        </div>
        <div>
          <div className="font-semibold" style={{ color: 'var(--cc-ink)' }}>
            Published
          </div>
          {fmtDate(asset.published_at)}
        </div>
      </div>
      <div className="mt-4 grid gap-2">
        {asset.surfaces.map((surface) => (
          <SurfaceRow
            key={surface.id}
            surface={surface}
            checked={activeSelected.has(surface.id)}
            overrideChecked={activeOverrideIds.has(surface.id)}
            overrideText={overrideText[surface.id] ?? ''}
            disabled={isApproving}
            canPublish={canPublish}
            onToggleSurface={setSurfaceChecked}
            onToggleOverride={setOverrideChecked}
            onOverrideText={(surfaceId, value) =>
              setOverrideText((current) => ({ ...current, [surfaceId]: value }))
            }
            onRetrySurface={(surfaceId) => onRetrySurface(asset.asset_id, surfaceId)}
          />
        ))}
      </div>
      {approvableSurfaceIds.length > 0 && asset.surfaces.some((s) => s.kind === 'canonical') && (
        // Candidate #17 tester finding 5: "nothing tells the volunteer that
        // publishing is what starts transcription." This is the one action
        // in the whole console that triggers offline caption transcription
        // (civiccast.publish.router._queue_offline_captions runs the moment
        // the portal surface first goes public) -- say so before the click,
        // not just on the asset detail page after the fact, and set a
        // realistic time expectation up front.
        <p className="mt-3 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Approving the portal surface also starts offline caption transcription for this
          recording automatically. Expect several minutes for a full meeting recording (measured
          ~37s for 11s of audio on a 32 GB CPU-only reference machine) — check progress on the
          asset&apos;s Offline caption jobs panel.
        </p>
      )}
      {approvableSurfaceIds.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => setConfirmingPublish(true)}
            className="rounded-md px-3 py-2 text-xs font-semibold"
            style={{
              background: canSubmit ? 'var(--cc-ink)' : 'var(--cc-surface-3)',
              color: canSubmit ? 'var(--cc-ink-inv)' : 'var(--cc-ink-3)',
              border: '1px solid var(--cc-line)',
            }}
          >
            {isApproving ? 'Publishing selected surfaces...' : 'Approve and Publish selected'}
          </button>
          {overrideMissingJustification && (
            <span className="text-xs" style={{ color: 'var(--cc-err)' }}>
              Each override needs a specific approval record and fix path.
            </span>
          )}
          {blockedSelectedSurface && (
            <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
              The selected surface is blocked. Complete its next step or uncheck it before
              publishing other ready surfaces.
            </span>
          )}
          {!canPublish && (
            <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
              Publish operator role required to approve or retry surfaces.
            </span>
          )}
          {error && (
            <span role="alert" className="text-xs" style={{ color: 'var(--cc-err)' }}>
              <strong>Publish stopped.</strong>{' '}
              {errorDetail || 'The server did not provide a safe reason.'} Nothing else was
              published; correct the named issue and retry.
            </span>
          )}
        </div>
      )}
      {confirmingPublish && (
        <ConfirmDialog
          title={`Publish "${asset.title}" to residents?`}
          body={`${approvedSurfaceIds.length + overrides.length} selected surface(s) publish for real. The portal surface becomes publicly visible to residents immediately and starts offline caption transcription.`}
          confirmLabel="Approve and Publish"
          tone="brand"
          onConfirm={() => {
            setConfirmingPublish(false)
            submitApproval()
          }}
          onCancel={() => setConfirmingPublish(false)}
        />
      )}
    </article>
  )
}

function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const isApiError = error instanceof ApiError
  const is503 = isApiError && error.status === 503
  return (
    <div
      role="alert"
      className="mx-6 my-6 flex flex-col gap-2 rounded-md p-4"
      style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}
    >
      <div className="text-sm font-semibold">
        {is503 ? 'Publish dashboard needs a database.' : 'Could not load publish status.'}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        {isApiError && error.detail ? error.detail : error.message}
      </div>
      <div className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        <strong>Next step.</strong>{' '}
        {is503
          ? 'Open deployment settings, connect the CivicCast database, then reload this screen.'
          : 'Retry the request. If it fails again, check the API server logs.'}
      </div>
      <div>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md px-3 py-1.5 text-xs font-medium"
          style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
        >
          Retry
        </button>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div
      className="mx-6 my-10 flex flex-col items-center gap-2 rounded-md p-10 text-center"
      style={{ background: 'var(--cc-surface-2)', border: '1px dashed var(--cc-line-strong)' }}
    >
      <div className="text-sm font-semibold">No assets are ready for publish review.</div>
      <div className="max-w-md text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Upload or record a meeting first. Packaged recordings will appear here with portal,
        Internet Archive, local NAS, YouTube, and signed-record status.
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="mx-6 my-6 grid gap-3">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-40 w-full animate-pulse rounded-md"
          style={{ background: 'var(--cc-surface-2)' }}
        />
      ))}
    </div>
  )
}

export function PublishDashboardScreen() {
  const [filter, setFilter] = useState<'all' | PublishDashboardState>('all')
  const queryClient = useQueryClient()
  const staffIdentityQuery = useQuery({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canPublish =
    staffIdentityQuery.isSuccess &&
    hasOperatorRole(staffIdentityQuery.data, 'publish_operator')
  const query = useQuery({
    queryKey: ['publish-assets'],
    queryFn: listPublishAssets,
    retry: false,
  })
  const approveMutation = useMutation({
    mutationFn: ({
      assetId,
      payload,
    }: {
      assetId: string
      payload: PublishApprovalRequest
    }) => approvePublishAsset(assetId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['publish-assets'] })
    },
  })
  const retryMutation = useMutation({
    mutationFn: ({
      assetId,
      surfaceId,
    }: {
      assetId: string
      surfaceId: string
    }) =>
      retryPublishSurface(assetId, surfaceId, {
        operator_id: 'operator-dashboard',
        operator_display_name: 'Operator dashboard',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['publish-assets'] })
    },
  })

  const visible = useMemo(() => {
    const assets = query.data?.assets ?? []
    return filter === 'all'
      ? assets
      : assets.filter((asset) => asset.dashboard_state === filter)
  }, [filter, query.data])

  return (
    <div className="flex flex-col">
      <header className="px-6 pb-4 pt-6">
        <div
          className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: 'var(--cc-ink-3)' }}
        >
          Publish workflow
        </div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Publish dashboard</h1>
        <p className="mt-1 max-w-3xl text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Canonical portal, archive, reach, and signed-record surfaces are tracked
          separately so a YouTube problem never hides the public record state.
        </p>
      </header>

      {query.data && (
        <section
          aria-label="Publish summary"
          className="grid gap-2 px-6 pb-3 sm:grid-cols-3 lg:grid-cols-6"
        >
          {[
            ['Total', query.data.summary.total_assets],
            ['Draft', query.data.summary.draft],
            ['Portal live', query.data.summary.portal_live],
            ['Archive verified', query.data.summary.archive_verified],
            ['Degraded', query.data.summary.degraded],
            ['Needs action', query.data.summary.needs_operator_action],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-md p-3"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              <div className="text-[10px] font-semibold uppercase" style={{ color: 'var(--cc-ink-3)' }}>
                {label}
              </div>
              <div className="cc-mono text-xl font-semibold">{value}</div>
            </div>
          ))}
        </section>
      )}

      <div
        className="flex flex-wrap items-center gap-2 px-6 py-3"
        style={{ borderBottom: '1px solid var(--cc-line)' }}
      >
        <div role="tablist" aria-label="Filter publish state" className="flex flex-wrap gap-1">
          {FILTERS.map((item) => {
            const active = filter === item.id
            return (
              <button
                key={item.id}
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(item.id)}
                className="rounded-md px-3 py-1.5 text-xs font-medium"
                style={{
                  background: active ? 'var(--cc-ink)' : 'transparent',
                  color: active ? 'var(--cc-ink-inv)' : 'var(--cc-ink-2)',
                  border: '1px solid transparent',
                }}
              >
                {item.label}
              </button>
            )
          })}
        </div>
      </div>

      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {query.isSuccess && query.data.assets.length === 0 && <EmptyState />}
      {query.isSuccess && query.data.assets.length > 0 && visible.length === 0 && (
        <div
          className="mx-6 my-6 rounded-md p-4 text-center text-xs"
          style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-2)' }}
        >
          No assets match this publish filter.
        </div>
      )}
      {query.isSuccess && visible.length > 0 && (
        <div className="grid gap-3 px-6 py-4">
          {visible.map((asset) => (
            <AssetPanel
              key={asset.asset_id}
              asset={asset}
              canPublish={canPublish}
              isApproving={
                (approveMutation.isPending &&
                  approveMutation.variables?.assetId === asset.asset_id) ||
                (retryMutation.isPending &&
                  retryMutation.variables?.assetId === asset.asset_id)
              }
              error={
                approveMutation.variables?.assetId === asset.asset_id
                  ? approveMutation.error
                  : retryMutation.variables?.assetId === asset.asset_id
                    ? retryMutation.error
                  : null
              }
              onApprove={(assetId, payload) =>
                approveMutation.mutate({ assetId, payload })
              }
              onRetrySurface={(assetId, surfaceId) =>
                retryMutation.mutate({ assetId, surfaceId })
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

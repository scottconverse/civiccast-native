// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator console: Setup > Station Profile (S1). Two distinct panels, matching
// the backend's deliberate identity/capability split (S1 §2):
//
// 1. Station Identity -- the mutable operator-facing profile (name, timezone,
//    storage roots, default channel) via GET/PUT /api/staff/station/profile.
//    Read: setup_admin, meeting_operator, support_admin. Write: setup_admin.
// 2. StationBoxProfile -- the S1 computed, read-only cable/PEG appliance
//    readiness report (hardware, playout engine, PEG readiness roll-up,
//    cable-grade-OS verdict) via GET /api/staff/station-box-profile.

import { type ReactNode, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'
import {
  ApiError,
  getStaffIdentity,
  getStationBoxProfile,
  getStationProfile,
  updateStationProfile,
} from '../api/client'
import type {
  PegReadinessDimension,
  StaffIdentityResponse,
  StationBoxProfile,
  StationProfile,
} from '../types/api.generated'
import { hasRole } from './contribution-format'

const READ_ROLES = ['setup_admin', 'meeting_operator', 'support_admin']
const WRITE_ROLES = ['setup_admin']

type Tone = 'neutral' | 'ok' | 'warn' | 'info' | 'red'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  red: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

// role="alert" reserved for genuine error/notice banners (assertive live
// region) -- never for the per-dimension readiness badges below, which must
// not interrupt a screen reader on render.
function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div role="alert" className="rounded-md p-3 text-sm" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

function colorTone(color: 'green' | 'yellow' | 'red'): Tone {
  if (color === 'green') return 'ok'
  if (color === 'yellow') return 'warn'
  return 'red'
}

// A plain inline badge, never color-only (S20): the color word is always in
// the visible text, not just the background.
function ReadinessBadge({ overall }: { overall: 'green' | 'yellow' | 'red' }) {
  const c = TONE_COLORS[colorTone(overall)]
  return (
    <span
      className="rounded px-2 py-0.5 text-xs font-semibold uppercase"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {overall}
    </span>
  )
}

function ReadinessDimensionRow({ dimension }: { dimension: PegReadinessDimension }) {
  const c = TONE_COLORS[colorTone(dimension.color)]
  return (
    <li
      className="flex flex-col gap-0.5 rounded-md p-2 text-xs"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold">{dimension.label}</span>
        <span className="uppercase" style={{ color: 'var(--cc-ink-3)' }}>
          {dimension.color}
        </span>
      </div>
      <span>{dimension.message}</span>
      {dimension.next_step ? (
        <span style={{ color: 'var(--cc-ink-3)' }}>Next step: {dimension.next_step}</span>
      ) : null}
    </li>
  )
}

interface EditableFields {
  station_name: string
  station_timezone: string
  public_base_url: string
  default_channel_id: string
  media_library: string
  recordings: string
  backups: string
}

function fieldsFromProfile(profile: StationProfile): EditableFields {
  return {
    station_name: profile.station_name,
    station_timezone: profile.station_timezone ?? 'local',
    public_base_url: profile.public_base_url ?? '',
    default_channel_id: profile.default_channel_id ?? '',
    media_library: profile.storage_locations.media_library,
    recordings: profile.storage_locations.recordings,
    backups: profile.storage_locations.backups,
  }
}

function StationIdentityPanel({ canWrite }: { canWrite: boolean }) {
  const qc = useQueryClient()
  const profileQuery = useQuery<StationProfile>({
    queryKey: ['station-profile'],
    queryFn: getStationProfile,
    retry: false,
  })
  // Derived-state pattern (no effect): `fields` starts as whatever the
  // server last returned, and local edits are layered on top. `resetKey`
  // remembers which server snapshot `fields` was initialized from, so a
  // fresh fetch (e.g. after `onSuccess` refetches) can re-derive without a
  // useEffect synchronizing state from props/query data.
  const [fields, setFields] = useState<EditableFields | null>(null)
  const [resetKey, setResetKey] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  const serverKey = profileQuery.data ? profileQuery.data.recovery_kit_generated_at : null
  if (profileQuery.data && resetKey !== serverKey && !dirty) {
    // Safe to call setState during render here (not inside an effect): this
    // mirrors React's documented "adjusting state when a prop changes"
    // pattern -- it re-renders once more with the derived value instead of
    // committing a stale frame, and never fires when `dirty` is true.
    setFields(fieldsFromProfile(profileQuery.data))
    setResetKey(serverKey)
  }

  const saveMut = useMutation({
    mutationFn: (v: EditableFields) =>
      updateStationProfile({
        station_name: v.station_name,
        station_timezone: v.station_timezone,
        public_base_url: v.public_base_url || null,
        default_channel_id: v.default_channel_id,
        storage_locations: {
          media_library: v.media_library,
          recordings: v.recordings,
          backups: v.backups,
        },
      }),
    onSuccess: (data) => {
      qc.setQueryData(['station-profile'], data)
      setFields(fieldsFromProfile(data))
      setDirty(false)
    },
  })

  if (profileQuery.isLoading) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Loading station identity…
      </p>
    )
  }

  if (profileQuery.isError) {
    const notSetUp = profileQuery.error instanceof ApiError && profileQuery.error.status === 404
    if (notSetUp) {
      return (
        <Banner tone="info">
          No station identity yet -- complete First Setup to create the station profile before
          editing it here.
        </Banner>
      )
    }
    return <Banner tone="warn">{apiMessage(profileQuery.error, 'Could not load the station identity.')}</Banner>
  }

  if (!fields) {
    return (
      <Banner tone="info">No station identity is available yet.</Banner>
    )
  }

  function update<K extends keyof EditableFields>(key: K, value: EditableFields[K]) {
    setFields((prev) => (prev ? { ...prev, [key]: value } : prev))
    setDirty(true)
  }

  const canSave = canWrite && dirty && fields.station_name.trim().length > 0 && !saveMut.isPending

  return (
    <section
      aria-label="Station identity"
      className="space-y-3 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Station identity</h2>
        {!canWrite && (
          <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            read-only
          </span>
        )}
      </div>

      {saveMut.isError && (
        <Banner tone="warn">{apiMessage(saveMut.error, 'Could not save the station profile.')}</Banner>
      )}
      {saveMut.isSuccess && !dirty && <Banner tone="ok">Station profile saved.</Banner>}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Station name</span>
          <input
            aria-label="Station name"
            value={fields.station_name}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => update('station_name', e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Timezone (IANA name, or "local")</span>
          <input
            aria-label="Station timezone"
            value={fields.station_timezone}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => update('station_timezone', e.target.value)}
            placeholder="America/New_York"
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Default channel id</span>
          <input
            aria-label="Default channel id"
            value={fields.default_channel_id}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => update('default_channel_id', e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Public base URL (optional)</span>
          <input
            aria-label="Public base URL"
            value={fields.public_base_url}
            disabled={!canWrite || saveMut.isPending}
            onChange={(e) => update('public_base_url', e.target.value)}
            placeholder="https://watch.example.gov"
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
      </div>

      <fieldset className="grid gap-3 sm:grid-cols-3" disabled={!canWrite || saveMut.isPending}>
        <legend className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Storage roots
        </legend>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Media library</span>
          <input
            aria-label="Media library path"
            value={fields.media_library}
            onChange={(e) => update('media_library', e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Recordings</span>
          <input
            aria-label="Recordings path"
            value={fields.recordings}
            onChange={(e) => update('recordings', e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
        <label className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Backups</span>
          <input
            aria-label="Backups path"
            value={fields.backups}
            onChange={(e) => update('backups', e.target.value)}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}
          />
        </label>
      </fieldset>

      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        An env-var override (CIVICCAST_STATION_TZ, CIVICCAST_STATION_NAME,
        CIVICCAST_STATION_MEDIA_LIBRARY / _RECORDINGS / _BACKUPS) always wins over what is saved
        here — this form shows the value currently in effect.
      </p>

      {canWrite && (
        <div className="flex justify-end">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => fields && saveMut.mutate(fields)}
            className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            {saveMut.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </section>
  )
}

function StationBoxProfilePanel() {
  const boxQuery = useQuery<StationBoxProfile>({
    queryKey: ['station-box-profile'],
    queryFn: getStationBoxProfile,
    retry: false,
  })

  if (boxQuery.isLoading) {
    return (
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Probing station hardware and playout-engine readiness…
      </p>
    )
  }
  if (boxQuery.isError) {
    return <Banner tone="warn">{apiMessage(boxQuery.error, 'Could not load the station box profile.')}</Banner>
  }
  const profile = boxQuery.data
  if (!profile) {
    return <Banner tone="info">No station box profile is available yet.</Banner>
  }

  return (
    <section
      aria-label="Station box profile"
      className="space-y-3 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Station box profile (S1)</h2>
        <ReadinessBadge overall={profile.peg_readiness.overall} />
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt style={{ color: 'var(--cc-ink-3)' }}>CPU</dt>
        <dd>{profile.hardware.cpu.brand}</dd>
        <dt style={{ color: 'var(--cc-ink-3)' }}>RAM</dt>
        <dd>{profile.system_ram_total_gb} GB</dd>
        <dt style={{ color: 'var(--cc-ink-3)' }}>Recommended tier</dt>
        <dd className="cc-mono">{profile.hardware.recommended_tier}</dd>
        <dt style={{ color: 'var(--cc-ink-3)' }}>Playout engine</dt>
        <dd>
          {profile.engine.gstreamer_present
            ? `GStreamer ${profile.engine.gstreamer_version ?? ''}`.trim()
            : 'GStreamer not detected'}
          {' — qualifies for '}
          <span className="cc-mono">{profile.qualified_engine_tier.qualifies_for}</span>
        </dd>
        <dt style={{ color: 'var(--cc-ink-3)' }}>AI summary default</dt>
        <dd>
          {profile.ai_default.summary_model} ({profile.ai_default.basis})
        </dd>
      </dl>

      {/* S1 §5: while soak-pending, this line must read exactly the §13.1
          caveat -- no green single-Windows-PC cable claim before the
          decision. The text is server-rendered verbatim from
          cable_os_verdict.rationale, never rephrased client-side. */}
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        <strong>Cable-grade OS:</strong> {profile.cable_os_verdict.rationale}
      </p>

      <div>
        <h3 className="mb-1 text-xs font-semibold" style={{ color: 'var(--cc-ink-3)' }}>
          PEG readiness
        </h3>
        <ul className="space-y-1">
          {(profile.peg_readiness.dimensions ?? []).map((dimension) => (
            <ReadinessDimensionRow key={dimension.id} dimension={dimension} />
          ))}
        </ul>
      </div>
    </section>
  )
}

export function StationProfileScreen() {
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, READ_ROLES)
  const canWrite = hasRole(identityQuery.data, WRITE_ROLES)

  if (identityQuery.isLoading) {
    return (
      <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        Loading…
      </div>
    )
  }
  if (identityQuery.isError) {
    return (
      <div className="px-6 py-10">
        <AuthRequiredState error={identityQuery.error} />
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Station Profile requires the setup admin, meeting operator, or support admin role. Ask
          your station admin for access.
        </Banner>
      </div>
    )
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Station Profile</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          The station's identity (name, timezone, storage roots) and its computed cable/PEG
          appliance-readiness report -- separate concerns, per S1: identity is what you edit,
          readiness is what the box actually detects.
        </p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <StationIdentityPanel canWrite={canWrite} />
        <StationBoxProfilePanel />
      </div>
    </div>
  )
}

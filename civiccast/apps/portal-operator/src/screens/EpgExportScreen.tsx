// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S23 Operator console: EPG Export config management.
//
// Manage per-channel EPG export configs (X-List / XMLTV / CSV) and run the
// generator on demand. The generator either returns the document inline
// (download) or pushes to the configured aggregator endpoint — a push failure
// surfaces on the result's `error` field rather than as a 500, so we render
// the result and let the operator decide.
//
// Role-gated: setup_admin OR publish_operator (read + write per spec §4).

import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  createEpgConfig,
  deleteEpgConfig,
  generateEpgExport,
  getStaffIdentity,
  listEpgConfigs,
  patchEpgConfig,
} from '../api/client'
import type {
  EpgExportConfig,
  EpgExportConfigInput,
  EpgExportConfigUpdate,
  EpgGenerateResult,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import { parseFieldMapText, stringifyFieldMap } from './reports-format'
import { EmptyState } from '../components/EmptyState'

// Spec §4: setup_admin or publish_operator can read + manage EPG configs.
const ROLES = ['setup_admin', 'publish_operator']
const DEFAULT_STATION_ID = 'civiccast-station'

type EpgFormat = 'xlist' | 'xmltv' | 'csv'
const FORMAT_OPTIONS: { value: EpgFormat; label: string }[] = [
  { value: 'xlist', label: 'X-List (TV Guide / TitanTV)' },
  { value: 'xmltv', label: 'XMLTV' },
  { value: 'csv', label: 'CSV' },
]

type Tone = 'neutral' | 'warn' | 'info' | 'ok'
const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div
      role="alert"
      className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {children}
    </div>
  )
}

interface FormState {
  /** null when the form is in "create" mode; the config_id otherwise. */
  editingConfigId: string | null
  config_id: string
  channel_id: string
  format: EpgFormat
  horizon_days: number
  endpoint: string
  field_map_text: string
}

const EMPTY_FORM: FormState = {
  editingConfigId: null,
  config_id: '',
  channel_id: '',
  format: 'xlist',
  horizon_days: 14,
  endpoint: '',
  field_map_text: '',
}

function formFromConfig(cfg: EpgExportConfig): FormState {
  return {
    editingConfigId: cfg.config_id,
    config_id: cfg.config_id,
    channel_id: cfg.channel_id,
    format: cfg.format,
    horizon_days: cfg.horizon_days ?? 14,
    endpoint: cfg.endpoint ?? '',
    field_map_text: stringifyFieldMap(cfg.field_map),
  }
}

function EpgConfigForm({
  form,
  onChange,
  onSubmit,
  onCancelEdit,
  pending,
}: {
  form: FormState
  onChange: (next: FormState) => void
  onSubmit: () => void
  onCancelEdit: () => void
  pending: boolean
}) {
  const idCfg = useId()
  const idCh = useId()
  const idFmt = useId()
  const idHor = useId()
  const idEnd = useId()
  const idMap = useId()
  const editing = form.editingConfigId != null
  const canSubmit =
    form.config_id.trim().length > 0 &&
    form.channel_id.trim().length > 0 &&
    form.horizon_days > 0 &&
    !pending

  return (
    <section
      aria-label={editing ? 'Edit EPG export config' : 'Create EPG export config'}
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">
        {editing ? 'Edit export config' : 'Create export config'}
      </h2>

      <label htmlFor={idCfg} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Config ID</span>
        <input
          id={idCfg}
          aria-label="Config ID"
          type="text"
          value={form.config_id}
          disabled={editing}
          placeholder="epg-tv-guide-channel-1"
          onChange={(e) => onChange({ ...form, config_id: e.target.value })}
          className="rounded-md px-2 py-1.5 disabled:opacity-60"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
      </label>

      <label htmlFor={idCh} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Channel ID</span>
        <input
          id={idCh}
          aria-label="Channel ID"
          type="text"
          value={form.channel_id}
          placeholder="pub-1"
          onChange={(e) => onChange({ ...form, channel_id: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
      </label>

      <label htmlFor={idFmt} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Format</span>
        <select
          id={idFmt}
          aria-label="Format"
          value={form.format}
          onChange={(e) => onChange({ ...form, format: e.target.value as EpgFormat })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        >
          {FORMAT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label htmlFor={idHor} className="grid gap-1 text-xs" style={{ maxWidth: '10rem' }}>
        <span style={{ color: 'var(--cc-ink-3)' }}>Horizon (days)</span>
        <input
          id={idHor}
          aria-label="Horizon days"
          type="number"
          min={1}
          value={form.horizon_days}
          onChange={(e) =>
            onChange({ ...form, horizon_days: Number.parseInt(e.target.value, 10) || 0 })
          }
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
      </label>

      <label htmlFor={idEnd} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Aggregator endpoint (optional)</span>
        <input
          id={idEnd}
          aria-label="Endpoint"
          type="url"
          pattern="https://.*"
          value={form.endpoint}
          placeholder="https://aggregator.example.com/ingest"
          onChange={(e) => onChange({ ...form, endpoint: e.target.value })}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
        <span style={{ color: 'var(--cc-ink-3)', fontSize: '0.75rem' }}>
          https only. Loopback and private IPs are rejected.
        </span>
        <span style={{ color: 'var(--cc-ink-3)' }}>
          Leave blank to download the document instead of pushing to an endpoint.
        </span>
      </label>

      <label htmlFor={idMap} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>
          Field map (one <code>key=value</code> per line; blank lines + # comments ignored)
        </span>
        <textarea
          id={idMap}
          aria-label="Field map"
          rows={4}
          value={form.field_map_text}
          placeholder={'channel=pub-1\ngenre=category'}
          onChange={(e) => onChange({ ...form, field_map_text: e.target.value })}
          className="rounded-md px-2 py-1.5 font-mono"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        />
      </label>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {editing ? 'Save changes' : 'Create config'}
        </button>
        {editing && (
          <button
            type="button"
            onClick={onCancelEdit}
            className="rounded-md px-3 py-1.5 font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Cancel
          </button>
        )}
      </div>
    </section>
  )
}

function GenerateResultPanel({
  result,
  format,
}: {
  result: EpgGenerateResult
  format: EpgFormat
}) {
  const tone: Tone = result.error ? 'warn' : 'ok'
  const sizeKb = (result.bytes / 1024).toFixed(1)
  const mediaType =
    format === 'csv'
      ? 'text/csv'
      : format === 'xmltv'
        ? 'application/xml'
        : 'text/plain'
  // UX-6: if the document is returned inline (no endpoint), build a Blob URL
  // rather than a `data:` URL — browsers cap data: URLs at a few MB and a busy
  // station's 30-day XMLTV trivially exceeds that. The useEffect revokes the
  // URL when the document changes or the panel unmounts.
  const downloadHref = useMemo(() => {
    if (result.document == null) return null
    if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') return null
    const blob = new Blob([result.document], { type: `${mediaType};charset=utf-8` })
    return URL.createObjectURL(blob)
  }, [result.document, mediaType])
  useEffect(() => {
    return () => {
      if (downloadHref && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(downloadHref)
      }
    }
  }, [downloadHref])
  return (
    <Banner tone={tone}>
      <div className="space-y-1 text-xs">
        <div>
          <strong>{result.slot_count}</strong> slot{result.slot_count === 1 ? '' : 's'} ·{' '}
          <strong>{sizeKb} KB</strong> ({result.format})
        </div>
        {result.pushed_to && (
          <div>
            Pushed to <code>{result.pushed_to}</code>
            {result.pushed_at ? ` at ${result.pushed_at}` : ''}.
          </div>
        )}
        {result.error && (
          <div>
            Push failed: <strong>{result.error}</strong>. The staff API is still up; retry once the
            aggregator endpoint recovers.
          </div>
        )}
        {downloadHref && (
          <a
            href={downloadHref}
            download={`epg-export.${result.format === 'xmltv' ? 'xml' : result.format === 'csv' ? 'csv' : 'txt'}`}
            className="inline-block rounded-md px-2 py-1 text-xs font-medium"
            style={{
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          >
            Download document
          </a>
        )}
      </div>
    </Banner>
  )
}

function ConfigRow({
  cfg,
  onEdit,
  onDelete,
  onConfirmDelete,
  onGenerate,
  confirming,
  generating,
  anyGenerating,
  generateResult,
  generateError,
}: {
  cfg: EpgExportConfig
  onEdit: () => void
  onDelete: () => void
  onConfirmDelete: () => void
  onGenerate: () => void
  confirming: boolean
  generating: boolean
  anyGenerating: boolean
  generateResult: EpgGenerateResult | null
  generateError: string | null
}) {
  return (
    <li
      className="space-y-2 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <strong>{cfg.config_id}</strong>{' '}
          <span className="cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            ch={cfg.channel_id} · fmt={cfg.format} · horizon={cfg.horizon_days ?? 14}d
          </span>
          {cfg.endpoint ? (
            <div className="cc-mono text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              → {cfg.endpoint}
            </div>
          ) : (
            <div className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              (no endpoint — Generate returns a downloadable document)
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            aria-label={`Generate ${cfg.config_id}`}
            disabled={anyGenerating}
            onClick={onGenerate}
            className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {generating ? 'Generating…' : 'Generate now'}
          </button>
          <button
            type="button"
            aria-label={`Edit ${cfg.config_id}`}
            onClick={onEdit}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Edit
          </button>
          {confirming ? (
            <button
              type="button"
              aria-label={`Confirm delete ${cfg.config_id}`}
              onClick={onConfirmDelete}
              className="rounded-md px-2 py-1 text-xs font-semibold"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              Confirm delete
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Delete ${cfg.config_id}`}
              onClick={onDelete}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {confirming && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Confirming will delete this EPG export config and stop pushing to{' '}
          {cfg.endpoint || 'this download workflow'}. Existing aggregator data is not deleted.
        </p>
      )}
      {generateError && <Banner tone="warn">{generateError}</Banner>}
      {generateResult && <GenerateResultPanel result={generateResult} format={cfg.format} />}
    </li>
  )
}

export function EpgExportScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, ROLES)

  const configsQuery = useQuery({
    queryKey: ['epg-configs'],
    queryFn: listEpgConfigs,
    enabled: canRead,
  })

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [confirmDelete, setConfirmDelete] = useState<Record<string, true>>({})
  const [generateResults, setGenerateResults] = useState<Record<string, EpgGenerateResult>>({})
  const [generateErrors, setGenerateErrors] = useState<Record<string, string>>({})

  const invalidate = () => qc.invalidateQueries({ queryKey: ['epg-configs'] })

  const createMut = useMutation({
    mutationFn: (payload: EpgExportConfigInput) => createEpgConfig(payload),
    onSuccess: () => {
      invalidate()
      setForm(EMPTY_FORM)
    },
  })
  const patchMut = useMutation({
    mutationFn: (v: { configId: string; patch: EpgExportConfigUpdate }) =>
      patchEpgConfig(v.configId, v.patch),
    onSuccess: () => {
      invalidate()
      setForm(EMPTY_FORM)
    },
  })
  const deleteMut = useMutation({
    mutationFn: (configId: string) => deleteEpgConfig(configId),
    onSuccess: (_data, configId) => {
      setConfirmDelete((prev) => {
        const next = { ...prev }
        delete next[configId]
        return next
      })
      invalidate()
    },
  })
  const generateMut = useMutation({
    mutationFn: (configId: string) => generateEpgExport(configId),
    onMutate: (configId) => {
      setGenerateErrors((prev) => {
        const next = { ...prev }
        delete next[configId]
        return next
      })
      return { configId }
    },
    onSuccess: (result, configId) => {
      setGenerateResults((prev) => ({ ...prev, [configId]: result }))
    },
    onError: (err, configId) => {
      setGenerateErrors((prev) => ({
        ...prev,
        [configId]: apiMessage(err, 'Could not run the export.'),
      }))
    },
  })

  const handleSubmit = () => {
    const fieldMap = parseFieldMapText(form.field_map_text)
    if (form.editingConfigId != null) {
      const patch: EpgExportConfigUpdate = {
        channel_id: form.channel_id.trim(),
        format: form.format,
        horizon_days: form.horizon_days,
        endpoint: form.endpoint.trim() === '' ? null : form.endpoint.trim(),
        field_map: fieldMap,
      }
      patchMut.mutate({ configId: form.editingConfigId, patch })
      return
    }
    const payload: EpgExportConfigInput = {
      config_id: form.config_id.trim(),
      station_id: DEFAULT_STATION_ID,
      channel_id: form.channel_id.trim(),
      format: form.format,
      horizon_days: form.horizon_days,
      endpoint: form.endpoint.trim() === '' ? null : form.endpoint.trim(),
      field_map: fieldMap,
    }
    createMut.mutate(payload)
  }

  const sortedConfigs = useMemo(() => {
    const list = configsQuery.data ?? []
    return [...list].sort((a, b) => a.config_id.localeCompare(b.config_id))
  }, [configsQuery.data])

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
        <Banner tone="warn">
          Could not load your staff identity (
          {apiMessage(identityQuery.error, 'request failed')}). Check that you are signed in (staff
          token) and the local API is running, then retry.
        </Banner>
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          EPG export requires the setup admin or publish operator role. Ask your station admin for
          access.
        </Banner>
      </div>
    )
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">EPG Export</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Compile the upcoming committed schedule into X-List / XMLTV / CSV per a field map; either
          download the document or push it to an aggregator endpoint. A push failure surfaces on
          the result rather than as a server error, so a flaky aggregator never breaks the staff
          API.
        </p>
      </div>

      <EpgConfigForm
        form={form}
        onChange={setForm}
        onSubmit={handleSubmit}
        onCancelEdit={() => setForm(EMPTY_FORM)}
        pending={createMut.isPending || patchMut.isPending}
      />

      {createMut.isError && (
        <Banner tone="warn">{apiMessage(createMut.error, 'Could not create the config.')}</Banner>
      )}
      {patchMut.isError && (
        <Banner tone="warn">{apiMessage(patchMut.error, 'Could not save the config.')}</Banner>
      )}
      {deleteMut.isError && (
        <Banner tone="warn">{apiMessage(deleteMut.error, 'Could not delete the config.')}</Banner>
      )}

      <section aria-label="EPG export configs" className="space-y-2">
        <h2 className="text-sm font-semibold">Configured exports</h2>
        {configsQuery.isLoading ? (
          <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            Loading configs…
          </p>
        ) : configsQuery.isError ? (
          <Banner tone="warn">{apiMessage(configsQuery.error, 'Could not load configs.')}</Banner>
        ) : sortedConfigs.length === 0 ? (
          <EmptyState
            headline="No guide exports set up yet."
            body="An EPG export publishes this station's program guide in the format cable boxes and TV apps read. Create an export with the form above and it appears here."
          />
        ) : (
          <ul className="space-y-2">
            {sortedConfigs.map((cfg) => (
              <ConfigRow
                key={cfg.config_id}
                cfg={cfg}
                onEdit={() => setForm(formFromConfig(cfg))}
                onDelete={() => setConfirmDelete((prev) => ({ ...prev, [cfg.config_id]: true }))}
                onConfirmDelete={() => deleteMut.mutate(cfg.config_id)}
                onGenerate={() => generateMut.mutate(cfg.config_id)}
                confirming={cfg.config_id in confirmDelete}
                generating={generateMut.isPending && generateMut.variables === cfg.config_id}
                anyGenerating={generateMut.isPending}
                generateResult={generateResults[cfg.config_id] ?? null}
                generateError={generateErrors[cfg.config_id] ?? null}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

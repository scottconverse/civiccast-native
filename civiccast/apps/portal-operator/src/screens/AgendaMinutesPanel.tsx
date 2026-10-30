// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ApiError, createAgendaMinutes, getStaffIdentity, listSummaryReviewItems } from '../api/client'

export function AgendaMinutesPanel({ agendaId, assetId }: { agendaId: string; assetId: string }) {
  const [open, setOpen] = useState(false)
  return <section className="rounded-md border p-4">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Draft meeting minutes</button>
    {open && <MinutesCreator agendaId={agendaId} assetId={assetId} />}
  </section>
}

function MinutesCreator({ agendaId, assetId }: { agendaId: string; assetId: string }) {
  const qc = useQueryClient()
  const [source, setSource] = useState('')
  const identity = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity })
  const canWrite = identity.data?.roles?.includes('records_clerk') ?? false
  const summaries = useQuery({ queryKey: ['summary-review-items'], queryFn: listSummaryReviewItems, enabled: canWrite })
  const choices = (summaries.data?.items ?? []).filter((row) => row.meeting_id === assetId && row.status !== 'refused' && !row.agenda_minutes)
  const create = useMutation({ mutationFn: () => createAgendaMinutes(agendaId, { source_summary_id: source || null }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['summary-review-items'] }) } })
  return <div className="grid gap-3 mt-3">
    <p>Use a completed cited summary generated from this recording’s reviewed English captions, or start manually if the model is unavailable. Nothing is published here. Empty agenda sections need cited discussion or staff confirmation that they were not discussed. Motions and votes are entered and confirmed by a person.</p>
    {!canWrite && <p>Drafting minutes requires the records clerk role.</p>}
    <label>Discussion draft source <select aria-label="Minutes discussion draft source" value={source} onChange={(event) => setSource(event.target.value)}>
      <option value="">Manual draft — no model needed</option>
      {choices.map((row) => <option key={row.summary_id} value={row.summary_id}>{row.provenance.model_tag} — {row.provenance.generated_at}</option>)}
    </select></label>
    {summaries.isError && <p role="alert">Summary list unavailable. Manual drafting remains available; retry the summary list after storage recovers.</p>}
    <button type="button" disabled={!canWrite || create.isPending} onClick={() => create.mutate()}>Create draft minutes</button>
    {create.isError && <p role="alert">{create.error instanceof ApiError ? (create.error.detail ?? create.error.message) : create.error.message} <Link to="/review">Open caption review</Link></p>}
    {create.isSuccess && <p role="status">Draft created. <Link to="/summary">Open Summary review to edit citations, motions and votes, then approve and export.</Link></p>}
  </div>
}

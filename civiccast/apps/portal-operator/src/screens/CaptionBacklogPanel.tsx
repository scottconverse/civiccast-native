// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cancelOfflineCaptionJob, listOfflineCaptionJobs, listStaffAssets, queueCaptionBatch, retryOfflineCaptionJob } from '../api/client'

export function CaptionBacklogPanel({ canReview }: { canReview: boolean }) {
  const client = useQueryClient()
  const assets = useQuery({ queryKey: ['staff-assets'], queryFn: listStaffAssets })
  const jobs = useQuery({ queryKey: ['caption-backlog-jobs'], queryFn: () => listOfflineCaptionJobs(), refetchInterval: (query) => query.state.data?.some((job) => job.state === 'pending' || job.state === 'awaiting_review') ? 5000 : false })
  const [selected, setSelected] = useState<string[]>([])
  const refresh = () => client.invalidateQueries({ queryKey: ['caption-backlog-jobs'] })
  const batch = useMutation({ mutationFn: queueCaptionBatch, onSuccess: refresh })
  const action = useMutation({ mutationFn: ({ id, cancel }: { id: string; cancel: boolean }) => cancel ? cancelOfflineCaptionJob(id) : retryOfflineCaptionJob(id), onSuccess: refresh })
  const busy = batch.isPending || action.isPending
  const error = assets.error ?? jobs.error ?? batch.error ?? action.error
  return <section aria-label="Recording caption backlog" className="mx-6 grid gap-3 rounded-md border p-4">
    <h2 className="m-0 text-sm font-semibold">Recording caption backlog</h2>
    <p className="m-0 text-xs">Select up to ten packaged recordings. The existing worker processes audio serially; large recordings take time. Inference fills the review queue and does not approve captions. After correcting a completed recording, select it again to republish reviewed cues.</p>
    {error && <p role="alert">{error instanceof Error ? error.message : 'Caption backlog could not load.'}</p>}
    {(assets.isLoading || jobs.isLoading) && <p role="status">Loading recordings…</p>}
    <ul className="m-0 grid list-none gap-2 p-0">{assets.data?.map((asset) => {
      const job = jobs.data?.filter((row) => row.asset_id === asset.asset_id).at(-1)
      const state = job?.state ?? 'missing'
      const label = state === 'complete' ? (job && (job.published_cue_count ?? 0) > 0 ? 'Reviewed captions attached' : 'No speech cues produced') : state === 'awaiting_review' ? 'Awaiting human review' : state === 'pending' ? 'Queued or transcribing' : state === 'cancelled' ? 'Cancelled' : state === 'failed' ? 'Failed' : 'No caption job'
      return <li key={asset.asset_id} className="flex flex-wrap items-center gap-2">
        <label><input type="checkbox" aria-label={`Select ${asset.title}`} checked={selected.includes(asset.asset_id)} disabled={!canReview || busy || (!selected.includes(asset.asset_id) && selected.length >= 10)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, asset.asset_id] : ids.filter((id) => id !== asset.asset_id))} /> {asset.title}</label>
        <span>{label}{job ? ` · ${job.cue_count} cues · ${job.published_cue_count} published · ${job.attempts} attempts` : ''}</span>
        {job?.last_error && <span>{job.last_error}</span>}
        {canReview && job && (state === 'pending' || state === 'awaiting_review' || state === 'failed' || state === 'cancelled') && <button disabled={busy} onClick={() => action.mutate({ id: job.job_id, cancel: state === 'pending' || state === 'awaiting_review' })}>{state === 'cancelled' ? 'Resume' : state === 'failed' ? 'Retry' : 'Cancel'}</button>}
      </li>
    })}</ul>
    {assets.data?.length === 0 && <p>No recordings yet. Upload and package a recording in Assets.</p>}
    {canReview && <button disabled={busy || selected.length === 0} onClick={() => batch.mutate(selected)}>Caption selected ({selected.length}/10)</button>}
    <p className="m-0 text-xs">Cancel stops remaining work at the next audio chunk boundary; an in-flight model call may finish first. A publication write already started may finish. Review decisions and already published captions remain. Resume reuses retained cues.</p>
    {batch.data && <ul>{batch.data.map((result) => <li key={result.asset_id}>{assets.data?.find((asset) => asset.asset_id === result.asset_id)?.title ?? 'Recording'}: {result.error ?? 'Queued for caption review'}</li>)}</ul>}
  </section>
}

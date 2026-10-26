// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { editAgendaMinutes, listCaptionReviewItems } from '../api/client'
import type { MinutesContent, MinutesMotion, MinutesSection, SummaryDraft, TranscriptRange } from '../types/api.generated'

export function AgendaMinutesEditor({ summary, canReview, onSeek, onDirtyChange }: {
  summary: SummaryDraft; canReview: boolean; onSeek: (range: TranscriptRange) => void; onDirtyChange: (dirty: boolean) => void
}) {
  const minutes = summary.agenda_minutes!
  const editable = summary.status === 'pending_review' && canReview
  const qc = useQueryClient()
  const [content, setContent] = useState<MinutesContent>(structuredClone(minutes.content))
  const reviews = useQuery({ queryKey: ['minutes-source-cues', minutes.asset_id],
    queryFn: () => listCaptionReviewItems({ asset_id: minutes.asset_id, language: 'en' }), enabled: editable })
  const cues = (reviews.data ?? []).filter((item) => item.status === 'approved' || item.status === 'edited').map((item) => item.cue)
  const save = useMutation({ mutationFn: () => editAgendaMinutes(summary.summary_id,
    { content, expected_audit_fingerprint: summary.audit_fingerprint }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['summary-review-items'] }) } })
  const dirty = JSON.stringify(content) !== JSON.stringify(minutes.content)
  useEffect(() => { onDirtyChange(dirty || save.isPending) }, [dirty, save.isPending, onDirtyChange])
  function updateSection(index: number, patch: Partial<MinutesSection>) {
    setContent({ ...content, decisions_reviewed: false, sections: content.sections.map((section, n) => n === index ? { ...section, ...patch } : section) })
  }
  function updateMotion(index: number, motionIndex: number, patch: Partial<MinutesMotion>, confirming = false) {
    const motions = [...(content.sections[index].motions ?? [])]
    motions[motionIndex] = { ...motions[motionIndex], ...patch, ...(!confirming ? { human_confirmed: false } : {}) }
    updateSection(index, { motions })
  }
  function ranges(selected: HTMLCollectionOf<HTMLOptionElement>): TranscriptRange[] {
    const ids = new Set(Array.from(selected).map((option) => option.value))
    return cues.filter((cue) => ids.has(cue.cue_id)).map((cue) => ({ cue_id: cue.cue_id, start_seconds: cue.start_seconds, end_seconds: cue.end_seconds }))
  }
  return <section aria-label="Agenda minutes editor" className="grid gap-4">
    <h3 className="font-semibold">Agenda-based minutes — {editable ? 'draft for human review' : summary.status}</h3>
    <p>Discussion citations use original recording seconds. The existing source preview adjusts to the packaged trim. Motions and member votes are staff entries; changing either clears that motion’s confirmation. Save before approving.</p>
    {reviews.isError && <p role="alert">Reviewed cue list unavailable. Reload before adding citations.</p>}
    {content.sections.map((section, index) => <fieldset key={section.item_id} className="grid gap-3 rounded-md border p-3" disabled={!editable || save.isPending}>
      <legend>{section.title}</legend>
      <label><input type="checkbox" checked={section.not_discussed ?? false} onChange={(event) => updateSection(index, {
        not_discussed: event.target.checked, ...(event.target.checked ? { discussion: '', transcript_ranges: [], motions: [] } : {}),
      })} /> Staff confirmed this item was not discussed</label>
      {!section.not_discussed && <>
        <label>Discussion <textarea aria-label={`Discussion for ${section.title}`} rows={4} maxLength={12000} value={section.discussion ?? ''}
          onChange={(event) => updateSection(index, { discussion: event.target.value })} /></label>
        {editable && <label>Reviewed discussion citations (choose one or more)
          <select multiple aria-label={`Discussion citations for ${section.title}`} value={(section.transcript_ranges ?? []).map((range) => range.cue_id)}
            onChange={(event) => updateSection(index, { transcript_ranges: ranges(event.target.selectedOptions) })}>
            {cues.map((cue) => <option key={cue.cue_id} value={cue.cue_id}>{cue.start_seconds}s: {cue.text}</option>)}
          </select>
        </label>}
        {(section.motions ?? []).map((motion, m) => <fieldset key={m} className="grid gap-2 border p-3">
          <legend>Motion {m + 1}</legend>
          <label>Motion text <textarea aria-label={`Motion text ${index + 1}-${m + 1}`} value={motion.text} onChange={(event) => updateMotion(index, m, { text: event.target.value })} /></label>
          <label>Moved by <input value={motion.mover} onChange={(event) => updateMotion(index, m, { mover: event.target.value })} /></label>
          <label>Seconded by (if recorded) <input value={motion.seconder ?? ''} onChange={(event) => updateMotion(index, m, { seconder: event.target.value })} /></label>
          <label>Outcome <select value={motion.outcome} onChange={(event) => updateMotion(index, m, { outcome: event.target.value as MinutesMotion['outcome'] })}>
            <option value="no_vote">No vote</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="withdrawn">Withdrawn</option>
          </select></label>
          {editable && <label>Reviewed motion/vote citations <select multiple aria-label={`Motion citations ${index + 1}-${m + 1}`}
            value={motion.transcript_ranges.map((range) => range.cue_id)} onChange={(event) => updateMotion(index, m, { transcript_ranges: ranges(event.target.selectedOptions) })}>
            {cues.map((cue) => <option key={cue.cue_id} value={cue.cue_id}>{cue.start_seconds}s: {cue.text}</option>)}
          </select></label>}
          {(motion.votes ?? []).map((vote, v) => <div key={v} className="flex flex-wrap gap-2">
            <label>Member <input aria-label={`Vote member ${index + 1}-${m + 1}-${v + 1}`} value={vote.member} onChange={(event) => updateMotion(index, m, { votes: motion.votes!.map((item, n) => n === v ? { ...item, member: event.target.value } : item) })} /></label>
            <label>Vote <select aria-label={`Vote choice ${index + 1}-${m + 1}-${v + 1}`} value={vote.choice} onChange={(event) => updateMotion(index, m, { votes: motion.votes!.map((item, n) => n === v ? { ...item, choice: event.target.value as typeof vote.choice } : item) })}>
              <option value="yes">Yes</option><option value="no">No</option><option value="abstain">Abstain</option><option value="absent">Absent</option>
            </select></label>
            <button type="button" onClick={() => updateMotion(index, m, { votes: motion.votes!.filter((_, n) => n !== v) })}>Remove vote</button>
          </div>)}
          <button type="button" onClick={() => updateMotion(index, m, { votes: [...(motion.votes ?? []), { member: '', choice: 'yes' }] })}>Add member vote</button>
          <label><input type="checkbox" aria-label={`Confirm motion and votes ${index + 1}-${m + 1}`} checked={motion.human_confirmed ?? false}
            onChange={(event) => updateMotion(index, m, { human_confirmed: event.target.checked }, true)} /> I checked this motion, outcome and all entered votes against the recording</label>
          <button type="button" onClick={() => updateSection(index, { motions: section.motions!.filter((_, n) => n !== m) })}>Remove motion</button>
        </fieldset>)}
        <button type="button" onClick={() => updateSection(index, { motions: [...(section.motions ?? []), {
          text: '', mover: '', seconder: '', outcome: 'no_vote', votes: [], transcript_ranges: section.transcript_ranges ?? [], human_confirmed: false,
        }] })}>Add human-entered motion</button>
      </>}
    </fieldset>)}
    <div aria-label="Minutes source locations">{content.sections.flatMap((section) => [...(section.transcript_ranges ?? []), ...(section.motions ?? []).flatMap((motion) => motion.transcript_ranges)]).map((range, index) =>
      <button key={`${range.cue_id}-${index}`} type="button" onClick={() => onSeek(range)}>Preview source {range.start_seconds}-{range.end_seconds}s</button>)}</div>
    <label><input type="checkbox" disabled={!editable || save.isPending} checked={content.decisions_reviewed ?? false}
      onChange={(event) => setContent({ ...content, decisions_reviewed: event.target.checked })} /> I checked all agenda items for motions and votes, including items with none</label>
    {editable && <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>Save draft minutes</button>}
    {save.isError && <p role="alert">{save.error.message} Reload if the draft or reviewed transcript changed.</p>}
    <details><summary>Edit history ({minutes.revisions?.length ?? 0})</summary>
      {(minutes.revisions ?? []).map((revision, index) => <article key={index}><p>{revision.edited_at} — {revision.operator_id}</p>
        {revision.content.sections.map((section) => <p key={section.item_id}>{section.title}: {section.discussion} {section.motions?.map((motion) => `Motion: ${motion.text}; ${motion.outcome}; ${motion.votes?.map((vote) => `${vote.member}: ${vote.choice}`).join(', ')}`).join(' ')}</p>)}</article>)}
    </details>
  </section>
}

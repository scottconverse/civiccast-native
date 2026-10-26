// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, getRecordedCaptionSettings, saveRecordedCaptionSettings } from '../api/client'
import type { RecordedCaptionSettings } from '../types/recordedCaptions'

const DEFAULT_SETTINGS: RecordedCaptionSettings = {
  enabled: true,
  languages: ['en', 'es'],
  completion_requirement: 'all_selected_languages',
}

function apiMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail || error.message
  if (error instanceof Error) return error.message
  return 'Check the station settings and try again.'
}

export function RecordedCaptionSettingsPanel({ canWrite }: { canWrite: boolean }) {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['recorded-caption-settings'],
    queryFn: getRecordedCaptionSettings,
    retry: false,
  })
  const [draft, setDraft] = useState<RecordedCaptionSettings | null>(null)
  const current = settingsQuery.data
  const settings = draft ?? current ?? DEFAULT_SETTINGS
  const saveMutation = useMutation({
    mutationFn: (value: RecordedCaptionSettings) => saveRecordedCaptionSettings({ ...value, vocabulary: { ...value.vocabulary, terms: (value.vocabulary?.terms ?? []).map((term) => term.trim()).filter(Boolean) } }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['recorded-caption-settings'], saved)
      setDraft(saved)
    },
  })
  const busy = settingsQuery.isLoading || saveMutation.isPending
  const hasChanges = current != null && JSON.stringify(settings) !== JSON.stringify(current)

  function update<K extends keyof RecordedCaptionSettings>(
    key: K,
    value: RecordedCaptionSettings[K],
  ) {
    setDraft((previous) => ({ ...(previous ?? current ?? DEFAULT_SETTINGS), [key]: value }))
  }

  function toggleSpanish(enabled: boolean) {
    const languages: RecordedCaptionSettings['languages'] = enabled ? ['en', 'es'] : ['en']
    update('languages', languages)
  }

  return (
    <section
      aria-labelledby="recorded-caption-settings-title"
      className="grid gap-3 rounded-lg p-4"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div>
        <h2 id="recorded-caption-settings-title" className="m-0 text-sm font-semibold">
          Recorded captions
        </h2>
        <p className="m-0 mt-1 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
          Choose which reviewed caption tracks the station prepares for recordings.
        </p>
      </div>

      {settingsQuery.isLoading && (
        <p role="status" className="m-0 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
          Loading recorded-caption settings…
        </p>
      )}
      {settingsQuery.isError && (
        <p role="alert" className="m-0 rounded-md p-3 text-sm" style={{ background: 'var(--cc-warn-soft)' }}>
          Recorded-caption settings could not load. {apiMessage(settingsQuery.error)}
        </p>
      )}
      {saveMutation.isError && (
        <p role="alert" className="m-0 rounded-md p-3 text-sm" style={{ background: 'var(--cc-warn-soft)' }}>
          Recorded-caption settings could not be saved. {apiMessage(saveMutation.error)}
        </p>
      )}
      {saveMutation.isSuccess && (
        <p role="status" className="m-0 text-sm" style={{ color: 'var(--cc-ok)' }}>
          Settings saved. New jobs follow these settings; existing jobs pause or resume on the next worker scan.
        </p>
      )}

      {current && (
        <>
          <div className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-surface-2)' }}>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.enabled}
                disabled={!canWrite || busy}
                onChange={(event) => update('enabled', event.target.checked)}
              />
              <span>Enable recorded captions</span>
            </label>
            <p className="m-0 pl-6 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
              When off, new recordings do not get caption jobs and existing jobs pause in their current state until you enable captions again.
            </p>
          </div>

          <fieldset className="grid gap-2 rounded-md p-3" style={{ border: '1px solid var(--cc-line)' }}>
            <legend className="px-1 text-sm font-semibold">Caption languages</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked disabled aria-label="English captions are selected" />
              <span>English <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>(recording transcription)</span></span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                aria-label="Spanish captions"
                checked={settings.languages.includes('es')}
                disabled={!canWrite || busy}
                onChange={(event) => toggleSpanish(event.target.checked)}
              />
              <span>Spanish <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>(translated from reviewed English)</span></span>
            </label>
          </fieldset>

          {settings.languages.includes('es') && (
            <fieldset className="grid gap-2 rounded-md p-3" style={{ border: '1px solid var(--cc-line)' }}>
              <legend className="px-1 text-sm font-semibold">Completion requirement</legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="recorded-caption-completion"
                  value="all_selected_languages"
                  checked={settings.completion_requirement === 'all_selected_languages'}
                  disabled={!canWrite || busy}
                  onChange={() => update('completion_requirement', 'all_selected_languages')}
                />
                <span>
                  <span className="block font-semibold">Wait for every selected language</span>
                  <span className="block text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                    Attach English and Spanish together after both tracks are reviewed.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="recorded-caption-completion"
                  value="english_reviewed"
                  checked={settings.completion_requirement === 'english_reviewed'}
                  disabled={!canWrite || busy}
                  onChange={() => update('completion_requirement', 'english_reviewed')}
                />
                <span>
                  <span className="block font-semibold">Attach English after its review</span>
                  <span className="block text-xs" style={{ color: 'var(--cc-ink-2)' }}>
                    The job stays active while Spanish is translated and reviewed, then attaches the Spanish track.
                  </span>
                </span>
              </label>
            </fieldset>
          )}

          <label className="grid gap-1 text-sm">
            Local names and terms (one per line)
            <textarea aria-label="Local caption vocabulary" disabled={!canWrite || busy}
              value={(settings.vocabulary?.terms ?? []).join('\n')}
              onChange={(event) => update('vocabulary', { ...settings.vocabulary, terms: event.target.value.split('\n') })}
              className="min-h-24 rounded-md border p-2" />
            <span className="text-xs">Hints for the station’s supported Whisper transcription adapters on the next scan. These do not guarantee spelling or approve any captions.</span>
          </label>

          {canWrite && (
            <div className="flex justify-end">
              <button
                type="button"
                aria-label="Save recorded-caption settings"
                disabled={!hasChanges || busy}
                onClick={() => saveMutation.mutate(settings)}
                className="rounded-md px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
              >
                {saveMutation.isPending ? 'Saving…' : 'Save recorded-caption settings'}
              </button>
            </div>
          )}
          {!canWrite && (
            <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Read-only. Only the setup admin can change recorded-caption settings.
            </p>
          )}
        </>
      )}
    </section>
  )
}

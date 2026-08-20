// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Portal home: live now, coming up, newest recordings, follow + contribute.

import { useEffect, useState, type FormEvent } from 'react'
import { fetchJson, formatDateTime, formatDuration, postForm, postJson } from '../api'
import { HlsPlayer } from '../HlsPlayer'
import { buildRecordingsHash, buildWatchHash } from '../router'
import { LIVE_POLL_SECONDS, sameLiveStatus } from './homeLive'
import type {
  AssetMetadata,
  ContributorSubmissionReceipt,
  EmergencyOverlay,
  IdlePage,
  LoadError,
  PublicLiveStatus,
  PublicSubmissionStatus,
  ScheduleItem,
  SubmissionAgreementCatalog,
  SubmissionMediaReference,
  SubscriptionActionResponse,
  SubscriptionPublicResponse,
} from '../types'

type LoadState = 'loading' | 'ready' | 'error'
type SubscriptionState =
  | 'idle'
  | 'submitting'
  | 'pending_confirmation'
  | 'confirmed'
  | 'unsubscribed'
  | 'invalid_token'
  | 'error'

interface PortalData {
  live: PublicLiveStatus | null
  comingUp: ScheduleItem[]
  recordings: AssetMetadata[]
}

const EMPTY_DATA: PortalData = {
  live: null,
  comingUp: [],
  recordings: [],
}

const HOME_RECORDING_COUNT = 6

function getSubscriptionAction(): { action: 'confirm' | 'unsubscribe'; token: string } | null {
  const params = new URLSearchParams(window.location.search)
  const action = params.get('subscription')
  const token = params.get('token')
  if ((action === 'confirm' || action === 'unsubscribe') && token) {
    return { action, token }
  }
  return null
}

function shouldShowEmergencyOverlay(): boolean {
  return new URLSearchParams(window.location.search).get('emergency') === '1'
}

export function HomeScreen() {
  const [state, setState] = useState<LoadState>('loading')
  const [data, setData] = useState<PortalData>(EMPTY_DATA)
  const [errors, setErrors] = useState<LoadError[]>([])
  const [idlePage, setIdlePage] = useState<IdlePage | null>(null)
  const [emergencyOverlay, setEmergencyOverlay] = useState<EmergencyOverlay | null>(null)
  const [email, setEmail] = useState('')
  const [subscriptionState, setSubscriptionState] = useState<SubscriptionState>('idle')
  const [subscriptionMessage, setSubscriptionMessage] = useState('')
  const [subscriptionNextStep, setSubscriptionNextStep] = useState('')
  const [unsubscribeToken, setUnsubscribeToken] = useState<string | null>(null)
  const [submissionAgreement, setSubmissionAgreement] = useState<SubmissionAgreementCatalog | null>(null)
  const [submissionFile, setSubmissionFile] = useState<File | null>(null)
  const [submissionState, setSubmissionState] = useState<'idle' | 'submitting' | 'submitted' | 'error'>('idle')
  const [submissionMessage, setSubmissionMessage] = useState('')
  const [submissionReceipt, setSubmissionReceipt] = useState<ContributorSubmissionReceipt | null>(null)
  const [statusLookup, setStatusLookup] = useState({
    submissionId: '',
    receiptToken: '',
  })
  const [statusLookupState, setStatusLookupState] = useState<'idle' | 'checking' | 'ready' | 'error'>('idle')
  const [statusLookupMessage, setStatusLookupMessage] = useState('')
  const [statusLookupResult, setStatusLookupResult] = useState<PublicSubmissionStatus | null>(null)
  const [submissionForm, setSubmissionForm] = useState({
    producerName: '',
    contactEmail: '',
    organization: '',
    title: '',
    description: '',
    tags: '',
    requestedAirDate: '',
  })

  useEffect(() => {
    let cancelled = false

    async function loadPortal() {
      fetchJson<IdlePage>('/api/public/cg/idle')
        .then((result) => {
          if (!cancelled) setIdlePage(result)
        })
        .catch(() => {
          if (!cancelled) setIdlePage(null)
        })
      if (shouldShowEmergencyOverlay()) {
        fetchJson<EmergencyOverlay>('/api/public/cg/emergency-overlay')
          .then((result) => {
            if (!cancelled) setEmergencyOverlay(result)
          })
          .catch(() => {
            if (!cancelled) setEmergencyOverlay(null)
          })
      }
      fetchJson<SubmissionAgreementCatalog>('/api/public/contribute/agreements/current')
        .then((result) => {
          if (!cancelled) setSubmissionAgreement(result)
        })
        .catch(() => {
          if (!cancelled) setSubmissionAgreement(null)
        })

      setState('loading')
      const results = await Promise.allSettled([
        fetchJson<PublicLiveStatus>('/api/public/live/current'),
        fetchJson<ScheduleItem[]>('/api/public/schedule/coming-up'),
        fetchJson<AssetMetadata[]>('/api/public/assets'),
      ])

      if (cancelled) return

      const nextErrors: LoadError[] = []
      const nextData: PortalData = { ...EMPTY_DATA }

      if (results[0].status === 'fulfilled') {
        nextData.live = results[0].value
      } else {
        nextErrors.push({
          surface: 'Live stream',
          message: 'Live status is unavailable. Refresh the page or check the station link.',
        })
      }
      if (results[1].status === 'fulfilled') {
        nextData.comingUp = results[1].value
      } else {
        nextErrors.push({
          surface: 'Coming up',
          message: 'The schedule could not be loaded. Try again in a few minutes.',
        })
      }
      if (results[2].status === 'fulfilled') {
        nextData.recordings = results[2].value
      } else {
        nextErrors.push({
          surface: 'Recordings',
          message: 'Published recordings could not be loaded. Try again or contact the station.',
        })
      }

      setData(nextData)
      setErrors(nextErrors)
      setState(nextErrors.length === 3 ? 'error' : 'ready')
    }

    void loadPortal()
    return () => {
      cancelled = true
    }
  }, [])

  // Follow the live stream while the page is open: re-resolve /current on an
  // interval so (1) a mid-broadcast source switch — the surge switch hands
  // viewers a CDN manifest_url under load — flows to <HlsPlayer> (which swaps
  // its source when the manifestUrl prop changes) and (2) the origin keeps
  // seeing this viewer, which is the surge switch's concurrent-load signal.
  // Only updates state when something actually changed, so a steady broadcast
  // causes no re-render churn.
  useEffect(() => {
    let cancelled = false
    const timer = window.setInterval(() => {
      fetchJson<PublicLiveStatus>('/api/public/live/current')
        .then((live) => {
          if (cancelled) return
          setData((prev) => (sameLiveStatus(prev.live, live) ? prev : { ...prev, live }))
        })
        .catch(() => {
          /* transient network blip — keep the last known live status */
        })
    }, LIVE_POLL_SECONDS * 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    const action = getSubscriptionAction()
    if (!action) return
    const endpoint =
      action.action === 'confirm'
        ? '/api/public/subscribe/confirm'
        : '/api/public/subscribe/unsubscribe'
    fetchJson<SubscriptionActionResponse>(`${endpoint}?token=${encodeURIComponent(action.token)}`)
      .then((result) => {
        setSubscriptionState(result.status)
        setSubscriptionMessage(result.message)
        setSubscriptionNextStep(result.next_step)
      })
      .catch((error: Error) => {
        setSubscriptionState('invalid_token')
        setSubscriptionMessage(error.message)
        setSubscriptionNextStep('Use the signup form to request a fresh confirmation link.')
      })
  }, [])

  async function submitSubscription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubscriptionState('submitting')
    try {
      const result = await postJson<SubscriptionPublicResponse>('/api/public/subscribe/email', {
        email,
        target_type: 'channel',
        target_id: 'government',
      })
      setSubscriptionState(result.status)
      setSubscriptionMessage(result.message)
      setSubscriptionNextStep(result.next_step)
      setUnsubscribeToken(result.unsubscribe_token)
    } catch (error) {
      setSubscriptionState('error')
      setSubscriptionMessage(error instanceof Error ? error.message : 'Subscription failed.')
      setSubscriptionNextStep('Check the email address and try again. Contact the station if it still fails.')
    }
  }

  async function submitContributorProgram(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!submissionFile) {
      setSubmissionState('error')
      setSubmissionMessage('Choose a video file before submitting.')
      return
    }
    setSubmissionState('submitting')
    setSubmissionMessage('')
    try {
      const agreement =
        submissionAgreement ??
        await fetchJson<SubmissionAgreementCatalog>('/api/public/contribute/agreements/current')
      const uploadBody = new FormData()
      uploadBody.set('file', submissionFile)
      const media = await postForm<SubmissionMediaReference>(
        '/api/public/contribute/uploads',
        uploadBody,
      )
      const tags = submissionForm.tags
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean)
      const receipt = await postJson<ContributorSubmissionReceipt>(
        '/api/public/contribute/submissions',
        {
          contributor: {
            account_id: submissionForm.contactEmail
              .toLowerCase()
              .replace(/[^a-z0-9]+/g, '-')
              .replace(/^-|-$/g, '')
              .slice(0, 80) || 'contributor',
            display_name: submissionForm.producerName,
            contact_email: submissionForm.contactEmail,
            organization: submissionForm.organization || null,
          },
          channel_id: 'public',
          title: submissionForm.title,
          description: submissionForm.description,
          tags,
          producer_name: submissionForm.producerName,
          requested_air_date: submissionForm.requestedAirDate || null,
          media,
          agreements: [
            {
              agreement_id: agreement.agreement_id,
              version: agreement.version,
              accepted_at: new Date().toISOString(),
              accepted_by_name: submissionForm.producerName,
            },
          ],
          notifications: [
            {
              kind: 'email',
              target: submissionForm.contactEmail,
            },
          ],
        },
      )
      setSubmissionReceipt(receipt)
      setStatusLookup({
        submissionId: receipt.submission_id,
        receiptToken: receipt.receipt_token,
      })
      setStatusLookupResult(null)
      setStatusLookupState('idle')
      setSubmissionState('submitted')
      setSubmissionMessage('Your program was sent to the station review queue.')
    } catch (error) {
      setSubmissionState('error')
      setSubmissionMessage(error instanceof Error ? error.message : 'Submission failed.')
    }
  }

  async function checkContributorStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setStatusLookupState('checking')
    setStatusLookupMessage('')
    setStatusLookupResult(null)
    try {
      const result = await fetchJson<PublicSubmissionStatus>(
        `/api/public/contribute/submissions/${encodeURIComponent(statusLookup.submissionId)}/status?receipt_token=${encodeURIComponent(statusLookup.receiptToken)}`,
      )
      setStatusLookupResult(result)
      setStatusLookupState('ready')
      setStatusLookupMessage(result.status_message)
    } catch (error) {
      setStatusLookupState('error')
      setStatusLookupMessage(error instanceof Error ? error.message : 'Status lookup failed.')
    }
  }

  const liveManifest = data.live?.manifest_url
  const isPartial = state === 'ready' && errors.length > 0
  const isEmpty =
    state === 'ready' &&
    !liveManifest &&
    data.comingUp.length === 0 &&
    data.recordings.length === 0
  const recentRecordings = data.recordings.slice(0, HOME_RECORDING_COUNT)

  return (
    <>
      {emergencyOverlay && <EmergencyNotice overlay={emergencyOverlay} />}

      {state === 'loading' && (
        <section
          role="status"
          aria-live="polite"
          className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-200"
        >
          Loading the live stream, schedule, and recordings.
        </section>
      )}

      {state === 'error' && (
        <section
          role="alert"
          className="rounded-lg border border-red-400/50 bg-red-950/40 p-5 text-sm text-red-100"
        >
          The public portal could not load right now. Refresh the page, then
          contact the station if the problem continues.
        </section>
      )}

      {isPartial && <StatusList title="Some portal sections need attention" errors={errors} />}

      {/* Audit UX-009: while loading, ONLY the loading banner shows - the
          content sections otherwise render resolved-looking defaults ("No
          live broadcast is on air") beneath a still-visible banner. */}
      {state !== 'loading' && (
        <>
      <section aria-labelledby="live-heading" className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-3">
          <div>
            <h2 id="live-heading" className="text-xl font-semibold">
              Live now
            </h2>
            <p className="text-sm text-stone-300">
              {data.live?.state === 'on_air'
                ? `${data.live.title ?? 'Broadcast'} is on air.`
                : 'No live broadcast is on air.'}
            </p>
          </div>
          {liveManifest ? (
            <HlsPlayer
              manifestUrl={liveManifest}
              analytics={{ channelId: data.live?.channel_id ?? null }}
            />
          ) : idlePage ? (
            <IdlePanel idlePage={idlePage} />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg border border-dashed border-stone-500 bg-[#172018] p-6 text-center text-sm text-stone-300">
              Live video appears here when the station goes on air.
            </div>
          )}
        </div>

        <aside className="rounded-lg border border-stone-500/30 bg-[#172018] p-5">
          <h3 className="text-base font-semibold">Broadcast status</h3>
          <dl className="mt-4 space-y-3 text-sm">
            <StatusRow label="State" value={data.live?.state === 'on_air' ? 'On air' : 'Offline'} />
            <StatusRow label="Channel" value={data.live?.channel_id ?? 'None yet'} />
            <StatusRow label="Started" value={formatDateTime(data.live?.started_at ?? null)} />
          </dl>
        </aside>
      </section>

      {isEmpty && (
        <section className="rounded-lg border border-stone-500/30 bg-[#172018] p-5 text-sm text-stone-200">
          Nothing is posted yet. Check back after the station schedules a
          premiere or publishes a recording.
        </section>
      )}

      <section aria-labelledby="coming-up-heading" className="space-y-3">
        <h2 id="coming-up-heading" className="text-xl font-semibold">
          Coming up
        </h2>
        {data.comingUp.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {data.comingUp.map((item) => (
              <article key={item.id} className="rounded-lg border border-stone-500/30 bg-[#172018] p-4">
                <h3 className="font-semibold">{item.asset_title ?? item.asset_id}</h3>
                <p className="mt-1 text-sm text-stone-300">{formatDateTime(item.scheduled_at)}</p>
                <p className="mt-2 text-xs uppercase tracking-[0.14em] text-emerald-200">
                  {item.channel_id} / {formatDuration(item.duration_seconds)}
                </p>
              </article>
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-stone-500 bg-[#172018] p-4 text-sm text-stone-300">
            No premieres are scheduled.
          </p>
        )}
      </section>

      <section aria-labelledby="recordings-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="recordings-heading" className="text-xl font-semibold">
            Latest recordings
          </h2>
          <a
            href={buildRecordingsHash({})}
            className="inline-flex min-h-11 items-center rounded-md border border-emerald-300/50 px-3 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200"
          >
            Browse all recordings
          </a>
        </div>
        {recentRecordings.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {recentRecordings.map((asset) => (
              <RecordingCard key={asset.asset_id} asset={asset} />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-stone-500 bg-[#172018] p-4 text-sm text-stone-300">
            No published recordings are available.
          </p>
        )}
      </section>

      <section
        aria-labelledby="audience-heading"
        className="grid gap-4 rounded-lg border border-stone-500/30 bg-[#172018] p-5 lg:grid-cols-[1.2fr_0.8fr]"
      >
        <div>
          <h2 id="audience-heading" className="text-xl font-semibold">
            Follow new recordings
          </h2>
          <p className="mt-1 text-sm text-stone-300">
            Get a notice when this channel publishes a recording, or subscribe
            to the public RSS and podcast feeds without sharing personal data.
          </p>
          <form onSubmit={submitSubscription} className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <label className="grid gap-1 text-sm">
              <span className="font-medium text-stone-100">Email address</span>
              <input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
                placeholder="resident@example.org"
              />
            </label>
            <button
              type="submit"
              disabled={subscriptionState === 'submitting'}
              className="min-h-11 self-end rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:opacity-60"
            >
              {subscriptionState === 'submitting' ? 'Sending link' : 'Subscribe'}
            </button>
          </form>
          {subscriptionState !== 'idle' && (
            <div
              role={subscriptionState === 'error' || subscriptionState === 'invalid_token' ? 'alert' : 'status'}
              aria-live="polite"
              className={`mt-4 rounded-md border p-4 text-sm ${
                subscriptionState === 'error' || subscriptionState === 'invalid_token'
                  ? 'border-red-300/60 bg-red-950/30 text-red-100'
                  : 'border-emerald-300/60 bg-emerald-950/20 text-emerald-100'
              }`}
            >
              <div className="font-semibold">{subscriptionMessage}</div>
              <div className="mt-1">{subscriptionNextStep}</div>
              {unsubscribeToken && (
                <a
                  className="mt-3 inline-flex text-emerald-100 underline"
                  href={`/?subscription=unsubscribe&token=${encodeURIComponent(unsubscribeToken)}`}
                >
                  Test one-click unsubscribe
                </a>
              )}
            </div>
          )}
        </div>
        <div className="grid content-start gap-3 text-sm">
          <a
            className="rounded-md border border-stone-500/40 bg-[#101811] px-3 py-3 text-stone-100 hover:border-emerald-300/60 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            href="/api/public/subscribe/rss/channel/government.xml"
          >
            Channel RSS feed
          </a>
          <a
            className="rounded-md border border-stone-500/40 bg-[#101811] px-3 py-3 text-stone-100 hover:border-emerald-300/60 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            href="/api/public/podcast/government.xml"
          >
            Podcast RSS feed
          </a>
          <p className="text-xs leading-5 text-stone-400">
            RSS does not create a subscriber row. Email uses double opt-in,
            one-click unsubscribe, and no tracking pixels.
          </p>
        </div>
      </section>

      <section
        aria-labelledby="contribute-heading"
        className="grid gap-4 rounded-lg border border-stone-500/30 bg-[#172018] p-5 lg:grid-cols-[0.9fr_1.1fr]"
      >
        <div>
          <h2 id="contribute-heading" className="text-xl font-semibold">
            Submit a program
          </h2>
          <p className="mt-1 text-sm leading-6 text-stone-300">
            Community producers can send video to the station review queue.
            Operators review every file before anything airs or publishes.
          </p>
          <div className="mt-4 rounded-md border border-stone-500/40 bg-[#101811] p-4 text-sm text-stone-300">
            <div className="font-semibold text-stone-100">
              {submissionAgreement?.title ?? 'Submission agreement'}
            </div>
            <div className="mt-1">
              {submissionAgreement?.summary ??
                'Your submission is accepted only after station review.'}
            </div>
          </div>
        </div>

        <form onSubmit={submitContributorProgram} className="grid gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <ContributorInput
              label="Producer name"
              value={submissionForm.producerName}
              onChange={(value) => setSubmissionForm((current) => ({ ...current, producerName: value }))}
            />
            <ContributorInput
              label="Email"
              type="email"
              value={submissionForm.contactEmail}
              onChange={(value) => setSubmissionForm((current) => ({ ...current, contactEmail: value }))}
            />
          </div>
          <ContributorInput
            label="Organization"
            required={false}
            value={submissionForm.organization}
            onChange={(value) => setSubmissionForm((current) => ({ ...current, organization: value }))}
          />
          <ContributorInput
            label="Program title"
            value={submissionForm.title}
            onChange={(value) => setSubmissionForm((current) => ({ ...current, title: value }))}
          />
          <label className="grid gap-1 text-sm">
            <span className="font-medium text-stone-100">Description</span>
            <textarea
              required
              value={submissionForm.description}
              onChange={(event) => {
                const value = event.currentTarget.value
                setSubmissionForm((current) => ({ ...current, description: value }))
              }}
              className="min-h-24 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <ContributorInput
              label="Tags"
              required={false}
              value={submissionForm.tags}
              onChange={(value) => setSubmissionForm((current) => ({ ...current, tags: value }))}
              placeholder="arts, community"
            />
            <ContributorInput
              label="Requested air date"
              required={false}
              type="datetime-local"
              value={submissionForm.requestedAirDate}
              onChange={(value) => setSubmissionForm((current) => ({ ...current, requestedAirDate: value }))}
            />
          </div>
          <label className="grid gap-1 text-sm">
            <span className="font-medium text-stone-100">Video file</span>
            <input
              required
              type="file"
              accept="video/*"
              onChange={(event) => setSubmissionFile(event.currentTarget.files?.[0] ?? null)}
              className="rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 file:mr-3 file:rounded-md file:border-0 file:bg-emerald-200 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-emerald-950 focus:outline-none focus:ring-2 focus:ring-emerald-200"
            />
          </label>
          <button
            type="submit"
            disabled={submissionState === 'submitting'}
            className="min-h-11 rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:opacity-60"
          >
            {submissionState === 'submitting' ? 'Uploading' : 'Send to review'}
          </button>
          {submissionState !== 'idle' && (
            <div
              role={submissionState === 'error' ? 'alert' : 'status'}
              aria-live="polite"
              className={`rounded-md border p-4 text-sm ${
                submissionState === 'error'
                  ? 'border-red-300/60 bg-red-950/30 text-red-100'
                  : 'border-emerald-300/60 bg-emerald-950/20 text-emerald-100'
              }`}
            >
              <div className="font-semibold">{submissionMessage}</div>
              {submissionReceipt && (
                <div className="mt-2 grid gap-1">
                  <div>Receipt: {submissionReceipt.submission_id}</div>
                  <div className="break-all">Status token: {submissionReceipt.receipt_token}</div>
                </div>
              )}
            </div>
          )}
        </form>

        <form
          onSubmit={checkContributorStatus}
          className="grid gap-3 rounded-md border border-stone-500/40 bg-[#101811] p-4 lg:col-start-2"
        >
          <h3 className="text-base font-semibold text-stone-100">Check submission status</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <ContributorInput
              label="Receipt"
              value={statusLookup.submissionId}
              onChange={(value) => setStatusLookup((current) => ({ ...current, submissionId: value }))}
            />
            <ContributorInput
              label="Status token"
              value={statusLookup.receiptToken}
              onChange={(value) => setStatusLookup((current) => ({ ...current, receiptToken: value }))}
            />
          </div>
          <button
            type="submit"
            disabled={statusLookupState === 'checking'}
            className="min-h-11 rounded-md border border-emerald-300/60 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:opacity-60"
          >
            {statusLookupState === 'checking' ? 'Checking' : 'Check status'}
          </button>
          {statusLookupState !== 'idle' && (
            <div
              role={statusLookupState === 'error' ? 'alert' : 'status'}
              aria-live="polite"
              className={`rounded-md border p-4 text-sm ${
                statusLookupState === 'error'
                  ? 'border-red-300/60 bg-red-950/30 text-red-100'
                  : 'border-emerald-300/60 bg-emerald-950/20 text-emerald-100'
              }`}
            >
              <div className="font-semibold">{statusLookupMessage}</div>
              {statusLookupResult && (
                <div className="mt-1">
                  {statusLookupResult.title} / {statusLookupResult.state.replace('_', ' ')} / updated{' '}
                  {formatDateTime(statusLookupResult.updated_at)}
                  {statusLookupResult.decline_reason ? ` / ${statusLookupResult.decline_reason}` : ''}
                </div>
              )}
            </div>
          )}
        </form>
      </section>
        </>
      )}
    </>
  )
}

export function RecordingCard({ asset }: { asset: AssetMetadata }) {
  return (
    <article className="rounded-lg border border-stone-500/30 bg-[#172018] p-4">
      <h3 className="font-semibold">{asset.title}</h3>
      <p className="mt-1 text-sm text-stone-300">
        {asset.description ?? 'Recording description not posted.'}
      </p>
      <p className="mt-3 text-xs text-stone-400">
        Published {formatDateTime(asset.published_at)}
      </p>
      <a
        href={buildWatchHash(asset.asset_id)}
        className="mt-4 inline-flex rounded-md border border-emerald-300/50 px-3 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200"
      >
        Watch recording
      </a>
    </article>
  )
}

function ContributorInput({
  label,
  value,
  onChange,
  required = true,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  required?: boolean
  type?: string
  placeholder?: string
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-medium text-stone-100">{label}</span>
      <input
        required={required}
        type={type}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        placeholder={placeholder}
        className="min-h-11 rounded-md border border-stone-500 bg-[#101811] px-3 py-2 text-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-200"
      />
    </label>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-3 last:border-0 last:pb-0">
      <dt className="text-stone-400">{label}</dt>
      <dd className="text-right font-medium text-stone-100">{value}</dd>
    </div>
  )
}

function StatusList({ title, errors }: { title: string; errors: LoadError[] }) {
  return (
    <section
      role="status"
      aria-live="polite"
      className="rounded-lg border border-amber-300/50 bg-amber-950/30 p-5 text-sm text-amber-50"
    >
      <h2 className="font-semibold">{title}</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {errors.map((error) => (
          <li key={error.surface}>
            <span className="font-medium">{error.surface}:</span> {error.message}
          </li>
        ))}
      </ul>
    </section>
  )
}

function IdlePanel({ idlePage }: { idlePage: IdlePage }) {
  return (
    <section
      aria-label="Between-streams idle page"
      className="flex aspect-video flex-col justify-center rounded-lg border border-stone-500/30 bg-[#172018] p-6 text-stone-100"
    >
      <div className="max-w-xl">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-200">
          {idlePage.channel_id}
        </p>
        <h3 className="mt-2 text-2xl font-semibold">{idlePage.title}</h3>
        <p className="mt-3 text-sm leading-6 text-stone-300">{idlePage.message}</p>
        <p className="mt-4 text-sm font-medium text-stone-100">
          {idlePage.next_broadcast_label}
        </p>
        <a
          href={idlePage.action_url}
          className="mt-5 inline-flex rounded-md border border-emerald-300/50 px-3 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-300/10 focus:outline-none focus:ring-2 focus:ring-emerald-200"
        >
          {idlePage.action_label}
        </a>
      </div>
    </section>
  )
}

function EmergencyNotice({ overlay }: { overlay: EmergencyOverlay }) {
  return (
    <section
      role="alert"
      aria-live={overlay.aria_live}
      className="rounded-lg border border-red-300/70 bg-red-950/50 p-5 text-red-50"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-red-100">
        {overlay.severity} notice
      </p>
      <h2 className="mt-1 text-xl font-semibold">{overlay.title}</h2>
      <p className="mt-2 text-sm leading-6">{overlay.message}</p>
      <p className="mt-2 text-sm leading-6">{overlay.instructions}</p>
      {overlay.cellular_fallback_enabled && (
        <p className="mt-3 text-sm font-medium">
          Cellular fallback is enabled for emergency delivery.
        </p>
      )}
    </section>
  )
}

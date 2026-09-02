// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Operator console: Settings > AI Models (S13). Per-feature model selection — three
// cards (captions, summary, translation), each showing the effective model, its tier
// band (Local/Cloud/Frontier), cost ($USD/token + estimate), and privacy, plus a
// dropdown to pick another model. The DEFAULT is always the LOCAL tier (zero cloud
// fee). The hosted/frontier tiers are FUNCTIONAL but default OFF: choosing one requires
// the operator to tick a TOS/consent checkbox accepting the per-token cost (decision A).
//
// Roles (S13 §4.1): setup_admin OR meeting_operator may READ; only setup_admin may
// change a selection. Read-only operators see the controls disabled, not hidden.

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'

import {
  ApiError,
  getAiModelAvailability,
  getAiModelConfiguration,
  getProviderKeyStatus,
  getStaffIdentity,
  getSystemHealth,
  saveProviderKey,
  selectFeatureModel,
} from '../api/client'
import type {
  FeatureModelAvailability,
  FeatureModelRegistry,
  ModelTier,
  StaffIdentityResponse,
} from '../types/api.generated'
import { hasRole } from './contribution-format'
import {
  availabilityWarning,
  credentialProviderForTier,
  type CredentialProvider,
  FEATURE_ORDER,
  featureLabel,
  isCloudTier,
  privacyLabel,
  tierBandLabel,
  tierBandTone,
  tierCostLabel,
  tierFitsBox,
  tierLatencyLabel,
  tierRamLabel,
  type Tone,
} from './ai-models-format'

const READ_ROLES = ['setup_admin', 'meeting_operator']
const WRITE_ROLES = ['setup_admin']

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

// role="alert" — an assertive live region. Reserved for genuine error/notice banners,
// NOT the per-card status badges (which must not interrupt a screen reader on render).
function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  return (
    <div role="alert" className="rounded-md p-3 text-sm" style={{ background: c.bg, border: `1px solid ${c.bd}` }}>
      {children}
    </div>
  )
}

// A plain inline badge (NOT a live region). Carries a TEXT label, so color is never the
// only signal (S20) — cost/privacy here are safety-relevant.
function BandBadge({ tier }: { tier: ModelTier | undefined }) {
  const c = TONE_COLORS[tierBandTone(tier)]
  return (
    <span
      className="rounded px-1.5 py-0.5 text-xs font-semibold"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {tierBandLabel(tier)}
    </span>
  )
}

function tierFor(reg: FeatureModelRegistry, key: string): ModelTier | undefined {
  return (reg.available_tiers ?? []).find((t) => t.key === key)
}

// A per-card availability hint (U4 / Q2 / M3, spec §6.3). A plain inline TEXT block
// (color is never the only signal, S20). NOT a live region — it must not interrupt a
// screen reader on render (same discipline as BandBadge).
function AvailabilityHint({ message }: { message: string }) {
  const c = TONE_COLORS.warn
  return (
    <p
      className="rounded-md p-2 text-xs"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      <strong>Availability:</strong> {message}
    </p>
  )
}

/** A single feature's card. Pure presentational: it takes the registry + a write flag +
 *  an onSelect callback and owns only the transient "which option is staged" / "consent
 *  ticked" UI state. The container does the data fetch + the POST. */
export function FeatureModelCard({
  registry,
  canWrite,
  onSelect,
  availability,
  boxRamGb,
  pending = false,
  credentialStoredByProvider,
  onSaveProviderKey,
  savingKey = false,
}: {
  registry: FeatureModelRegistry
  canWrite: boolean
  onSelect: (feature: string, modelKey: string, consent: boolean) => void
  availability?: FeatureModelAvailability
  boxRamGb?: number
  pending?: boolean
  /** Per-provider "is an API key stored" map (from GET /credentials/{provider}).
   *  A provider absent from the map (or undefined value) means "status unknown" —
   *  the key field is only offered when the status is explicitly `false`. */
  credentialStoredByProvider?: Partial<Record<CredentialProvider, boolean>>
  onSaveProviderKey?: (provider: CredentialProvider, apiKey: string) => void
  savingKey?: boolean
}) {
  const effectiveKey = registry.effective_model_key ?? registry.default_key
  // `staged` is what the dropdown currently shows; it starts at the effective key.
  const [staged, setStaged] = useState(effectiveKey)
  const [consent, setConsent] = useState(false)
  // Write-only API-key buffer for a staged hosted tier (never seeded from server).
  const [apiKey, setApiKey] = useState('')
  const stagedTier = tierFor(registry, staged)
  const effectiveTier = tierFor(registry, effectiveKey)
  const label = `${featureLabel(registry.feature)} model`
  const consentId = useId()
  const keyFieldId = useId()
  const warnRef = useRef<HTMLDivElement>(null)

  const stagedIsCloud = isCloudTier(stagedTier)
  // The cloud provider whose key backs the staged tier (null for a local tier).
  const stagedProvider = credentialProviderForTier(stagedTier)
  // Only offer the key field when the backend explicitly says no key is stored
  // for this provider (an unknown/undefined status never forces the field on).
  const needsProviderKey =
    canWrite &&
    stagedIsCloud &&
    stagedProvider != null &&
    credentialStoredByProvider?.[stagedProvider] === false
  // U7: when a cloud tier becomes staged (the warning block appears), move keyboard /
  // AT focus to it so it is not silently missed below the select.
  useEffect(() => {
    if (canWrite && stagedIsCloud) warnRef.current?.focus()
  }, [canWrite, stagedIsCloud])

  function handleChange(nextKey: string) {
    setStaged(nextKey)
    setConsent(false)
    setApiKey('')
    const nextTier = tierFor(registry, nextKey)
    // Local tiers apply immediately. Cloud/frontier tiers wait for the TOS opt-in.
    if (!isCloudTier(nextTier)) {
      onSelect(registry.feature, nextKey, false)
    }
  }

  const availMessage = availabilityWarning(availability)
  const isStagedPreview = staged !== effectiveKey
  const stagedLicenseUrl = stagedTier?.license_url ?? null

  return (
    <section
      aria-label={`${featureLabel(registry.feature)} model selection`}
      className="space-y-2 rounded-md p-3 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{featureLabel(registry.feature)}</h2>
        <BandBadge tier={effectiveTier} />
      </div>

      {/* U4/Q2/M3: spec §6.3 degraded-state surface — TEXT, not color-only. */}
      {availMessage && <AvailabilityHint message={availMessage} />}

      {/* The 2026-08-29 audit found this picker had a model, a cost and a
          latency figure but no caller, so it carried a "not connected yet"
          warning. Recorded-Spanish captions connected it: publishing a
          recording translates its approved English captions with the model
          selected here. The banner is now a plain status note, not a warning
          — it says where the selection shows up, because a setting whose
          effect is invisible is the thing operators distrust. */}
      {registry.feature === 'translation' && (
        <div
          role="status"
          className="rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-surface-3)', color: 'var(--cc-ink-2)' }}
        >
          This model translates a published recording&rsquo;s approved English
          captions into Spanish. The Spanish cues then go to the caption review
          queue for their own approval — a recording publishes with both
          language tracks or neither. Live broadcasts are captioned in English
          only.
        </div>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt style={{ color: 'var(--cc-ink-3)' }}>Current model</dt>
        <dd className="cc-mono">{effectiveKey}</dd>
        {/* U5: human-readable notes as a secondary line under the slug. */}
        {effectiveTier?.notes ? (
          <>
            <dt style={{ color: 'var(--cc-ink-3)' }}>About</dt>
            <dd>{effectiveTier.notes}</dd>
          </>
        ) : null}
        <dt style={{ color: 'var(--cc-ink-3)' }}>Cost</dt>
        <dd>{tierCostLabel(effectiveTier)}</dd>
        {/* U1: latency was shown nowhere; the operator trades latency, so surface it. */}
        <dt style={{ color: 'var(--cc-ink-3)' }}>Latency</dt>
        <dd>{tierLatencyLabel(effectiveTier)}</dd>
        <dt style={{ color: 'var(--cc-ink-3)' }}>Privacy</dt>
        <dd>{privacyLabel(effectiveTier)}</dd>
        {/* U5: license/provider-terms link on the card. */}
        {effectiveTier?.license_url ? (
          <>
            <dt style={{ color: 'var(--cc-ink-3)' }}>Terms</dt>
            <dd>
              <a
                href={effectiveTier.license_url}
                target="_blank"
                rel="noreferrer noopener"
                style={{ color: 'var(--cc-brand-2)' }}
              >
                View provider terms
              </a>
            </dd>
          </>
        ) : null}
      </dl>

      <label className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Choose a model</span>
        <select
          aria-label={label}
          value={staged}
          disabled={!canWrite || pending}
          onChange={(e) => handleChange(e.target.value)}
          className="rounded-md px-2 py-1.5"
          style={{
            background: 'var(--cc-surface)',
            border: '1px solid var(--cc-line)',
            color: 'var(--cc-ink)',
          }}
        >
          {(registry.available_tiers ?? []).map((t) => {
            const ram = tierRamLabel(t)
            const fits = tierFitsBox(t, boxRamGb)
            // U3: annotate each option with its RAM requirement (TEXT, not color),
            // and disable an option the box demonstrably cannot run.
            const ramSuffix = ram ? ` · ${ram}${fits ? '' : ' (exceeds this box)'}` : ''
            return (
              <option key={t.key} value={t.key} disabled={!fits}>
                {t.key} — {tierBandLabel(t)} · {tierCostLabel(t)}
                {ramSuffix}
              </option>
            )
          })}
        </select>
      </label>

      {/* U1: staged-preview — the cost/privacy/latency of the option the operator is
          ABOUT to pick, visible before commit (for a local instant-apply tier this
          reflects the just-applied choice; for cloud it precedes the Apply gate). */}
      {isStagedPreview && stagedTier && (
        <dl
          aria-label={`${featureLabel(registry.feature)} staged selection`}
          className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
        >
          <dt style={{ color: 'var(--cc-ink-3)' }}>Staged</dt>
          <dd className="cc-mono">{staged}</dd>
          <dt style={{ color: 'var(--cc-ink-3)' }}>Band</dt>
          <dd>{tierBandLabel(stagedTier)}</dd>
          <dt style={{ color: 'var(--cc-ink-3)' }}>Cost</dt>
          <dd>{tierCostLabel(stagedTier)}</dd>
          <dt style={{ color: 'var(--cc-ink-3)' }}>Latency</dt>
          <dd>{tierLatencyLabel(stagedTier)}</dd>
          <dt style={{ color: 'var(--cc-ink-3)' }}>Privacy</dt>
          <dd>{privacyLabel(stagedTier)}</dd>
          {tierRamLabel(stagedTier) ? (
            <>
              <dt style={{ color: 'var(--cc-ink-3)' }}>Requires</dt>
              <dd>{tierRamLabel(stagedTier)}</dd>
            </>
          ) : null}
        </dl>
      )}

      {canWrite && stagedIsCloud && (
        <div
          ref={warnRef}
          role="group"
          aria-label={`${featureLabel(registry.feature)} cloud model consent`}
          tabIndex={-1}
          className="space-y-2 rounded-md p-2 text-xs"
          style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}
        >
          <div>
            <strong>{tierBandLabel(stagedTier)} model.</strong> {privacyLabel(stagedTier)}. Cost:{' '}
            {tierCostLabel(stagedTier)}. Latency: {tierLatencyLabel(stagedTier)}.
          </div>
          {/* U5: the operator accepts the TOS — give them the link to read it. */}
          {stagedLicenseUrl ? (
            <div>
              <a
                href={stagedLicenseUrl}
                target="_blank"
                rel="noreferrer noopener"
                style={{ color: 'var(--cc-brand-2)' }}
              >
                View provider terms
              </a>
            </div>
          ) : null}
          {/* Finding-1 UI half (DONE-10 / D13): the operator must be able to store
              the provider API key from the product, or the hosted path defers. Shown
              only when the backend reports NO key is stored for this provider. The
              field is write-only — the key is never displayed or pre-filled, and on a
              successful save the "no credential" availability warning clears. */}
          {needsProviderKey && stagedProvider != null && (
            <div className="space-y-1 border-t pt-2" style={{ borderColor: 'var(--cc-line)' }}>
              <div>
                <strong>Provider API key required.</strong> No key is stored for this
                provider yet, so this hosted model will defer until one is saved.
              </div>
              <label htmlFor={keyFieldId} className="grid gap-1">
                <span style={{ color: 'var(--cc-ink-3)' }}>Provider API key</span>
                <input
                  id={keyFieldId}
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={apiKey}
                  disabled={savingKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste the provider API key"
                  aria-label={`${featureLabel(registry.feature)} ${tierBandLabel(stagedTier)} provider API key`}
                  className="rounded-md px-2 py-1.5"
                  style={{
                    background: 'var(--cc-surface)',
                    border: '1px solid var(--cc-line)',
                    color: 'var(--cc-ink)',
                  }}
                />
              </label>
              <button
                type="button"
                disabled={apiKey.trim().length === 0 || savingKey}
                onClick={() => {
                  onSaveProviderKey?.(stagedProvider, apiKey)
                  setApiKey('')
                }}
                className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
              >
                Save key
              </button>
            </div>
          )}
          <label id={consentId} className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <span>
              I accept the provider terms of service and the per-token cost for this hosted model.
            </span>
          </label>
          <button
            type="button"
            disabled={!consent || pending}
            aria-describedby={consentId}
            onClick={() => onSelect(registry.feature, staged, true)}
            className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Apply cloud model
          </button>
        </div>
      )}

      {!canWrite && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          (read-only — changing the model requires the setup admin role)
        </p>
      )}
    </section>
  )
}

export function AiModelsScreen() {
  const qc = useQueryClient()
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })
  const canRead = hasRole(identityQuery.data, READ_ROLES)
  const canWrite = hasRole(identityQuery.data, WRITE_ROLES)

  const configQuery = useQuery({
    queryKey: ['ai-model-config'],
    queryFn: getAiModelConfiguration,
    enabled: canRead,
  })

  // Spec §6.3 availability surface (U4/Q2/M3): per-feature present/absent + runtime
  // reachability of the EFFECTIVE model. Best-effort — a failed probe must never blank
  // the config screen, so a query error simply yields no availability hints.
  const availabilityQuery = useQuery({
    queryKey: ['ai-model-availability'],
    queryFn: getAiModelAvailability,
    enabled: canRead,
    retry: false,
  })

  // Box RAM (U3): drives the disabled state for tiers whose min_ram_gb exceeds this
  // hardware. Best-effort — a failed/absent sample simply leaves RAM unknown, in which
  // case no option is gated (the requirement text is still always shown).
  const healthQuery = useQuery({
    queryKey: ['system-health-ram'],
    queryFn: getSystemHealth,
    enabled: canRead,
    retry: false,
  })
  const boxRamGb = healthQuery.data?.latest_resource_sample?.ram_total_gb ?? undefined

  const selectMut = useMutation({
    mutationFn: (v: { feature: string; modelKey: string; consent: boolean }) =>
      selectFeatureModel(v.feature, {
        model_key: v.modelKey,
        ...(v.consent ? { consent_accepted: true } : {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ai-model-config'] })
      qc.invalidateQueries({ queryKey: ['ai-model-availability'] })
    },
  })

  // Finding-1 UI half (DONE-10 / D13): per-provider "is an API key stored" so the
  // cards can offer a write-only key field for a staged hosted tier that has none.
  // Only a setup admin may write a key — read-only operators never see the field, so
  // the status queries (and the save mutation) are scoped to the write role. A failed
  // status probe leaves the provider's status unknown, which never forces the field on.
  const ollamaCloudKeyQuery = useQuery({
    queryKey: ['ai-model-credential', 'ollama-cloud'],
    queryFn: () => getProviderKeyStatus('ollama-cloud'),
    enabled: canWrite,
    retry: false,
  })
  const openrouterKeyQuery = useQuery({
    queryKey: ['ai-model-credential', 'openrouter'],
    queryFn: () => getProviderKeyStatus('openrouter'),
    enabled: canWrite,
    retry: false,
  })
  const credentialStoredByProvider: Partial<Record<CredentialProvider, boolean>> = {
    ...(ollamaCloudKeyQuery.data ? { 'ollama-cloud': ollamaCloudKeyQuery.data.stored } : {}),
    ...(openrouterKeyQuery.data ? { openrouter: openrouterKeyQuery.data.stored } : {}),
  }

  const saveKeyMut = useMutation({
    mutationFn: (v: { provider: CredentialProvider; apiKey: string }) =>
      saveProviderKey(v.provider, { api_key: v.apiKey }),
    onSuccess: (_data, v) => {
      // Refresh the per-provider status (the "no credential" warning clears) and the
      // availability surface (a hosted tier flips from "will defer" to ready).
      qc.invalidateQueries({ queryKey: ['ai-model-credential', v.provider] })
      qc.invalidateQueries({ queryKey: ['ai-model-availability'] })
    },
  })

  if (identityQuery.isLoading) {
    return (
      <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        Loading…
      </div>
    )
  }
  if (identityQuery.isError) {
    // An auth/connectivity failure is NOT a permissions problem — say so distinctly.
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
          AI Models requires the setup admin or meeting operator role. Ask your station admin for
          access.
        </Banner>
      </div>
    )
  }

  const features = configQuery.data?.features ?? {}
  const availabilityByFeature = availabilityQuery.data?.features ?? {}

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">AI Models</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Choose the model behind each AI feature. The default is always a private, on-device
          (local) model with no per-token cost. Hosted cloud and frontier models are available but
          default off — selecting one sends content to a third-party provider and bills per token.
        </p>
      </div>

      {selectMut.isError && (
        <Banner tone="warn">{apiMessage(selectMut.error, 'Could not save the model selection.')}</Banner>
      )}

      {saveKeyMut.isError && (
        <Banner tone="warn">{apiMessage(saveKeyMut.error, 'Could not save the provider API key.')}</Banner>
      )}

      {configQuery.isLoading ? (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Loading AI model configuration…
        </p>
      ) : configQuery.isError ? (
        <Banner tone="warn">{apiMessage(configQuery.error, 'Could not load AI model configuration.')}</Banner>
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          {FEATURE_ORDER.map((feature) => {
            const reg = features[feature]
            if (!reg) return null
            return (
              <FeatureModelCard
                key={feature}
                registry={reg}
                canWrite={canWrite}
                availability={availabilityByFeature[feature]}
                boxRamGb={boxRamGb == null ? undefined : Math.floor(boxRamGb)}
                pending={selectMut.isPending}
                credentialStoredByProvider={credentialStoredByProvider}
                onSaveProviderKey={(provider, apiKey) =>
                  saveKeyMut.mutate({ provider, apiKey })
                }
                savingKey={saveKeyMut.isPending}
                onSelect={(f, modelKey, consent) =>
                  selectMut.mutate({ feature: f, modelKey, consent })
                }
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

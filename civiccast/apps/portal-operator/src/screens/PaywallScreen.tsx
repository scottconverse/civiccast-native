// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// S26 Operator console: subscription paywall config (slice 4).
//
// No card / PAN data ever rendered or captured on this page — Stripe-hosted
// Checkout only in production (DC-4); the `mock` provider option is test-only
// and intended for non-prod (development / contract tests / CI fixtures), not
// for a live station. This screen only configures: master enable toggle,
// provider (`stripe` for production, `mock` for non-prod), per-station signing
// secret (HMAC for magic-link + Stripe webhook verification), tier list (each
// row maps a CivicCast tier slug to an existing Stripe price id the operator
// already created in the Stripe dashboard — CivicCast never creates Stripe
// prices/customers/products here, keeping PCI SAQ-A scope intact), and
// comp-access grants by email. A canceled subscription or webhook touchpoint
// is owned server-side; the operator never sees a card number or a Stripe
// customer object here.
//
// Layout, top to bottom:
//
//   A. Config card — enable toggle (default OFF, with a banner explaining
//      what OFF vs ON means), provider selector, signing-secret field with
//      a Show toggle + "Generate new secret" button (crypto-random base64),
//      and Save / Delete buttons. Delete is a two-step confirm (matches the
//      AgendasScreen cascade-warn pattern).
//
//   B. Tiers section — table of existing tiers + an add-tier form. Each row
//      can be removed locally; "Save" persists the whole tiers list via PUT.
//      `price_id` is validated against the Stripe shape (must start with
//      "price_") inline; a misshapen id surfaces a warn under the field.
//
//   C. Comp grants section — table of recently-issued grants (operator-only;
//      a list endpoint is a follow-up so the table starts empty and shows
//      only what was issued in this session), + an issue-grant form with
//      email, scope_kind (asset / series / all), scope_id (hidden when kind
//      is "all"), and an optional expires_at date.
//
// Disabled-when-off: when `enabled=false` the tiers + grants sections render
// greyed out with an info banner — they are not *blocked* (the operator can
// pre-fill them) but the visual hierarchy says "flip the toggle first".
//
// Role gate: setup_admin only — matches the UnderwritingScreen MANAGE_ROLES
// convention and the spec §5 expectation that paywall config is a station-
// admin surface (not an everyday operator surface).

import { useId, useState, type CSSProperties, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  deleteAccessGrant,
  deletePaywallConfig,
  getPaywallConfig,
  getStaffIdentity,
  issueCompGrant,
  upsertPaywallConfig,
} from '../api/client'
import type {
  AccessGrant,
  AccessGrantInput,
  PaywallConfig,
  PaywallConfigInput,
  PaywallProvider,
  PaywallScopeKind,
  PaywallTier,
} from '../api/client'
import type { StaffIdentityResponse } from '../types/api.generated'
import { hasRole } from './contribution-format'

const ADMIN_ROLES = ['setup_admin']
const DEFAULT_STATION_ID = 'civiccast-station'
const DEFAULT_CONFIG_ID = 'paywall-default'
// Stripe price ids always start with "price_" — a misshapen id is almost
// always a copy-paste mistake. Inline validation surfaces it before save.
const STRIPE_PRICE_PREFIX = 'price_'

type Tone = 'neutral' | 'warn' | 'info' | 'ok'

const TONE_COLORS: Record<Tone, { bg: string; bd: string }> = {
  neutral: { bg: 'var(--cc-surface-2)', bd: 'var(--cc-line)' },
  warn: { bg: 'var(--cc-warn-soft)', bd: 'var(--cc-warn)' },
  info: { bg: 'var(--cc-info-soft)', bd: 'var(--cc-info)' },
  ok: { bg: 'var(--cc-ok-soft)', bd: 'var(--cc-ok)' },
}

const INPUT_STYLE: CSSProperties = {
  background: 'var(--cc-surface)',
  border: '1px solid var(--cc-line)',
  color: 'var(--cc-ink)',
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail || err.message || fallback
  if (err instanceof Error) return err.message || fallback
  return fallback
}

function Banner({ tone, children }: { tone: Tone; children: ReactNode }) {
  const c = TONE_COLORS[tone]
  const role = tone === 'warn' ? 'alert' : 'status'
  return (
    <div
      role={role}
      className="rounded-md p-3 text-sm"
      style={{ background: c.bg, border: `1px solid ${c.bd}` }}
    >
      {children}
    </div>
  )
}

// --- Helpers ----------------------------------------------------------------

/** Generate a 32-byte random base64 secret, suitable for HMAC signing. Uses
 *  the same Web Crypto primitive the rest of the operator app relies on
 *  (no Node.js polyfill). The encoded string is URL-safe-ish — we just want
 *  a high-entropy opaque blob that copies/pastes cleanly through forms. */
function generateSigningSecret(): string {
  const bytes = new Uint8Array(32)
  // crypto is part of the browser global; in vitest+jsdom it is provided too.
  // We avoid `window.crypto` so server-side rendering tooling doesn't trip.
  globalThis.crypto.getRandomValues(bytes)
  // btoa over a binary string is the simplest path here; we don't need
  // URL-safe encoding (the value sits in fetch bodies, not URLs).
  let bin = ''
  for (let i = 0; i < bytes.length; i++) {
    bin += String.fromCharCode(bytes[i])
  }
  return btoa(bin)
}

/** True if `value` looks like a Stripe price id ("price_..."). Empty is also
 *  considered invalid because every saved tier needs a price id. */
function isStripePriceShape(value: string): boolean {
  const trimmed = value.trim()
  return trimmed.startsWith(STRIPE_PRICE_PREFIX) && trimmed.length > STRIPE_PRICE_PREFIX.length
}

/** Best-effort empty-config seed when the GET returns 404. We never trigger
 *  a save automatically — the operator has to flip the toggle and click
 *  "Save" before anything hits the server. */
function emptyConfig(): PaywallConfig {
  const now = new Date().toISOString()
  return {
    config_id: DEFAULT_CONFIG_ID,
    station_id: DEFAULT_STATION_ID,
    enabled: false,
    provider: 'stripe',
    tiers: [],
    signing_secret: null,
    created_at: now,
    updated_at: now,
  }
}

// --- Screen entry-point (role gate) ----------------------------------------

export function PaywallScreen() {
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    retry: false,
  })

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
          {apiMessage(identityQuery.error, 'request failed')}). Check that you are signed in
          and the local API is running, then retry.
        </Banner>
      </div>
    )
  }
  const canAdmin = hasRole(identityQuery.data, ADMIN_ROLES)
  if (!canAdmin) {
    return (
      <div className="px-6 py-10">
        <Banner tone="info">
          Forbidden — the subscription paywall is a setup-admin surface. Ask your station
          admin for access.
        </Banner>
      </div>
    )
  }
  return <PaywallBody />
}

// --- Screen body ------------------------------------------------------------

function PaywallBody() {
  const qc = useQueryClient()

  // GET /api/staff/paywall/config — treat 404 as "no config yet" by mapping
  // the ApiError into our emptyConfig() seed. Any other failure still surfaces
  // as a warn banner so the operator knows the form below is unsaved local
  // state, not the durable server state.
  const configQuery = useQuery<PaywallConfig>({
    queryKey: ['paywall-config'],
    queryFn: async () => {
      try {
        return await getPaywallConfig()
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return emptyConfig()
        }
        throw err
      }
    },
    retry: false,
  })

  if (configQuery.isLoading) {
    return (
      <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
        Loading paywall config…
      </div>
    )
  }
  if (configQuery.isError || configQuery.data == null) {
    return (
      <div className="px-6 py-10">
        <Banner tone="warn">
          Could not load the paywall config (
          {apiMessage(configQuery.error, 'request failed')}).
        </Banner>
      </div>
    )
  }
  return (
    // Keyed by config_id so per-config local state (form fields, confirm
    // flags, etc.) resets cleanly if the operator ever switches contexts.
    <PaywallEditor
      key={configQuery.data.config_id}
      initialConfig={configQuery.data}
      onConfigInvalidated={() => qc.invalidateQueries({ queryKey: ['paywall-config'] })}
    />
  )
}

// --- Editor (local form state on top of the loaded config) -----------------

interface NewTierFormState {
  tier_id: string
  name: string
  price_id: string
  interval: 'month' | 'year'
}

const EMPTY_NEW_TIER: NewTierFormState = {
  tier_id: '',
  name: '',
  price_id: '',
  interval: 'month',
}

interface NewGrantFormState {
  email: string
  scope_kind: PaywallScopeKind
  scope_id: string
  expires_at: string
}

const EMPTY_NEW_GRANT: NewGrantFormState = {
  email: '',
  scope_kind: 'asset',
  scope_id: '',
  expires_at: '',
}

function PaywallEditor({
  initialConfig,
  onConfigInvalidated,
}: {
  initialConfig: PaywallConfig
  onConfigInvalidated: () => void
}) {
  // The form mirrors the loaded config — operator edits sit here until they
  // click Save, which fires PUT with the whole local state.
  const [enabled, setEnabled] = useState<boolean>(initialConfig.enabled)
  const [provider, setProvider] = useState<PaywallProvider>(initialConfig.provider)
  const [signingSecret, setSigningSecret] = useState<string>(
    initialConfig.signing_secret ?? '',
  )
  const [showSecret, setShowSecret] = useState<boolean>(false)
  const [tiers, setTiers] = useState<PaywallTier[]>(initialConfig.tiers)
  const [newTier, setNewTier] = useState<NewTierFormState>(EMPTY_NEW_TIER)
  const [confirmDeleteConfig, setConfirmDeleteConfig] = useState<boolean>(false)
  // UX-7: rotating the signing secret is destructive (invalidates every
  // unredeemed magic link + breaks Stripe webhook verification). Match the
  // delete-config two-step: arm-then-confirm. The arm step is skipped when
  // the current secret is empty (regenerating "nothing" is harmless).
  const [confirmRegenerateSecret, setConfirmRegenerateSecret] = useState<boolean>(false)
  const [grants, setGrants] = useState<AccessGrant[]>([])
  const [newGrant, setNewGrant] = useState<NewGrantFormState>(EMPTY_NEW_GRANT)
  const [grantDateError, setGrantDateError] = useState<string | null>(null)

  // upsertMut.isSuccess stays true for the entire remaining lifetime of this
  // mutation object -- react-query never resets it on its own -- so a "Saved."
  // banner keyed only on isSuccess would keep showing even after the operator
  // makes further, unsaved edits. Track dirtiness explicitly: any edit to a
  // field the Save payload actually includes clears it; a successful save
  // sets it back.
  const [dirtySinceSave, setDirtySinceSave] = useState(false)

  const upsertMut = useMutation({
    mutationFn: (payload: PaywallConfigInput) => upsertPaywallConfig(payload),
    onSuccess: () => {
      setDirtySinceSave(false)
      onConfigInvalidated()
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => deletePaywallConfig(initialConfig.config_id),
    onSuccess: () => {
      setConfirmDeleteConfig(false)
      onConfigInvalidated()
    },
  })

  const issueGrantMut = useMutation({
    mutationFn: (payload: AccessGrantInput) => issueCompGrant(payload),
    onSuccess: (created) => {
      setGrants((prev) => [created, ...prev])
      setNewGrant(EMPTY_NEW_GRANT)
    },
  })

  const revokeGrantMut = useMutation({
    mutationFn: (grantId: string) => deleteAccessGrant(grantId),
    onSuccess: (_data, grantId) => {
      setGrants((prev) => prev.filter((g) => g.grant_id !== grantId))
    },
  })

  const handleSave = () => {
    const payload: PaywallConfigInput = {
      config_id: initialConfig.config_id,
      station_id: initialConfig.station_id,
      enabled,
      provider,
      tiers,
      signing_secret: signingSecret.trim() === '' ? null : signingSecret,
    }
    upsertMut.mutate(payload)
  }

  const handleAddTier = () => {
    if (!canAddTier(newTier, tiers)) return
    const tier: PaywallTier = {
      tier_id: newTier.tier_id.trim(),
      name: newTier.name.trim(),
      price_id: newTier.price_id.trim(),
      interval: newTier.interval,
    }
    setTiers((prev) => [...prev, tier])
    setNewTier(EMPTY_NEW_TIER)
    setDirtySinceSave(true)
  }

  const handleRemoveTier = (tierId: string) => {
    setTiers((prev) => prev.filter((t) => t.tier_id !== tierId))
    setDirtySinceSave(true)
  }

  const handleIssueGrant = () => {
    if (newGrant.email.trim() === '') return
    setGrantDateError(null)
    // An expiry the browser cannot represent must NOT fall through as null:
    // null means "never expires", so a typo would quietly issue permanent
    // access when the operator asked for a limited grant.
    const expiresAt =
      newGrant.expires_at.trim() === '' ? null : isoFromDate(newGrant.expires_at)
    if (newGrant.expires_at.trim() !== '' && expiresAt === null) {
      setGrantDateError(
        'That expiry date could not be read, so no grant was issued. Re-enter it, or clear it to grant access that never expires.',
      )
      return
    }
    const payload: AccessGrantInput = {
      // The operator-issued grant id is a slug derived from email+scope so
      // the server's slug validator accepts it. The server will replace
      // collisions with a 409; the form surfaces that as a warn banner.
      grant_id: deriveGrantId(newGrant),
      station_id: initialConfig.station_id,
      email: newGrant.email.trim().toLowerCase(),
      scope_kind: newGrant.scope_kind,
      scope_id: newGrant.scope_kind === 'all' ? '' : newGrant.scope_id.trim(),
      granted_via: 'comp',
      expires_at: expiresAt,
    }
    issueGrantMut.mutate(payload)
  }

  const sectionsDisabled = !enabled

  return (
    <div className="space-y-4 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">Subscription paywall</h1>
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Optional, opt-in monetization. Default OFF — when off, every asset is public and
          the paywall code path is inert. Stripe-hosted Checkout only; no card or PAN data
          ever touches CivicCast (DC-4).
        </p>
      </div>

      <ConfigCard
        enabled={enabled}
        provider={provider}
        signingSecret={signingSecret}
        showSecret={showSecret}
        saving={upsertMut.isPending}
        deleting={deleteMut.isPending}
        confirmingDelete={confirmDeleteConfig}
        saveError={
          upsertMut.isError ? apiMessage(upsertMut.error, 'Could not save the config.') : null
        }
        deleteError={
          deleteMut.isError ? apiMessage(deleteMut.error, 'Could not delete the config.') : null
        }
        saved={upsertMut.isSuccess && !dirtySinceSave}
        onToggleEnabled={(next) => {
          setEnabled(next)
          setDirtySinceSave(true)
        }}
        onProviderChange={(next) => {
          setProvider(next)
          setDirtySinceSave(true)
        }}
        onSigningSecretChange={(next) => {
          setSigningSecret(next)
          setDirtySinceSave(true)
        }}
        onToggleShowSecret={() => setShowSecret((v) => !v)}
        confirmingRegenerate={confirmRegenerateSecret}
        onArmRegenerateSecret={() => {
          // No-confirm shortcut when there's nothing to overwrite: empty
          // → fresh-generated is a safe single-click path.
          if (signingSecret.trim() === '') {
            setSigningSecret(generateSigningSecret())
            setDirtySinceSave(true)
            return
          }
          setConfirmRegenerateSecret(true)
        }}
        onCancelRegenerateSecret={() => setConfirmRegenerateSecret(false)}
        onConfirmRegenerateSecret={() => {
          setSigningSecret(generateSigningSecret())
          setDirtySinceSave(true)
          setConfirmRegenerateSecret(false)
        }}
        onSave={handleSave}
        onArmDelete={() => setConfirmDeleteConfig(true)}
        onCancelDelete={() => setConfirmDeleteConfig(false)}
        onConfirmDelete={() => deleteMut.mutate()}
      />

      <TiersSection
        tiers={tiers}
        newTier={newTier}
        sectionsDisabled={sectionsDisabled}
        onNewTierChange={setNewTier}
        onAddTier={handleAddTier}
        onRemoveTier={handleRemoveTier}
      />

      <GrantsSection
        grants={grants}
        newGrant={newGrant}
        sectionsDisabled={sectionsDisabled}
        issuing={issueGrantMut.isPending}
        revoking={revokeGrantMut.isPending ? (revokeGrantMut.variables as string) : null}
        issueError={
          grantDateError ??
          (issueGrantMut.isError
            ? apiMessage(issueGrantMut.error, 'Could not issue the grant.')
            : null)
        }
        onNewGrantChange={setNewGrant}
        onIssueGrant={handleIssueGrant}
        onRevokeGrant={(id) => revokeGrantMut.mutate(id)}
      />
    </div>
  )
}

// --- Config card ------------------------------------------------------------

function ConfigCard({
  enabled,
  provider,
  signingSecret,
  showSecret,
  saving,
  deleting,
  confirmingDelete,
  confirmingRegenerate,
  saveError,
  deleteError,
  saved,
  onToggleEnabled,
  onProviderChange,
  onSigningSecretChange,
  onToggleShowSecret,
  onArmRegenerateSecret,
  onCancelRegenerateSecret,
  onConfirmRegenerateSecret,
  onSave,
  onArmDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  enabled: boolean
  provider: PaywallProvider
  signingSecret: string
  showSecret: boolean
  saving: boolean
  deleting: boolean
  confirmingDelete: boolean
  confirmingRegenerate: boolean
  saveError: string | null
  deleteError: string | null
  saved: boolean
  onToggleEnabled: (next: boolean) => void
  onProviderChange: (next: PaywallProvider) => void
  onSigningSecretChange: (next: string) => void
  onToggleShowSecret: () => void
  onArmRegenerateSecret: () => void
  onCancelRegenerateSecret: () => void
  onConfirmRegenerateSecret: () => void
  onSave: () => void
  onArmDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}) {
  const idToggle = useId()
  const idProvider = useId()
  const idSecret = useId()
  return (
    <section
      aria-label="Paywall config"
      className="space-y-3 rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
    >
      <h2 className="text-sm font-semibold">Config</h2>

      <Banner tone={enabled ? 'ok' : 'info'}>
        {enabled
          ? 'Paywall is ON. Tier-based gating active.'
          : 'Paywall is OFF. All content is public — no subscription required to view.'}
      </Banner>

      <div className="flex flex-wrap items-center gap-3">
        {/* UX-6: visible <label htmlFor> labels the checkbox; aria-label
            removed so AT users don't hear "Enable paywall" twice. */}
        <label htmlFor={idToggle} className="flex items-center gap-2 text-sm">
          <input
            id={idToggle}
            type="checkbox"
            checked={enabled}
            onChange={(e) => onToggleEnabled(e.target.checked)}
          />
          <span className="font-medium">Enable paywall</span>
        </label>
        <span className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Default off (DC-1).
        </span>
      </div>

      <label htmlFor={idProvider} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Provider</span>
        {/* UX-6: aria-label dropped — visible <span> + <label htmlFor>
            already labels this select. */}
        <select
          id={idProvider}
          value={provider}
          onChange={(e) => onProviderChange(e.target.value as PaywallProvider)}
          className="rounded-md px-2 py-1.5"
          style={INPUT_STYLE}
        >
          <option value="stripe">stripe (Stripe-hosted Checkout)</option>
          <option value="mock">mock (contract tests / lab)</option>
        </select>
      </label>

      <label htmlFor={idSecret} className="grid gap-1 text-xs">
        <span style={{ color: 'var(--cc-ink-3)' }}>Signing secret (HMAC)</span>
        <div className="flex flex-wrap items-center gap-2">
          {/* UX-6: aria-label removed (visible <span> labels the field). */}
          <input
            id={idSecret}
            type={showSecret ? 'text' : 'password'}
            value={signingSecret}
            placeholder="base64 secret; rotate via Generate"
            onChange={(e) => onSigningSecretChange(e.target.value)}
            className="flex-1 rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          {/* aria-label kept on Show/Hide and Generate — icon-style buttons
              with text that varies by state need a stable AT name. */}
          <button
            type="button"
            aria-label={showSecret ? 'Hide signing secret' : 'Show signing secret'}
            onClick={onToggleShowSecret}
            className="rounded-md px-2 py-1 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            {showSecret ? 'Hide' : 'Show'}
          </button>
          {/* UX-7: when a non-empty secret is already set, Generate is a
              two-step (arm → confirm) just like Delete. An empty starting
              state skips the confirm — generating into "nothing" is safe. */}
          {confirmingRegenerate ? (
            <>
              <button
                type="button"
                aria-label="Confirm regenerate signing secret"
                onClick={onConfirmRegenerateSecret}
                className="rounded-md px-2 py-1 text-xs font-semibold"
                style={{ background: 'var(--cc-warn-soft)', border: '1px solid var(--cc-warn)' }}
              >
                Confirm regenerate
              </button>
              <button
                type="button"
                onClick={onCancelRegenerateSecret}
                className="rounded-md px-2 py-1 text-xs font-medium"
                style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              aria-label="Generate a new signing secret"
              onClick={onArmRegenerateSecret}
              className="rounded-md px-2 py-1 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Generate new secret
            </button>
          )}
        </div>
        <span className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Rotating this invalidates all unredeemed magic links and breaks webhook
          verification until Stripe is updated.
        </span>
        {confirmingRegenerate && (
          <p role="alert" className="text-xs" style={{ color: 'var(--cc-warn)' }}>
            Confirming will overwrite the current secret. All unredeemed magic
            links stop working and Stripe webhook verification will fail until
            you update Stripe&rsquo;s webhook secret.
          </p>
        )}
      </label>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          aria-label="Save paywall config"
          disabled={saving}
          onClick={onSave}
          className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50"
          style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {confirmingDelete ? (
          <>
            <button
              type="button"
              aria-label="Confirm delete paywall config"
              disabled={deleting}
              onClick={onConfirmDelete}
              className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
              style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
            >
              {deleting ? 'Deleting…' : 'Confirm delete'}
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="rounded-md px-3 py-1.5 text-xs font-medium"
              style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            type="button"
            aria-label="Delete paywall config"
            onClick={onArmDelete}
            className="rounded-md px-3 py-1.5 text-xs font-medium"
            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
          >
            Delete config
          </button>
        )}
      </div>
      {confirmingDelete && (
        <p className="text-xs" style={{ color: 'var(--cc-warn)' }}>
          Confirming will remove the paywall config entirely and disable gating until you
          re-create it.
        </p>
      )}
      {saved && !upsertSaveStale(saveError) && (
        <Banner tone="ok">Saved.</Banner>
      )}
      {saveError && <Banner tone="warn">{saveError}</Banner>}
      {deleteError && <Banner tone="warn">{deleteError}</Banner>}
    </section>
  )
}

// react-query's mutation flips `isSuccess` true on the last successful run
// even after the next attempt errors. We never want to render a "Saved." pill
// next to a "Save failed" banner, so this trivial helper keeps the two states
// disjoint in render (the ok banner hides whenever the warn banner shows).
function upsertSaveStale(saveError: string | null): boolean {
  return saveError != null
}

// --- Tiers section ----------------------------------------------------------

function canAddTier(form: NewTierFormState, existing: PaywallTier[]): boolean {
  if (form.tier_id.trim() === '') return false
  if (form.name.trim() === '') return false
  if (!isStripePriceShape(form.price_id)) return false
  if (existing.some((t) => t.tier_id === form.tier_id.trim())) return false
  return true
}

function TiersSection({
  tiers,
  newTier,
  sectionsDisabled,
  onNewTierChange,
  onAddTier,
  onRemoveTier,
}: {
  tiers: PaywallTier[]
  newTier: NewTierFormState
  sectionsDisabled: boolean
  onNewTierChange: (next: NewTierFormState) => void
  onAddTier: () => void
  onRemoveTier: (tierId: string) => void
}) {
  const idTierId = useId()
  const idName = useId()
  const idPriceId = useId()
  const idIntervalMonth = useId()
  const idIntervalYear = useId()
  const priceOk = newTier.price_id.trim() === '' || isStripePriceShape(newTier.price_id)
  const addDisabled = !canAddTier(newTier, tiers)
  // UX-5: when the paywall is off, the Tiers section is informational
  // ("flip the toggle first"). Make the visual greying honest — mark the
  // subtree `inert` so neither pointer clicks nor tab focus reach the
  // pre-fill controls. The operator can't accumulate state that's lost
  // on navigate-away. React 19 + modern browsers support `inert` natively.
  return (
    <section
      aria-label="Paywall tiers"
      className="space-y-3 rounded-md p-4 text-sm"
      inert={sectionsDisabled}
      aria-disabled={sectionsDisabled || undefined}
      style={{
        background: 'var(--cc-surface)',
        border: '1px solid var(--cc-line)',
        opacity: sectionsDisabled ? 0.6 : 1,
      }}
    >
      <h2 className="text-sm font-semibold">Tiers</h2>
      {sectionsDisabled && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Save with the enable toggle on to manage tiers and grants.
        </p>
      )}
      <div className="overflow-auto">
        <table className="w-full text-sm" aria-label="Existing tiers">
          <thead>
            <tr style={{ color: 'var(--cc-ink-3)' }}>
              <th className="px-2 py-1 text-left">Tier ID</th>
              <th className="px-2 py-1 text-left">Name</th>
              <th className="px-2 py-1 text-left">Stripe price</th>
              <th className="px-2 py-1 text-left">Interval</th>
              <th className="px-2 py-1 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {tiers.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-2 py-2 text-xs"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  No tiers configured yet. Add one below; each tier maps to an existing
                  Stripe price id.
                </td>
              </tr>
            ) : (
              tiers.map((tier) => (
                <tr key={tier.tier_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
                  <td className="cc-mono px-2 py-1 text-xs">{tier.tier_id}</td>
                  <td className="px-2 py-1 text-xs">{tier.name}</td>
                  <td className="cc-mono px-2 py-1 text-xs">{tier.price_id}</td>
                  <td className="cc-mono px-2 py-1 text-xs">{tier.interval}</td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      aria-label={`Remove tier ${tier.tier_id}`}
                      onClick={() => onRemoveTier(tier.tier_id)}
                      className="rounded-md px-2 py-1 text-xs font-medium"
                      style={{
                        background: 'var(--cc-surface)',
                        border: '1px solid var(--cc-line)',
                      }}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div
        aria-label="Add a tier"
        className="space-y-2 rounded-md p-3 text-sm"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        <h3 className="text-sm font-semibold">Add tier</h3>
        {/* UX-6: visible <label htmlFor> labels each input; aria-labels
            dropped to avoid double-announcement. */}
        <div className="grid gap-2 sm:grid-cols-2">
          <label htmlFor={idTierId} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Tier ID (slug)</span>
            <input
              id={idTierId}
              type="text"
              value={newTier.tier_id}
              placeholder="basic"
              onChange={(e) => onNewTierChange({ ...newTier, tier_id: e.target.value })}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
          </label>
          <label htmlFor={idName} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Display name</span>
            <input
              id={idName}
              type="text"
              value={newTier.name}
              placeholder="Basic monthly"
              onChange={(e) => onNewTierChange({ ...newTier, name: e.target.value })}
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            />
          </label>
        </div>
        <label htmlFor={idPriceId} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Stripe price id</span>
          <input
            id={idPriceId}
            type="text"
            value={newTier.price_id}
            placeholder="price_1A2bcDeFgHiJkLmN"
            onChange={(e) => onNewTierChange({ ...newTier, price_id: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
          <span style={{ color: priceOk ? 'var(--cc-ink-3)' : 'var(--cc-warn)' }}>
            Stripe price IDs start with <span className="cc-mono">price_</span>.
          </span>
        </label>
        <fieldset className="grid gap-1 text-xs">
          <legend style={{ color: 'var(--cc-ink-3)' }}>Interval</legend>
          <div className="flex items-center gap-3">
            {/* Radio inputs: the <label htmlFor> wrapping each one carries
                the visible name ("Monthly"/"Yearly") so the input is named
                without an aria-label. */}
            <label htmlFor={idIntervalMonth} className="flex items-center gap-1">
              <input
                id={idIntervalMonth}
                type="radio"
                name="paywall-tier-interval"
                value="month"
                checked={newTier.interval === 'month'}
                onChange={() => onNewTierChange({ ...newTier, interval: 'month' })}
              />
              <span>Monthly</span>
            </label>
            <label htmlFor={idIntervalYear} className="flex items-center gap-1">
              <input
                id={idIntervalYear}
                type="radio"
                name="paywall-tier-interval"
                value="year"
                checked={newTier.interval === 'year'}
                onChange={() => onNewTierChange({ ...newTier, interval: 'year' })}
              />
              <span>Yearly</span>
            </label>
          </div>
        </fieldset>
        <div className="pt-1">
          {/* aria-label kept — the visible text "Add tier" matches, but a
              stable AT name protects against future copy edits. */}
          <button
            type="button"
            aria-label="Add tier"
            disabled={addDisabled}
            onClick={onAddTier}
            className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            Add tier
          </button>
        </div>
      </div>

      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Tier changes are local until you click Save in the Config section above.
      </p>
    </section>
  )
}

// --- Comp grants section ----------------------------------------------------

function deriveGrantId(form: NewGrantFormState): string {
  // Slug shape: comp-<email-local>-<scope-kind>-<scope-id-or-all>-<timestamp>.
  // We strip non-slug chars to keep the server's Slug validator happy; the
  // timestamp suffix avoids collisions when an operator re-issues quickly.
  const stamp = Date.now().toString(36)
  const local = form.email.split('@')[0] ?? 'unknown'
  const scopePart = form.scope_kind === 'all' ? 'all' : form.scope_id.trim() || 'unscoped'
  const raw = `comp-${local}-${form.scope_kind}-${scopePart}-${stamp}`
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '')
    .slice(0, 120)
}

// Returns null rather than throwing when the date cannot be represented.
// Two ways that happens: the caller passes text this never validated (the
// helper interpolates its argument straight into a date string), and the
// end-of-day offset itself overflows — a `<input type="date">` accepts up to
// 275760-09-13, but the largest representable instant is midnight on that
// day, so appending T23:59:59Z pushes it out of range. `toISOString()` on the
// resulting Invalid Date raises RangeError while the payload is being built,
// outside any try/catch, which would make "Issue grant" silently do nothing.
function isoFromDate(yyyyMmDd: string): string | null {
  // Treat the date input as end-of-day UTC so grants "expire on Dec 1" mean
  // the whole of Dec 1 is still valid. The server stores ISO; the form
  // surface is a calendar date.
  const d = new Date(`${yyyyMmDd}T23:59:59Z`)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

function GrantsSection({
  grants,
  newGrant,
  sectionsDisabled,
  issuing,
  revoking,
  issueError,
  onNewGrantChange,
  onIssueGrant,
  onRevokeGrant,
}: {
  grants: AccessGrant[]
  newGrant: NewGrantFormState
  sectionsDisabled: boolean
  issuing: boolean
  revoking: string | null
  issueError: string | null
  onNewGrantChange: (next: NewGrantFormState) => void
  onIssueGrant: () => void
  onRevokeGrant: (grantId: string) => void
}) {
  const idEmail = useId()
  const idScopeKind = useId()
  const idScopeId = useId()
  const idExpires = useId()
  const showScopeId = newGrant.scope_kind !== 'all'
  const canIssue = newGrant.email.trim() !== '' && !issuing
  // A revoke cuts a real person's access immediately, unlike the read-only
  // rows around it -- match the arm-then-confirm pattern used by Delete
  // config / Regenerate secret instead of firing on the first click.
  const [armedRevokeGrantId, setArmedRevokeGrantId] = useState<string | null>(null)
  // UX-5: same inert/aria-disabled treatment as the Tiers section — the
  // greyed look now reflects "you can't interact here" honestly.
  return (
    <section
      aria-label="Comp access grants"
      className="space-y-3 rounded-md p-4 text-sm"
      inert={sectionsDisabled}
      aria-disabled={sectionsDisabled || undefined}
      style={{
        background: 'var(--cc-surface)',
        border: '1px solid var(--cc-line)',
        opacity: sectionsDisabled ? 0.6 : 1,
      }}
    >
      <h2 className="text-sm font-semibold">Comp access grants</h2>
      {/* UX-8: the "server-side grant browsing is a follow-up" caveat used
          to live in a <table title="…"> attribute that vanished from the
          visual as soon as the operator issued one grant in-session. Move
          it to a persistent helper line under the heading so the limitation
          stays visible after the table fills. */}
      <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
        Showing grants issued in this session. Server-side grant history is a
        follow-up.
      </p>
      {sectionsDisabled && (
        <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>
          Save with the enable toggle on to manage tiers and grants.
        </p>
      )}
      <div className="overflow-auto">
        <table
          className="w-full text-sm"
          aria-label="Recently issued grants"
        >
          <thead>
            <tr style={{ color: 'var(--cc-ink-3)' }}>
              <th className="px-2 py-1 text-left">Email</th>
              <th className="px-2 py-1 text-left">Scope</th>
              <th className="px-2 py-1 text-left">Expires</th>
              <th className="px-2 py-1 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {grants.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="px-2 py-2 text-xs"
                  style={{ color: 'var(--cc-ink-3)' }}
                >
                  No grants issued in this session yet.
                </td>
              </tr>
            ) : (
              grants.map((grant) => {
                const scope =
                  grant.scope_kind === 'all'
                    ? 'all content'
                    : `${grant.scope_kind}: ${grant.scope_id || '(none)'}`
                return (
                  <tr key={grant.grant_id} style={{ borderTop: '1px solid var(--cc-line)' }}>
                    <td className="cc-mono px-2 py-1 text-xs">{grant.email}</td>
                    <td className="px-2 py-1 text-xs">{scope}</td>
                    <td className="cc-mono px-2 py-1 text-xs">
                      {grant.expires_at ?? 'never'}
                    </td>
                    <td className="px-2 py-1 text-right">
                      {armedRevokeGrantId === grant.grant_id ? (
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            aria-label={`Confirm revoke grant ${grant.grant_id}`}
                            disabled={revoking === grant.grant_id}
                            onClick={() => {
                              setArmedRevokeGrantId(null)
                              onRevokeGrant(grant.grant_id)
                            }}
                            className="rounded-md px-2 py-1 text-xs font-semibold disabled:opacity-50"
                            style={{ background: 'var(--cc-err-soft)', border: '1px solid var(--cc-err)' }}
                          >
                            {revoking === grant.grant_id ? 'Revoking…' : 'Confirm revoke'}
                          </button>
                          <button
                            type="button"
                            aria-label={`Cancel revoke grant ${grant.grant_id}`}
                            onClick={() => setArmedRevokeGrantId(null)}
                            className="rounded-md px-2 py-1 text-xs font-medium"
                            style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          aria-label={`Revoke grant ${grant.grant_id}`}
                          disabled={revoking === grant.grant_id}
                          onClick={() => setArmedRevokeGrantId(grant.grant_id)}
                          className="rounded-md px-2 py-1 text-xs font-medium disabled:opacity-50"
                          style={{
                            background: 'var(--cc-surface)',
                            border: '1px solid var(--cc-line)',
                          }}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div
        aria-label="Issue comp grant"
        className="space-y-2 rounded-md p-3 text-sm"
        style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
      >
        <h3 className="text-sm font-semibold">Issue comp grant</h3>
        {/* UX-6: aria-labels dropped — each input has a visible
            <label htmlFor> with semantically identical text. */}
        <label htmlFor={idEmail} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Email</span>
          <input
            id={idEmail}
            type="email"
            value={newGrant.email}
            placeholder="viewer@example.gov"
            onChange={(e) => onNewGrantChange({ ...newGrant, email: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label htmlFor={idScopeKind} className="grid gap-1 text-xs">
            <span style={{ color: 'var(--cc-ink-3)' }}>Scope kind</span>
            <select
              id={idScopeKind}
              value={newGrant.scope_kind}
              onChange={(e) =>
                onNewGrantChange({
                  ...newGrant,
                  scope_kind: e.target.value as PaywallScopeKind,
                })
              }
              className="rounded-md px-2 py-1.5"
              style={INPUT_STYLE}
            >
              <option value="asset">asset</option>
              <option value="series">series</option>
              <option value="all">all (catch-all)</option>
            </select>
          </label>
          {showScopeId && (
            <label htmlFor={idScopeId} className="grid gap-1 text-xs">
              <span style={{ color: 'var(--cc-ink-3)' }}>Scope ID</span>
              <input
                id={idScopeId}
                type="text"
                value={newGrant.scope_id}
                placeholder="asset-2026-01 / series-council"
                onChange={(e) => onNewGrantChange({ ...newGrant, scope_id: e.target.value })}
                className="rounded-md px-2 py-1.5"
                style={INPUT_STYLE}
              />
            </label>
          )}
        </div>
        <label htmlFor={idExpires} className="grid gap-1 text-xs">
          <span style={{ color: 'var(--cc-ink-3)' }}>Expires at (optional)</span>
          <input
            id={idExpires}
            type="date"
            value={newGrant.expires_at}
            onChange={(e) => onNewGrantChange({ ...newGrant, expires_at: e.target.value })}
            className="rounded-md px-2 py-1.5"
            style={INPUT_STYLE}
          />
        </label>
        <div className="pt-1">
          {/* aria-label kept on action buttons for a stable AT name. */}
          <button
            type="button"
            aria-label="Issue comp grant"
            disabled={!canIssue}
            onClick={onIssueGrant}
            className="rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--cc-brand)', color: 'var(--cc-brand-ink)' }}
          >
            {issuing ? 'Issuing…' : 'Issue grant'}
          </button>
        </div>
        {issueError && <Banner tone="warn">{issueError}</Banner>}
      </div>
    </section>
  )
}

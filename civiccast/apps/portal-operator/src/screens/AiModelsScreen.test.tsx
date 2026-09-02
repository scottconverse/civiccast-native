// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type {
  AiModelAvailability,
  AiModelConfiguration,
  FeatureModelAvailability,
  FeatureModelRegistry,
  ModelTier,
  StaffIdentityResponse,
} from '../types/api.generated'

afterEach(cleanup)

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 0, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getStaffIdentity: vi.fn(),
  getAiModelConfiguration: vi.fn(),
  getAiModelAvailability: vi.fn(),
  getSystemHealth: vi.fn(),
  selectFeatureModel: vi.fn(),
  getProviderKeyStatus: vi.fn(),
  saveProviderKey: vi.fn(),
}))

import {
  getAiModelAvailability,
  getAiModelConfiguration,
  getProviderKeyStatus,
  getStaffIdentity,
  getSystemHealth,
  saveProviderKey,
  selectFeatureModel,
} from '../api/client'
import { AiModelsScreen, FeatureModelCard } from './AiModelsScreen'

function identity(roles: string[]): StaffIdentityResponse {
  return { operator_id: 'dana', operator_display_name: 'Dana', roles } as StaffIdentityResponse
}

function tier(overrides: Partial<ModelTier> = {}): ModelTier {
  return {
    key: 'gemma4-12b-ollama',
    provider: 'ollama',
    model_id: 'gemma4:12b',
    cost_per_token_usd: 0,
    latency_p95_ms: 4200,
    private: true,
    requires_network: false,
    min_ram_gb: 16,
    license_url: null,
    notes: 'Local Gemma 4 12B QAT.',
    ...overrides,
  }
}

const SUMMARY_TIERS: ModelTier[] = [
  tier(),
  tier({ key: 'gemma4-e4b-ollama', model_id: 'gemma4:e4b', min_ram_gb: 8 }),
  tier({
    key: 'gemma4-31b-cloud',
    provider: 'ollama-cloud',
    model_id: 'gemma4:31b-cloud',
    cost_per_token_usd: 1e-7,
    private: false,
    requires_network: true,
    notes: 'Ollama Cloud — metered.',
  }),
]

function registry(overrides: Partial<FeatureModelRegistry> = {}): FeatureModelRegistry {
  return {
    feature: 'summary',
    default_key: 'gemma4-12b-ollama',
    adaptive_default: true,
    available_tiers: SUMMARY_TIERS,
    operator_selected_key: null,
    effective_model_key: 'gemma4-12b-ollama',
    ...overrides,
  }
}

function config(): AiModelConfiguration {
  return {
    created_at: '2026-06-17T00:00:00Z',
    updated_at: '2026-06-17T00:00:00Z',
    features: {
      captions: {
        feature: 'captions',
        default_key: 'whisper-large-v3-faster',
        adaptive_default: false,
        available_tiers: [
          tier({
            key: 'whisper-large-v3-faster',
            provider: 'external',
            model_id: 'whisper-large-v3',
            min_ram_gb: 8,
          }),
        ],
        operator_selected_key: null,
        effective_model_key: 'whisper-large-v3-faster',
      },
      summary: registry(),
      translation: {
        feature: 'translation',
        default_key: 'translategemma-4b-ollama',
        adaptive_default: false,
        available_tiers: [
          tier({ key: 'translategemma-4b-ollama', model_id: 'translategemma:4b', min_ram_gb: 8 }),
        ],
        operator_selected_key: null,
        effective_model_key: 'translategemma-4b-ollama',
      },
    },
  }
}

// --- pure-view tests (no QueryClient) ---------------------------------------

describe('FeatureModelCard', () => {
  it('shows the model key, Local band, free cost, and on-device privacy for a local default', () => {
    const { container } = render(<FeatureModelCard registry={registry()} canWrite={false} onSelect={() => {}} />)
    const text = container.textContent ?? ''
    expect(text).toContain('Summary')
    expect(text).toContain('gemma4-12b-ollama')
    expect(text).toContain('Local')
    expect(text).toContain('Free (local)')
    expect(text).toContain('On-device — private')
  })

  it('the translation card says where the selection actually shows up', () => {
    // This copy went stale once already: it carried a "not connected yet —
    // no published caption track uses a translated language" warning for
    // months after recorded-Spanish captions connected it, telling the
    // operator the opposite of the truth. Pin the claim so a future change
    // to the pipeline has to come past this test.
    const { container } = render(
      <FeatureModelCard
        registry={registry({ feature: 'translation' })}
        canWrite={false}
        onSelect={() => {}}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).not.toContain('Not connected yet')
    expect(text).toContain('approved English')
    expect(text).toContain('Spanish')
    expect(text).toContain('caption review')
  })

  it('a non-translation card carries no translation explainer', () => {
    const { container } = render(
      <FeatureModelCard registry={registry()} canWrite={false} onSelect={() => {}} />,
    )
    expect(container.textContent ?? '').not.toContain('approved English')
  })

  it('renders a select with one option per available tier', () => {
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    expect(select.options.length).toBe(3)
    expect(select.value).toBe('gemma4-12b-ollama')
  })

  it('disables the select when the operator cannot write', () => {
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite={false} onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    expect(select.disabled).toBe(true)
  })

  it('selecting a LOCAL tier calls onSelect immediately (no consent needed)', () => {
    const onSelect = vi.fn()
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={onSelect} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'gemma4-e4b-ollama' } })
    expect(onSelect).toHaveBeenCalledWith('summary', 'gemma4-e4b-ollama', false)
  })

  it('a CLOUD tier requires the TOS checkbox before it can be applied', () => {
    const onSelect = vi.fn()
    const { getByLabelText, getByText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={onSelect} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    // pick the metered cloud tier — onSelect must NOT fire yet (consent pending)
    fireEvent.change(select, { target: { value: 'gemma4-31b-cloud' } })
    expect(onSelect).not.toHaveBeenCalled()
    // the consent checkbox + an Apply button appear
    const consent = getByLabelText(/accept.*per-token/i) as HTMLInputElement
    const apply = getByText(/Apply cloud model/i) as HTMLButtonElement
    expect(apply.disabled).toBe(true)
    // checking consent enables Apply
    fireEvent.click(consent)
    expect(apply.disabled).toBe(false)
    fireEvent.click(apply)
    expect(onSelect).toHaveBeenCalledWith('summary', 'gemma4-31b-cloud', true)
  })

  it('U1: surfaces the effective model latency on the card', () => {
    const { container } = render(
      <FeatureModelCard registry={registry()} canWrite={false} onSelect={() => {}} />,
    )
    const text = container.textContent ?? ''
    // The effective tier is on-box (provider: 'ollama'), so the card renders the
    // CPU-only-caveated form (tierLatencyLabel, field evidence 2026-08-29), not a
    // bare "≈X s typical" number a real CPU generation cannot reliably hit.
    expect(text).toContain('Latency')
    expect(text).toContain('CPU-only')
  })

  it('U1: staging a non-effective tier renders that tier\'s latency/privacy BEFORE commit', () => {
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    // stage the cloud tier (cloud does NOT auto-apply — preview must show first)
    fireEvent.change(select, { target: { value: 'gemma4-31b-cloud' } })
    const preview = getByLabelText('Summary staged selection')
    const text = preview.textContent ?? ''
    expect(text).toContain('gemma4-31b-cloud')
    // the cloud tier's latency (4200 ms in the fixture) and privacy are visible
    expect(text).toContain('4.2 s')
    expect(text).toContain('Sent to cloud provider')
  })

  it('U2: a positive sub-cent rate never renders as $0.0/token or Free on the option', () => {
    const reg = registry({
      available_tiers: [
        tier(),
        tier({
          key: 'tiny-rate-cloud',
          provider: 'ollama-cloud',
          private: false,
          requires_network: true,
          cost_per_token_usd: 5e-8,
        }),
      ],
    })
    const { getByLabelText } = render(
      <FeatureModelCard registry={reg} canWrite onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    const tinyOption = Array.from(select.options).find((o) => o.value === 'tiny-rate-cloud')!
    expect(tinyOption.textContent).not.toContain('$0.0/token')
    expect(tinyOption.textContent).not.toContain('Free')
    // 5e-8 → $0.000000050/token, ~$0.050 / 1M tokens
    expect(tinyOption.textContent).toContain('/token')
    expect(tinyOption.textContent).toContain('1M tokens')
  })

  it('U3: each option carries its RAM requirement text (needs N GB)', () => {
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    const twelveB = Array.from(select.options).find((o) => o.value === 'gemma4-12b-ollama')!
    expect(twelveB.textContent).toContain('needs 16 GB')
  })

  it('U3: disables an option whose RAM requirement exceeds the box RAM', () => {
    const { getByLabelText } = render(
      <FeatureModelCard registry={registry()} canWrite boxRamGb={8} onSelect={() => {}} />,
    )
    const select = getByLabelText('Summary model') as HTMLSelectElement
    const twelveB = Array.from(select.options).find((o) => o.value === 'gemma4-12b-ollama')!
    const e4b = Array.from(select.options).find((o) => o.value === 'gemma4-e4b-ollama')!
    expect(twelveB.disabled).toBe(true)
    expect(twelveB.textContent).toContain('exceeds this box')
    expect(e4b.disabled).toBe(false)
  })

  it('U5: shows the tier notes as a secondary line on the card', () => {
    const reg = registry({
      effective_model_key: 'gemma4-12b-ollama',
      available_tiers: [tier({ notes: 'Local Gemma 4 12B QAT — long-context default.' })],
    })
    const { container } = render(
      <FeatureModelCard registry={reg} canWrite={false} onSelect={() => {}} />,
    )
    expect(container.textContent ?? '').toContain('long-context default')
  })

  it('U5: renders a license/provider-terms link inside the cloud consent band', () => {
    const reg = registry({
      available_tiers: [
        tier(),
        tier({
          key: 'gemma4-31b-cloud',
          provider: 'ollama-cloud',
          private: false,
          requires_network: true,
          cost_per_token_usd: 1e-7,
          license_url: 'https://ollama.com/terms',
        }),
      ],
    })
    const { getByLabelText, getAllByRole } = render(
      <FeatureModelCard registry={reg} canWrite onSelect={() => {}} />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    const links = getAllByRole('link') as HTMLAnchorElement[]
    expect(links.some((a) => a.getAttribute('href') === 'https://ollama.com/terms')).toBe(true)
  })

  it('U7: the cloud consent band is a role=group and Apply is aria-describedby the consent label', () => {
    const { getByLabelText, getByText } = render(
      <FeatureModelCard registry={registry()} canWrite onSelect={() => {}} />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    const group = getByLabelText('Summary cloud model consent')
    expect(group.getAttribute('role')).toBe('group')
    const apply = getByText(/Apply cloud model/i) as HTMLButtonElement
    const describedBy = apply.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    // the id points at the consent label that explains why Apply is disabled
    expect(apply.disabled).toBe(true)
    expect(document.getElementById(describedBy!)?.textContent).toMatch(/accept.*per-token/i)
  })

  it('U4/M3: renders a warn-tone availability hint when the effective model is absent', () => {
    const { container } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite={false}
        onSelect={() => {}}
        availability={{
          feature: 'summary',
          effective_model_key: 'gemma4-12b-ollama',
          band: 'local',
          requires_network: false,
          runtime_reachable: true,
          model_present: false,
        }}
      />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('Availability:')
    expect(text).toContain('Not installed')
    expect(text).toContain('feature will defer')
  })

  // --- Finding 1 (UI half): provider API-key field for a staged hosted tier ----
  it('Finding1: offers a write-only API-key field when a staged cloud tier has NO stored key', () => {
    const { getByLabelText, queryByLabelText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite
        onSelect={() => {}}
        credentialStoredByProvider={{ 'ollama-cloud': false }}
        onSaveProviderKey={() => {}}
      />,
    )
    // no key field before a cloud tier is staged
    expect(queryByLabelText(/provider API key/i)).toBeNull()
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    const keyField = getByLabelText(/provider API key/i) as HTMLInputElement
    // write-only: a password field, never seeded with a value
    expect(keyField.type).toBe('password')
    expect(keyField.value).toBe('')
  })

  it('Finding1: Save key calls onSaveProviderKey with the provider + typed key, then clears it', () => {
    const onSaveProviderKey = vi.fn()
    const { getByLabelText, getByText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite
        onSelect={() => {}}
        credentialStoredByProvider={{ 'ollama-cloud': false }}
        onSaveProviderKey={onSaveProviderKey}
      />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    const keyField = getByLabelText(/provider API key/i) as HTMLInputElement
    const save = getByText('Save key') as HTMLButtonElement
    // empty key → Save disabled
    expect(save.disabled).toBe(true)
    fireEvent.change(keyField, { target: { value: 'sk-test-123' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    expect(onSaveProviderKey).toHaveBeenCalledWith('ollama-cloud', 'sk-test-123')
    // the buffer is cleared after a save (never lingers in the DOM)
    expect(keyField.value).toBe('')
  })

  it('Finding1: hides the key field once a key IS stored for the staged provider', () => {
    const { getByLabelText, queryByLabelText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite
        onSelect={() => {}}
        credentialStoredByProvider={{ 'ollama-cloud': true }}
        onSaveProviderKey={() => {}}
      />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    // consent band is present, but no key field (a key is already stored)
    expect(getByLabelText('Summary cloud model consent')).toBeTruthy()
    expect(queryByLabelText(/provider API key/i)).toBeNull()
  })

  it('Finding1: never offers a key field for a LOCAL tier (no API key applies)', () => {
    const { getByLabelText, queryByLabelText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite
        onSelect={() => {}}
        credentialStoredByProvider={{ 'ollama-cloud': false }}
        onSaveProviderKey={() => {}}
      />,
    )
    // stage a local tier — no consent band, no key field
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-e4b-ollama' } })
    expect(queryByLabelText(/provider API key/i)).toBeNull()
  })

  it('Finding1: a read-only operator never sees the key field even with no stored key', () => {
    const { getByLabelText, queryByLabelText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite={false}
        onSelect={() => {}}
        credentialStoredByProvider={{ 'ollama-cloud': false }}
        onSaveProviderKey={() => {}}
      />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    expect(queryByLabelText(/provider API key/i)).toBeNull()
  })

  it('Finding1: an UNKNOWN credential status (no map entry) does not force the field on', () => {
    const { getByLabelText, queryByLabelText } = render(
      <FeatureModelCard
        registry={registry()}
        canWrite
        onSelect={() => {}}
        credentialStoredByProvider={{}}
        onSaveProviderKey={() => {}}
      />,
    )
    fireEvent.change(getByLabelText('Summary model'), { target: { value: 'gemma4-31b-cloud' } })
    expect(queryByLabelText(/provider API key/i)).toBeNull()
  })
})

// --- container tests (with QueryClient) -------------------------------------

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AiModelsScreen />
    </QueryClientProvider>,
  )
}

function availability(
  features: Record<string, FeatureModelAvailability> = {},
): AiModelAvailability {
  return { features }
}

function featureAvailability(
  overrides: Partial<FeatureModelAvailability> = {},
): FeatureModelAvailability {
  return {
    feature: 'summary',
    effective_model_key: 'gemma4-12b-ollama',
    band: 'local',
    requires_network: false,
    runtime_reachable: true,
    model_present: true,
    ...overrides,
  }
}

describe('AiModelsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getAiModelConfiguration).mockResolvedValue(config())
    vi.mocked(getAiModelAvailability).mockResolvedValue(availability())
    // 25 GB box by default (matches the gate hardware) — 16 GB tiers fit.
    vi.mocked(getSystemHealth).mockResolvedValue({
      latest_resource_sample: { sampled_at: '2026-06-18T00:00:00Z', ram_total_gb: 25 },
    } as unknown as Awaited<ReturnType<typeof getSystemHealth>>)
    vi.mocked(selectFeatureModel).mockResolvedValue(registry())
    // Default: a key IS stored for both providers, so no key field is offered
    // unless a test explicitly says the provider has none.
    vi.mocked(getProviderKeyStatus).mockImplementation((provider) =>
      Promise.resolve({ provider, stored: true }),
    )
    vi.mocked(saveProviderKey).mockImplementation((provider) =>
      Promise.resolve({ provider, stored: true }),
    )
  })

  it('shows the access banner for a non-privileged role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['records_clerk']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin or meeting operator/i)).toBeTruthy()
  })

  it('renders all three feature cards read-only for a meeting operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByLabelText } = renderScreen()
    const captions = (await findByLabelText('Captions model')) as HTMLSelectElement
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    const translation = (await findByLabelText('Translation model')) as HTMLSelectElement
    expect(captions.disabled).toBe(true)
    expect(summary.disabled).toBe(true)
    expect(translation.disabled).toBe(true)
  })

  it('lets a setup admin select a local model via the dropdown', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByLabelText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    expect(summary.disabled).toBe(false)
    fireEvent.change(summary, { target: { value: 'gemma4-e4b-ollama' } })
    await waitFor(() =>
      expect(vi.mocked(selectFeatureModel)).toHaveBeenCalledWith('summary', {
        model_key: 'gemma4-e4b-ollama',
      }),
    )
  })

  it('does NOT POST a cloud selection until the TOS box is checked, then does', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    const { findByLabelText, getByText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    fireEvent.change(summary, { target: { value: 'gemma4-31b-cloud' } })
    expect(vi.mocked(selectFeatureModel)).not.toHaveBeenCalled()
    const consent = (await findByLabelText(/accept.*per-token/i)) as HTMLInputElement
    fireEvent.click(consent)
    fireEvent.click(getByText(/Apply cloud model/i))
    await waitFor(() =>
      // F3/Q3/E4: consent is now sent to the server for the cloud selection.
      expect(vi.mocked(selectFeatureModel)).toHaveBeenCalledWith('summary', {
        model_key: 'gemma4-31b-cloud',
        consent_accepted: true,
      }),
    )
  })

  it('renders a tone=warn availability hint when the effective model is not installed (U4/Q2/M3)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAiModelAvailability).mockResolvedValue(
      availability({
        summary: featureAvailability({ model_present: false }),
      }),
    )
    const { findByText } = renderScreen()
    expect(await findByText(/Not installed/i)).toBeTruthy()
    expect(await findByText(/feature will defer/i)).toBeTruthy()
  })

  it('renders an "Ollama unavailable" hint when the runtime is unreachable (U4/Q2/M3)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAiModelAvailability).mockResolvedValue(
      availability({
        summary: featureAvailability({ runtime_reachable: false }),
      }),
    )
    const { findByText } = renderScreen()
    expect(await findByText(/Ollama unavailable/i)).toBeTruthy()
  })

  it('shows NO availability hint when the effective model is present and reachable', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAiModelAvailability).mockResolvedValue(
      availability({
        summary: featureAvailability({ model_present: true, runtime_reachable: true }),
      }),
    )
    const { findByLabelText, queryByText } = renderScreen()
    await findByLabelText('Summary model')
    expect(queryByText(/Availability:/i)).toBeNull()
  })

  it('still renders the cards when the availability probe fails (best-effort)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAiModelAvailability).mockRejectedValue(new Error('probe down'))
    const { findByLabelText, queryByText } = renderScreen()
    expect(await findByLabelText('Summary model')).toBeTruthy()
    expect(queryByText(/Availability:/i)).toBeNull()
  })

  it('U3: gates 16 GB tiers on an 8 GB box (box RAM from system health)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getSystemHealth).mockResolvedValue({
      latest_resource_sample: { sampled_at: '2026-06-18T00:00:00Z', ram_total_gb: 8 },
    } as unknown as Awaited<ReturnType<typeof getSystemHealth>>)
    const { findByLabelText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    await waitFor(() => {
      const twelveB = Array.from(summary.options).find((o) => o.value === 'gemma4-12b-ollama')!
      expect(twelveB.disabled).toBe(true)
    })
  })

  it('U3: does NOT gate any tier when box RAM is unknown (health probe fails)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getSystemHealth).mockRejectedValue(new Error('health down'))
    const { findByLabelText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    const twelveB = Array.from(summary.options).find((o) => o.value === 'gemma4-12b-ollama')!
    expect(twelveB.disabled).toBe(false)
  })

  it('Finding1: a setup admin can save a provider key from a staged cloud tier (calls the client)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    // no ollama-cloud key stored yet → the key field must appear when the tier is staged
    vi.mocked(getProviderKeyStatus).mockImplementation((provider) =>
      Promise.resolve({ provider, stored: provider === 'ollama-cloud' ? false : true }),
    )
    const { findByLabelText, getByText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    fireEvent.change(summary, { target: { value: 'gemma4-31b-cloud' } })
    const keyField = (await findByLabelText(/provider API key/i)) as HTMLInputElement
    fireEvent.change(keyField, { target: { value: 'sk-live-xyz' } })
    fireEvent.click(getByText('Save key'))
    await waitFor(() =>
      expect(vi.mocked(saveProviderKey)).toHaveBeenCalledWith('ollama-cloud', {
        api_key: 'sk-live-xyz',
      }),
    )
  })

  it('Finding1: does NOT fetch provider key status for a read-only operator', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByLabelText } = renderScreen()
    await findByLabelText('Summary model')
    expect(vi.mocked(getProviderKeyStatus)).not.toHaveBeenCalled()
  })

  it('Finding1: no key field is offered when the provider key IS already stored', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    // default beforeEach mock returns stored:true for both providers
    const { findByLabelText, queryByLabelText } = renderScreen()
    const summary = (await findByLabelText('Summary model')) as HTMLSelectElement
    fireEvent.change(summary, { target: { value: 'gemma4-31b-cloud' } })
    await findByLabelText('Summary cloud model consent')
    expect(queryByLabelText(/provider API key/i)).toBeNull()
  })
})

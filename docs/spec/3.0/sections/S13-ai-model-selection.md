# S13 — AI Model Selection Surface & Operator Control

> **Status:** SPEC FOR REVIEW — do not begin implementation until approved.
> **Date:** 2026-06-13  
> **Scope:** Per-feature model registry + three-tier selection surface (local Ollama → Ollama Cloud → OpenRouter).  
> **Disposition:** Net-new wiring (models exist; operator control surface does not).  
> **Proof rung goal:** Contract (unit/API tests) → Lab (release-gates verified) → Machine (soak with model fallback).

---

## 1. Goal & PEG automation rationale

**What incumbent PEG platform does:**
The incumbent PEG workflow hard-wires model choices: cloud cloud telemetry for captions (~$12/hr metered), cloud for translation and summary (7 languages live, 72 VOD). A station has no model choice — it buys the appliance, the cloud bill follows.

**The gap we close (MASTER §4.10, §8):**  
"Operator always chooses" is a hard principle that **is not built today.** CivicCast currently has:
- **Summary:** hard-coded `gemma4:e4b` (local Ollama only); no selection UI; no 12B adaptive default.
- **Translation:** hard-coded `translategemma:4b` (local Ollama); alternates documented but unwired (MADLAD-400).
- **Captions:** hard-coded `whisper-large-v3` (faster-whisper); no selection surface.
- **AI runtime:** loopback-only enforcement (no cloud providers wired).

**S13 delivers:**
1. Per-feature `ModelSelection` registry exposing three tiers:
   - **Tier 1 (LOCAL):** Ollama (e4b/12b/26b + Apache alternates MADLAD-400/Mistral).
   - **Tier 2 (HOSTED):** Ollama Cloud (`gemma4:31b-cloud`).
   - **Tier 3 (FRONTIER):** OpenRouter mid-tier (Gemini 2.5 Flash / Haiku 4.5 / GPT-5 mini).
2. Adaptive DEFAULT: `gemma4:12b` QAT for summary on ≥16GB RAM **with a real GPU present**; `gemma4:e4b` everywhere else, including every CPU-only box regardless of RAM (MRCR: 25.4 → 43.4, ~2× long-context gain when 12B is actually reachable — see §3.2's amendment note for the CPU-only field evidence that added the GPU gate).
3. Operator selection surface (console + API) with cost/latency/privacy tradeoff UI.
4. DEFAULT stays local (zero cloud fee); hosted tiers (Ollama Cloud + OpenRouter) ship **functional** (D13) — default OFF, operator opts in and accepts per-token cost — not stubbed.
5. Release-gate wiring respects operator choice (not pinned).

**Parity claim:** CivicCast 3.0 **restores operator agency** over the AI stack (incumbent PEG platform removes it via cloud lock-in).

---

## 2. Current state (grounded to code)

| Feature | Current | Status | Notes |
|---------|---------|--------|-------|
| **Summary** | `gemma4:e4b` | Hard-coded | `civiccast/summary/ollama.py:19` `_SUMMARY_MODEL_TAG = "gemma4:e4b"` |
| **Translation** | `translategemma:4b` | Hard-coded | `civiccast/translate/ollama.py:17` registry stub exists but unwired |
| **Captions** | `whisper-large-v3` | Hard-coded | `civiccast/captions/runtime.py:51` no selection surface |
| **AI Runtime** | Loopback-only | Enforced | `civiccast/ai_runtime/ollama_client.py:113-122` restricts to 127.0.0.1 |
| **Model bundle** | 3 required | Pinned | `civiccast/installer/model_bundle.py:44-66` hardcoded trio |
| **Release gates** | Per-runtime | Contract-tested | `civiccast/ai_quality/release_gates.py:90-136` validates WER/BLEU |
| **Ollama client** | Generic HTTP | Reusable | `civiccast/ai_runtime/ollama_client.py:32-69` solid foundation |

**Net-new work:**
- `ModelSelection` entity (registry key, tier, cost, latency, privacy tags)
- Per-feature model selection API (`/api/staff/ai-models/{feature}`)
- Operator console UI (settings card, dropdown)
- Adaptive default logic in installer (`doctor`)
- Release-gate wiring respects operator choice (not pinned)

---

## 3. Entities / data model & migrations

### 3.1 Net-new entity: `ModelSelection`

**Location:** `civiccast/ai_models/models.py` (new module)

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, Annotated


class ModelTier(BaseModel):
    key: Annotated[str, Field(min_length=1, max_length=120)]
    provider: Literal["ollama", "ollama-cloud", "openrouter", "external"]
    model_id: Annotated[str, Field(min_length=1, max_length=120)]
    cost_per_token_usd: float = 0.0
    latency_p95_ms: Annotated[int, Field(ge=0)] = 0
    private: bool = True
    requires_network: bool = False
    min_ram_gb: Annotated[int, Field(ge=1)] = 8
    license_url: Annotated[str | None, Field(default=None, max_length=200)]
    notes: Annotated[str, Field(max_length=400)]


class FeatureModelRegistry(BaseModel):
    feature: Literal["captions", "summary", "translation"]
    default_key: Annotated[str, Field(min_length=1, max_length=120)]
    adaptive_default: bool = False
    available_tiers: list[ModelTier]
    operator_selected_key: Annotated[str | None, Field(default=None, max_length=120)] = None

    @property
    def effective_model_key(self) -> str:
        return self.operator_selected_key or self.default_key


class AiModelConfiguration(BaseModel):
    created_at: datetime
    updated_at: datetime
    features: dict[str, FeatureModelRegistry]
```

#### 3.1.1 Model identifier mapping (D4)

`ModelTier.model_id` is the Ollama/runtime **tag** (what the runtime loads); `ModelTier.key`
is the registry **slug** (stable selection identifier, what the operator/API references). The
canonical mapping S13 carries:

| Feature | `ModelTier.key` (registry slug) | `ModelTier.model_id` (runtime tag) | Provider |
|---------|---------------------------------|------------------------------------|----------|
| Summary (default ≥16GB) | `gemma4-12b-ollama` | `gemma4:12b` | ollama |
| Summary (fallback 8GB) | `gemma4-e4b-ollama` | `gemma4:e4b` | ollama |
| Summary (hosted) | `gemma4-31b-cloud` | `gemma4:31b-cloud` | ollama-cloud |
| Translation | `translategemma-4b-ollama` | `translategemma:4b` | ollama |
| Captions | `whisper-large-v3-faster` | `whisper-large-v3` | external |

**Translation is `translategemma:4b` everywhere** (runtime tag); never `gemma4:4b`.

### 3.2 Adaptive default logic

> **AMENDED 2026-08-29 (field evidence, candidate #17):** the RAM-only rule
> below is superseded. On a 32GB CPU-only reference station it picked 12B
> (32 >= 16), which took 366s to complete one summary generation and then
> failed twice more under realistic memory pressure (CPU buffer allocation
> failure; a crashed `llama-server` process); `gemma4:e4b` completed every
> attempt in 94-128s on the same box. RAM headroom does not predict CPU
> token-generation throughput — a discrete GPU does. The as-implemented rule
> (`civiccast/ai_models/models.py::detect_summary_model_default`) adds a
> `has_gpu` gate: 12B is only the default with a real (NVML-detected) GPU
> present AND >=16GB RAM; every CPU-only box gets e4b regardless of RAM. The
> RAM-only table below is kept for historical context, not as the current
> behavior.

```python
# HISTORICAL (pre-2026-08-29) — see the amendment note above for the
# as-implemented, GPU-aware rule.
def detect_summary_model_default(system_ram_total_gb: int) -> str:
    if system_ram_total_gb >= 16:
        return "gemma4-12b-ollama"
    return "gemma4-e4b-ollama"
```

### 3.3 Storage

**Migration:** `0053_ai_model_configuration` — single global chain (one head; `down_revision`
`0052_secondary_audio`, the live head after S11's per-slice 0049–0052). Adds
`ai_model_configuration` and `feature_model_registry` tables. No per-module chain. (The
earlier draft naming `0045` on `0044_loudness_and_eas` was stale before S11 landed.)

`feature_model_registry` table (per-feature operator selection):
- `feature`: captions | summary | translation
- `model_key`: operator selection or NULL
- `tier`: computed (local | cloud | frontier)
- `created_at`, `updated_at`
- **Unique constraint:** `(feature, deleted_at) WHERE deleted_at IS NULL`

`ai_model_configuration` table holds the global config row (`created_at`/`updated_at`).

---

## 4. API surface

### 4.1 Operator endpoints

**Router:** `/api/staff/ai-models` (staff-gated)

```python
@staff_models_router.get(
    "/{feature}", dependencies=[Depends(require_any_role("setup_admin", "meeting_operator"))]
)
def get_feature_model_registry(feature: str) -> FeatureModelRegistry: ...


@staff_models_router.post(
    "/{feature}/select", dependencies=[Depends(require_any_role("setup_admin"))]
)
def select_feature_model(feature: str, payload: ModelSelectionRequest) -> FeatureModelRegistry: ...


@staff_models_router.get("")
def list_all_models() -> AiModelConfiguration: ...
```

Auth roles:
- `setup_admin`: change selections (bootstrap)
- `meeting_operator`: read-only

### 4.2 Release-gate boundary

Gates must not pin a single model. Updated in `civiccast/ai_quality/release_gates.py:90-136` to accept operator-selected model evidence.

---

## 5. Operator UI surface

### 5.1 Console settings card

Location: Operator console > Settings > AI Models

Shows three cards (captions, summary, translation) with:
- Current model + tier (Local/Cloud/Frontier)
- Status + cost + privacy label
- [Select another model] button

### 5.2 Model selection dropdown

Shows tiers with cost/latency info. LOCAL tier free; CLOUD tier metered (~$0.10/1M tokens); FRONTIER (OpenRouter) per-provider pricing.

### 5.3 First-run wizard

During installer (S3), show adaptive default with override option.

---

## 6. Behavior / algorithms

### 6.1 Model selection flow

1. Installer detects RAM → calls `detect_summary_model_default()` → persisted
2. Console startup loads `AiModelConfiguration` from DB
3. Feature init queries `AiModelStore.get_registry()` for effective model key
4. Release-gate collects evidence from selected models

### 6.2 Cost & privacy labeling

Models have flags: `cost_per_token_usd`, `private`, `requires_network` → UI propagates

### 6.3 Fallback

Ollama unavailable → yellow warning; services defer until restart

---

## 7. Proof tier: current & advancement

### Current: **Contract-tested (0)**

Unit tests + API contract tests + release-gate unit tests (no runtime Ollama)

### Path to Lab (1)

Attach to Ollama; run summary/translation on selected models; verify gates pass

### Path to Machine (2)

24h soak with `gemma4:12b` on ≥16GB; verify no regressions; kill/restart recovery

### Hard boundary

Cloud tiers (Ollama Cloud `gemma4:31b-cloud` + OpenRouter) ship **functional** (D13) but are
out of scope for **machine-proof** in S13 — they advance on their own proof evidence; the S13
machine-proof bar covers the local default only.

---

## 8. Test plan

### 8.1 Unit tests

- ModelTier validation (cost ≥ 0, latency ≥ 0)
- FeatureModelRegistry.effective_model_key
- detect_summary_model_default(8) → "gemma4-e4b-ollama"
- detect_summary_model_default(16) → "gemma4-12b-ollama"
- AiModelStore.get_registry / select_model / persistence
- Release gates accept selected models

### 8.2 API contract tests

- GET /api/staff/ai-models/{feature} requires role
- POST persists choice
- Invalid model → 400

### 8.3 Integration tests

- Summary uses selected model
- Release gate validates selected evidence
- Registry updates reflected

---

## 9. DONE criteria

1. `ModelSelection` + `AiModelConfiguration` entities defined
2. Per-feature registries wired and seeded
3. Adaptive default in installer
4. `/api/staff/ai-models/{feature}` endpoints live and role-gated
5. Operator console Settings > AI Models card renders
6. Release-gate accepts selected models (not hardcoded)
7. All tests pass (0/0/0/0/0 audit)
8. Playwright walkthrough passes
9. Commissioning wizard (S3) shows adaptive default
10. OpenRouter + Ollama Cloud (`gemma4:31b-cloud`) adapters ship **functional** (D13): default OFF, operator opts in and accepts per-token cost — not stubbed. "Operator always chooses" requires the hosted path actually works.

---

## 10. Dependencies & cross-refs

### Dependencies

- **S1:** `detect_summary_model_default()` reads `StationBoxProfile.system_ram_total_gb` (D3)
- **S3:** First-run includes AI model selection step
- **Master §5:** Release-gate alignment

### Cross-refs

- **S8:** Alerting on "AI runtime unavailable"
- **S11:** S13 provides captions selection; S11 owns CEA-708 proof

### Open decisions for Scott

1. **Cloud lists:** Hard-coded (A) or fetched (B)? **Recommend:** A
2. **Cloud consent:** TOS checkbox (A) or require token (B)? **Recommend:** A in S13
3. **Cost display:** Show $USD/token + estimate (A) or "metered" label (B)? **Recommend:** A

---

## Appendix A. Gemma 4 license (verified 2026-06-13)

Google Gemma 4 (e4b, 12b, 26b) is **Apache 2.0** for commercial use + redistribution.
- Ollama: `civiccast/installer/model_bundle.py:54-55`
- HuggingFace: `google/gemma-4-12B-it` (ungated)
- Google: [https://ai.google.dev/gemma](https://ai.google.dev/gemma)

Civic broadcasting compliant. Link Prohibited Use Policy in docs.

---

*End S13. Ready for review.*

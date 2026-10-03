# AI Models  (nav id: ai-models, section: Setup)
Source files (under `civiccast\apps\portal-operator\src\`): `screens\AiModelsScreen.tsx` (AiModelsScreen + FeatureModelCard, BandBadge, AvailabilityHint), `screens\ai-models-format.ts`, `components\AuthRequiredState.tsx`, `api\client.ts:2930-2995`.
Backend: `civiccast\ai_models\router.py` (`/api/staff/ai-models/*`), `ai_models\catalog.py` (model list), `ai_models\service.py` (select_model 234, get_availability 363), `ai_models\dispatch.py`, `ai_models\runtime.py`, `app.py:1523-1619` (where the selection feeds captions/summary/translation).
Who can open it: sidebar shows it to `setup_admin` and `meeting_operator` (`Sidebar.tsx:112`). Screen check `READ_ROLES = setup_admin, meeting_operator` (line 52). Only `setup_admin` may change anything (`WRITE_ROLES`, line 53; server `_WRITE`, router.py:53). A meeting_operator sees every control disabled and "(read-only — changing the model requires the setup admin role)" (407). Others see "AI Models requires the setup admin or meeting operator role. Ask your station admin for access." (515-516).

## What it is for
It lets the station choose which AI model does each of three jobs: Captions (speech to text), Summary (meeting summaries), Translation (English captions to Spanish). The default for each is a model that runs on this computer (private, no per-use fee). The page can also switch a job to a hosted internet model, which costs money per use and sends meeting content to a third party, only after an explicit consent tick.

## What the user sees
H1 "AI Models" and "Choose the model behind each AI feature. The default is always a private, on-device (local) model with no per-token cost. Hosted cloud and frontier models are available but default off — selecting one sends content to a third-party provider and bills per token." (529-533). Then three cards side by side in fixed order (`FEATURE_ORDER`): Captions, Summary, Translation. Each card has: title + band badge (Local / Cloud / Frontier / Unknown); optional yellow "Availability:" line; (Translation only) a grey note; a facts list (Current model, About, Cost, Latency, Privacy, Terms); a "Choose a model" dropdown; a "Staged" preview list when the dropdown differs from the current model; and, for hosted choices, a yellow consent group.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Choose a model (select; aria-label "Captions model", "Summary model", "Translation model") | Picks a model for that job. Option text: `<key> — <band> · <cost>` plus ` · needs N GB` and ` (exceeds this box)` | A **local** choice is saved immediately on change: `POST /api/staff/ai-models/{feature}/select` with `model_key` (router.py:235; `select_model` service.py:234). A hosted choice is only staged | `setup_admin` | Options needing more RAM than this box has are disabled (RAM from system-health sample; unknown RAM disables nothing). No confirm for local changes. If the save fails the dropdown keeps the new value while the old model stays current (UI has no revert; banner "Could not save the model selection.") |
| (hosted only) "View provider terms" link | Opens the provider's terms in a new tab | external URL | | Terms URLs: Google Gemma, OpenRouter, Whisper license |
| Provider API key (password field; placeholder "Paste the provider API key") + Save key | Stores the key for the staged hosted provider in the Windows credential store (write-only, never shown again) | `PUT /api/staff/ai-models/credentials/{ollama-cloud|openrouter}` | `setup_admin` | Field only appears if the server says no key is stored for that provider. Text "**Provider API key required.** No key is stored for this provider yet, so this hosted model will defer until one is saved." Errors: 400 "The provider API key must be a non-empty single-line secret.", 503 "The OS credential store is unavailable; provider keys cannot be saved here." There is no UI to remove a stored key (API `DELETE` exists) |
| Checkbox "I accept the provider terms of service and the per-token cost for this hosted model." | Consent record | sent as `consent_accepted: true` | `setup_admin` | Required before Apply; server rejects a hosted choice without it (400 "Model '<key>' is a cloud tier that sends content to a third-party provider and bills per token; the operator must accept the cloud terms of service before it can be selected.") |
| Apply cloud model | Saves the hosted choice with consent and the operator id as consent actor | `POST .../{feature}/select` | `setup_admin` | Disabled until the checkbox is ticked and no save is running. Focus moves to the consent group when a hosted model is staged |

Catalog (hard-coded, `catalog.py:69-215`): Captions: `whisper-medium-faster` (default, "faster-whisper medium (int8) on-box", needs 4 GB), `whisper-large-v3-faster` (needs 8 GB). Summary: `gemma4-12b-ollama` (needs 16 GB), `gemma4-e4b-ollama` (needs 8 GB), `gemma4-31b-cloud` (Ollama Cloud, ~$0.10 per 1M tokens), `gemini-2.5-flash-openrouter` (OpenRouter, ~$0.30 per 1M tokens). Translation: `translategemma-4b-ollama` (default), `gemma4-31b-cloud`. Summary default is adaptive: 12B only with a GPU and 16 GB+ RAM, otherwise e4b (`models.py:174-199`).

## States
- Loading: "Loading…" (identity), "Loading AI model configuration…".
- Identity failure: "Could not verify your staff identity (...). Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then retry once the local API is running." (`AuthRequiredState.tsx`).
- Config failure: "Could not load AI model configuration." or server text; 503 "Durable storage is not ready yet." Save failures: "Could not save the model selection.", "Could not save the provider API key."
- Availability lines (`ai-models-format.ts:181-203`): "Ollama unavailable — feature will defer until the runtime is back."; "Not installed — “<key>” is not on this box; feature will defer. Run the installer model step or pull the model, then retry."; hosted with no key: "Hosted tier selected but no provider credential is stored — feature will defer until a key is saved." The on-box faster-whisper models are never probed (detail "On-box faster-whisper runtime (presence not probed here)."), so no warning shows for them.
- Facts text: Cost "Free (local)" or "$0.00000010/token (~$0.10 / 1M tokens)"; Latency for captions "~3.3x the recording's length, CPU-only (varies with station load)", for local LLM "<n> s+ on a typical CPU-only station (varies with input length)" (summary e4b 128 s, 12B 366 s), hosted "≈1.8 s typical"; Privacy "On-device — private" or "Sent to cloud provider — network required".
- Translation note (always on that card): "This model translates a published recording’s approved English captions into Spanish, and the Spanish cues then go to the caption review queue for their own approval. The recording is public immediately; captions attach after review — both languages together, never English alone. Live broadcasts are captioned in English only." (210-214).

## Typical task flows
1. Look only: open the page, read each card.
2. Switch to a bigger local caption model: Captions card -> choose `whisper-large-v3-faster` (applies at once).
3. Use a hosted summary model: Summary card -> choose Cloud/Frontier option -> read terms -> paste provider key -> Save key -> tick consent -> Apply cloud model.
4. Go back to local: choose the local option (applies at once, no consent step).

## Statuses and words on this screen
Bands: Local (ollama and on-box faster-whisper), Cloud (ollama-cloud), Frontier (openrouter), Unknown. Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`GET /api/staff/ai-models`, `/availability`, `/{feature}`, `POST /{feature}/select`, `PUT /{feature}/first-run-override` (commissioning only, not on this screen), `PUT|GET|DELETE /credentials/{provider}`. Windows credential store (keyring). Local runtime: Ollama on loopback. CLI line `translation model: <key> (<band>)` (cli.py:2596).

## Help-text findings
- [HELP-01] `ai_models\catalog.py:145-148` (shown in the Translation card under "About") — "NOT YET CONNECTED (audit finding, 2026-08-29): no caller supplies a translation target, so this model is never actually invoked and no translated caption track is published. Selecting it has no visible effect yet; see AiModelsScreen's translation banner." — directly contradicts the grey note on the same card, which says it translates recordings (the screen comment at AiModelsScreen.tsx:197-203 says it is now connected, `app.py:1538` builds a translator from this selection). The stale text is rendered for the default model — fix: replace the tier note with a plain description (e.g. "On-device Spanish translation, 4B model") and delete the audit text.
- [HELP-02] AiModelsScreen.tsx:220, 275 — "Current model" shows the internal slug (e.g. `gemma4-e4b-ollama`, `whisper-medium-faster`) and the dropdown options read "<slug> — Local · Free (local) · needs 8 GB" — slugs mean nothing to a clerk and there is no plain name or "recommended" mark — fix: show a friendly name ("Gemma 4 small, runs on this computer") and mark the default.
- [HELP-03] AiModelsScreen.tsx:248-250 and ai-models-format.ts — "Frontier" / "Cloud" bands and "per-token" cost are jargon; no sentence says what a token is or gives a per-meeting dollar example; cost is only ~$/1M tokens — fix: add an "about $X per hour of meeting" example or hide.
- [HELP-04] AiModelsScreen.tsx:342-381 — for a hosted choice the key box says "Provider API key required." but the page never says where to get a key or which provider (Ollama Cloud vs OpenRouter) the tier uses; the staged tier's band label is the only clue — fix: name the provider and link to its key page.
- [HELP-05] AiModelsScreen.tsx:268-275 — a local change takes effect the moment the dropdown changes, with no confirmation and no note on when the new model starts being used (next meeting? next job?). The code does not say; UNVERIFIED how running jobs behave — fix: state "Applies to new captions/summaries from now on" once verified.
- [HELP-06] Captions card gives no hint about the difference between live captions and recording captions; the Station Profile page has a separate "Show live captions on air" switch (default OFF) — a clerk will assume choosing a caption model turns captions on. The page never mentions that switch — fix: add a link/sentence.
- [HELP-07] The "(exceeds this box)" suffix disables options silently; the user cannot see this computer's RAM on this page — fix: show "This computer has N GB".
- [HELP-08] AuthRequiredState text mentions an "installer handoff" and "operator-console link" that no longer exist (see station-profile inventory HELP-10).
- [HELP-09] `ai_models\catalog.py:90-96` — the "About" line for the 12B summary model (shown when it is the current model) says "...QAT... measured CPU-only on the 32GB reference station it took 366s... (memory allocation failure; a crashed llama-server process)" — engineering notes, not operator guidance — fix: "Needs a graphics card. On a computer without one it is very slow and may fail; use the smaller model."

## Screenshot plan
1. setup_admin with all three cards on defaults (Local badges, "Free (local)").
2. A card with the yellow "Availability:" line (stop Ollama or remove the model beforehand, or select a hosted tier with no key).
3. Hosted option staged: staged-preview list + consent group + "Provider API key required." box.
4. meeting_operator read-only view.
5. The Translation card showing the stale "NOT YET CONNECTED" About text (to prove HELP-01).
Setup: a token with `meeting_operator` scope made via `civiccast token issue --scopes meeting_operator`; do NOT enter a real provider key or accept real consent on a real station.

## UNVERIFIED / open questions
- UNVERIFIED: whether the Captions selection changes the model used for LIVE captions, recorded captions, or both (`app.py:1531` passes `live=True` to the runtime builder; the catalog says captions default is the medium tier but I did not trace the live tap).
- UNVERIFIED: that the stale catalog note is what the browser actually receives (serialized `notes` field of the tier; I read the catalog and the field render, not a live response).
- UNVERIFIED: timing of when a changed model takes effect for running jobs.
- UNVERIFIED: whether the first-run default listed in `station-state.json` (`ai_model_seed`) can differ from the displayed "Current model" (service `get_registry` override order not read in full).

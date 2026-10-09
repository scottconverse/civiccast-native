> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# AI Models (nav id: ai-models)

Sidebar: Setup > **AI Models**. Manual authority: `docs/manual/src/22-configuration.md` sections "Configure AI models" (`#configuration-ai`) and "Configure captions" (`#configuration-captions`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/AiModelsScreen.tsx` (578 lines: AiModelsScreen, FeatureModelCard, AvailabilityHint), `ai-models-format.ts` (cost, latency, privacy and availability wording), `components/AuthRequiredState.tsx`. The "About" text of each model is not in the screen: it is the `notes` field of the hard-coded catalog `civiccast/ai_models/catalog.py:69-215`, shown as received. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "AI Models"; "Choose the model behind each AI feature. The default is always a private, on-device (local) model with no per-token cost. Hosted cloud and frontier models are available but default off — selecting one sends content to a third-party provider and bills per token." | H1 and intro | AiModelsScreen.tsx:528, 530-532 |
| "AI Models requires the setup admin or meeting operator role. Ask your station admin for access."; "Loading…"; "Loading AI model configuration…"; "Could not load AI model configuration."; "Could not save the model selection."; "Could not save the provider API key." | gate and states | 515-516, 499, 546, 549, 537, 541 |
| Card titles Captions, Summary, Translation; band badge Local / Cloud / Frontier / Unknown | cards | AiModelsScreen.tsx (featureLabel, BandBadge) |
| "Availability:" + "Ollama unavailable — feature will defer until the runtime is back." / "Not installed — “<key>” is not on this box; feature will defer. Run the installer model step or pull the model, then retry." / "Hosted tier selected but no provider credential is stored — feature will defer until a key is saved." | yellow line | AiModelsScreen.tsx:107; ai-models-format.ts:181-203 |
| "This model translates a published recording's approved English captions into Spanish, and the Spanish cues then go to the caption review queue for their own approval. The recording is public immediately; captions attach after review — both languages together, never English alone. Live broadcasts are captioned in English only." | Translation card note | 210-214 |
| Facts list: "Current model" (the internal key, for example `gemma4-e4b-ollama`), "About", "Cost" ("Free (local)" or "$0.00000010/token (~$0.10 / 1M tokens)"), "Latency" ("~3.3x the recording's length, CPU-only (varies with station load)", "<n> s+ on a typical CPU-only station (varies with input length)", "≈1.8 s typical"), "Privacy" ("On-device — private" / "Sent to cloud provider — network required"), "Terms" with "View provider terms" | each card | 219, 224, 228-233, 238, 246; ai-models-format.ts:116, 159, 210-213 |
| "Choose a model"; options "<key> — <band> · <cost> · needs N GB (exceeds this box)" | dropdown | 254, 272-275 |
| "Staged" preview list | when the dropdown differs from the current model | 292 |
| Hosted consent group: "<Cloud|Frontier> model. <privacy>. Cost: ... Latency: ..."; "View provider terms" | consent group | 311-322, 333 |
| "Provider API key required." "No key is stored for this provider yet, so this hosted model will defer until one is saved."; label "Provider API key"; placeholder "Paste the provider API key"; button "Save key" | key box | 345-346, 349, 358, 378 |
| "I accept the provider terms of service and the per-token cost for this hosted model."; "Apply cloud model" | consent and apply | 389, 400 |
| "(read-only — changing the model requires the setup admin role)" | meeting operator view | 407 |
| Catalog "About" for the translation default: "...NOT YET CONNECTED (audit finding, 2026-08-29): no caller supplies a translation target, so this model is never actually invoked ... Selecting it has no visible effect yet" | "About" row | civiccast/ai_models/catalog.py:145-148 |
| Catalog "About" for the 12B summary model: "...on the 32GB reference station it took 366s... (memory allocation failure; a crashed llama-server process). A GPU is ..." | "About" row | catalog.py:90-96 |

## What the screen really does
It shows the model behind three jobs: Captions (speech to text), Summary, and Spanish Translation. Defaults run on this computer. Choosing a local model saves at once with no confirmation. Choosing a hosted model (Ollama Cloud or OpenRouter) only stages it: you enter the provider's key (stored write-only in the Windows credential store), tick the consent box and press Apply cloud model; the server refuses a hosted choice without consent. Hosted models send meeting content to the provider and bill per token. A Setup admin can change models; a Meeting operator can only read. On a native station the Captions choice does not change the model that actually runs: the caption runtime uses the verified model folder chosen at service start (`CIVICCAST_WHISPER_MODEL_PATH`), not the drop-down (manual ch. 11; `captions/runtime.py:660`, `native/station_runtime.py:1433`).

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | Translation "About": "NOT YET CONNECTED ... never actually invoked" (catalog.py:145-148) | The program does build a translator from this selection for recorded Spanish captions (app.py:1538); the grey note on the same card is the accurate one | blocks work (contradicts the page; user may think translation is off) |
| HELP-02 | "Current model" shows `gemma4-e4b-ollama` and options read "<key> — Local · Free (local) · needs 8 GB" (219, 275) | Internal keys; no plain name or "recommended" mark | misleading |
| HELP-03 | "Frontier", "Cloud", "per-token" (248-250; ai-models-format.ts) | Jargon; no example of cost for one meeting | misleading |
| HELP-04 | "Provider API key required." (345) | Does not say which provider (Ollama Cloud for Cloud, OpenRouter for Frontier) or where to get a key | misleading |
| HELP-05 | A local change saves the moment you pick it (268-275) | No confirm and no note on when it starts to apply; behaviour of a job already running is UNVERIFIED | misleading |
| HELP-06 | Captions card | Says nothing about the separate "Show live captions on air" switch on Station Profile (default off) | misleading |
| HELP-07 | "(exceeds this box)" (272) | Options are disabled silently; the page never shows how much memory this computer has | misleading |
| HELP-08 | AuthRequiredState installer-handoff text | Retired; real step is Admin sign-in | blocks work |
| HELP-09 | 12B "About": "...366s... crashed llama-server process" (catalog.py:90-96) | Engineering notes shown to operators | cosmetic |
| NEW-1 | Captions card: choosing `whisper-large-v3-faster` saves at once (253-275) | On a native station the choice has no effect on the running model; the tier is whichever caption model the installer staged. To change tiers add or remove the large-v3 component and restart the service | blocks work |
| NEW-2 | A failed local save | The dropdown keeps the new value while the old model stays current; there is no revert (manual) | misleading |
| NEW-3 | No way to remove a stored provider key | API `DELETE` exists; the screen has no button (`civiccast model set-provider-key <provider> --clear`) | misleading |

## Proposed text
**Intro:** "What this is for: choose which AI model does each job: Captions (speech to text), Summary (meeting summaries) and Translation (English to Spanish for recordings). Who can use this: Setup admin changes models; Meeting operator can read. By default every job runs on this computer, which is private and has no per-use fee. A hosted model is run by another company: it sends meeting content over the internet and charges for each use."
**Cost line (hosted):** "Costs about $0.10 per million tokens. A token is a small piece of text, roughly a word or part of one." (Figure comes from the catalog: ai_models/catalog.py cost fields; show per-meeting cost only after it is measured.) Remove "frontier"; call the bands "On this computer" and "Hosted (Ollama Cloud)" / "Hosted (OpenRouter)".
**Model names:** show a plain name first, key second: "Gemma 4, small (runs on this computer) (gemma4-e4b-ollama)". Mark the default "Recommended".
**Captions card (until fixed):** "On this station the caption model is set by the installer. Changing this drop-down does not switch it. To use the larger caption model, add the large caption component with the installer and restart CivicCast." After fix: the drop-down changes the running model and says when ("Applies to the next captioning job"). Add: "Live captions on air are turned on separately in Station Profile and are off by default."
**Local change text:** "Saved. Applies to new jobs from now on. A job already running keeps its model." (verify before use; UNVERIFIED).
**Translation "About" (replace the audit text):** "On-device Spanish translation, 4 billion parameters. Used when a recording is published."
**12B "About":** "Needs a graphics card. On a computer without one it is very slow and may fail; use the smaller model."
**Key box:** "This hosted model needs an account with <Ollama Cloud | OpenRouter>. Paste the provider's API key below. CivicCast keeps it in the Windows credential store and never shows it again. To remove a key later, ask IT (`civiccast model set-provider-key <provider> --clear`)." After fix: a Remove key button.
**Consent label:** "I accept the provider's terms and the cost per use. I understand this sends meeting content to the provider."
**Disabled option:** "needs 16 GB of memory; this computer has 8 GB" (show the computer's memory at the top: "This computer has N GB of memory.").
**Failed save:** "The model was not changed. Reload the page to see the model that is in use."

## Notes for the coder
- Files: `AiModelsScreen.tsx`, `ai-models-format.ts`, `civiccast/ai_models/catalog.py` (the "About" notes at 90-96 and 145-148 must be edited there; they are served as data), `router.py` for a key-removal button.
- Pins: `AiModelsScreen.test.tsx` and `ai-models-format.test.ts` pin "Apply cloud model", "exceeds this box", "Availability:", "Free (local)", "On-device", "Hosted tier selected but", "Not installed", "Ollama unavailable"; `tests/captions/test_doctor_translation_check.py` and `tests/installer/test_commissioning.py` also contain "Availability:" / "Not installed". The "NOT YET CONNECTED" and 366-second texts are not pinned by any test searched.
- Code fix needed, not text: make the Captions choice real on native stations or hide it (NEW-1); revert on failed save (NEW-2); show system RAM; a remove-key button (NEW-3); decide when a changed model takes effect.

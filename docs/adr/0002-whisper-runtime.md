# ADR 0002 — Canonical Whisper runtime: faster-whisper

**Status:** Accepted
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** Day 0 bootstrap / 0.5 — Captions
**Related spec section:** §11.2 Captions, §22 Open Decisions (D4)
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

CivicCast's captions module (`civiccast-captions`, spec §8.7 and §11.2) provides automated speech-to-text for live and recorded meetings using OpenAI's Whisper model family. Whisper itself is a model architecture; multiple runtime implementations exist, each with different performance characteristics, license terms, integration surfaces, and operational footprints. The captions module ships first at rung 0.5 of the release ladder, but the runtime choice is captured in Day 0 because:

1. The runtime adapter interface that decouples the captions module from any specific runtime must be designed in, not bolted on. Decoupling that depends on knowing the canonical runtime's API shape.
2. The platform's GPU acceleration story (CUDA via faster-whisper / CTranslate2 vs Apple Metal via whisper.cpp) affects the hardware reference (ADR 0003) and the deployment installer story (Sprint 0.1).
3. The captions module has the highest accuracy bar in the AI surface — accessibility regulations (ADA, WCAG 2.2 AA) require a level of caption quality that the runtime choice directly influences.

The selected runtime must support:

- **Whisper large-v3 model.** The smaller models are not accurate enough for public-meeting captions, especially with municipal/HOA/school-board domain vocabulary, multiple speakers, and imperfect audio.
- **GPU acceleration on the Tier 1 reference hardware** (NVIDIA RTX 5070 Ti via CUDA per ADR 0003). VRAM headroom matters: large-v3 alone uses ~5GB; concurrent operation with a local LLM for the summary module needs the remaining 10GB+ VRAM.
- **In-process Python API** so the runtime maps cleanly onto the captions module's stabilization layer (which post-processes Whisper output for diarization, paragraph breaks, and timestamp alignment). Out-of-process (server / API) integrations add latency and complexity.
- **OSI-approved license** consistent with the project's Apache 2.0 / CC BY 4.0 posture. No SSPL, RSAL, or "source-available" runtimes.
- **Active upstream maintenance** through at least the 1.0 timeline.

This was Open Decision **D4** in the spec (§22). The release plan resolves it in Day 0 alongside D3 (messaging substrate).

## Decision

**CivicCast uses faster-whisper as its canonical Whisper runtime.** The captions module wraps faster-whisper through an internal runtime adapter protocol (`civiccast.captions.runtime`) so a community-contributed alternative — most likely whisper.cpp for embedded or edge deployments — can plug in later without rewriting the captions module. faster-whisper is the only runtime shipped in v1.0; whisper.cpp is registered as a future alternate.

## Alternatives considered

**Option A — faster-whisper (CTranslate2-backed).** MIT license. Python-native via the `faster-whisper` package, in-process API, INT8 / FP16 inference paths well-tested on NVIDIA GPUs (including the RTX 5070 Ti per ADR 0003). Active upstream (Guillaume Klein and contributors), backed by CTranslate2's mature C++ inference engine. ~4x faster than the original `openai/whisper` package on the same hardware. This was selected.

**Option B — `openai/whisper` (the original PyTorch implementation).** MIT license. The reference implementation. Rejected for performance: significantly slower than faster-whisper on the same hardware, with higher VRAM consumption that would constrain concurrent LLM operation in the summary module. The reference implementation is correct but operationally heavier than CivicCast's reference hardware tolerates.

**Option C — whisper.cpp.** MIT license. C++ implementation with CPU and Metal/CUDA backends, broadly portable, including to embedded targets. Rejected as the primary runtime because (a) the Python binding (`pywhispercpp`) is a less-well-maintained shim than `faster-whisper`'s native Python package, and (b) CTranslate2's INT8 quantization on NVIDIA hardware outperforms whisper.cpp's CUDA path for the captions module's batch transcription pattern. **Retained as a registered future alternate** for embedded / edge deployments; the runtime adapter interface keeps that door open.

**Option D — OpenAI Whisper API (cloud).** Highest accuracy on a fully-managed runtime. Rejected because it violates the spec's prohibited-uses non-negotiable (§4.3 — no retention of resident audio for AI training in third-party systems without explicit consent), the platform's self-hostability principle, and CivicCast's vendor-lock-in posture. Public meeting audio cannot be sent to a third-party API as a default behavior.

**Option E — WhisperX.** Layered on top of faster-whisper with built-in diarization and timestamp alignment. Rejected as the primary runtime because we want the diarization and stabilization layers to live in `civiccast-captions` (under our license, our code, our test coverage), not as a dependency we don't control. WhisperX's individual components (diarization model, alignment model) may be referenced by the captions module, but the runtime layer stays at faster-whisper.

## Consequences

### Positive

- MIT-licensed Python-native runtime maps cleanly onto the captions module's in-process stabilization layer; no IPC or HTTP hop between Whisper output and post-processing.
- INT8 inference on the RTX 5070 Ti (ADR 0003) leaves 10+GB VRAM available for the summary module's local LLM, allowing captions and summaries to run concurrently on a single GPU within the Tier 1 Streaming reference build.
- faster-whisper supports Whisper large-v3 with the necessary accuracy floor for ADA / WCAG 2.2 AA caption quality.
- CTranslate2 is broadly portable: the same CivicCast captions module runs on Linux, macOS (CPU, with CoreML acceleration available), and WSL2 Ubuntu without code changes.
- The runtime adapter interface preserves optionality. A community whisper.cpp adapter can land post-1.0 for embedded/edge use without rewriting `civiccast-captions`.

### Negative

- CTranslate2 imposes a CUDA library dependency on the Tier 1 reference deployment. The installer must verify CUDA version compatibility before the captions module is enabled. (See ADR 0003's RTX 5070 Ti / Blackwell-architecture risk note.)
- faster-whisper's API does not yet expose all of upstream Whisper's training-time configuration knobs (e.g., specialized fine-tuned variants). For 1.0 the canonical large-v3 model is sufficient; if downstream operators need fine-tuned variants, the runtime adapter pattern lets them use a different runtime.
- The internal runtime adapter protocol is additional engineering surface (~1 module-week of design at Sprint 0.5).

### Risks

- **CUDA / Blackwell compatibility.** The RTX 5070 Ti is Blackwell architecture (5000 series). CTranslate2 relies on cuDNN + CUDA libraries with version constraints; a build incompatibility blocks Sprint 0.5. Mitigation: explicit verification at Sprint 0.5 kickoff that faster-whisper + CTranslate2 + the installed CUDA driver runs large-v3 successfully on the Tier 1 hardware. If incompatible, the rung is gated until a compatible build lands.
- **Upstream slowdown.** faster-whisper depends on CTranslate2; if either project goes dormant, the captions module's runtime story is at risk. Mitigation: the runtime adapter protocol designed at Sprint 0.5 ensures swapping to whisper.cpp (or a future alternate) is bounded engineering work, not a captions-module rewrite.
- **Model drift.** Whisper large-v3 is the canonical model now. Future model releases (large-v4, etc.) need an ADR if they change accuracy, latency, or VRAM characteristics meaningfully.

## Compliance

- The captions module (`civiccast.captions`) imports faster-whisper through `civiccast.captions.runtime` only. Direct `faster-whisper` imports in any other module are a violation flagged by lint at Sprint 0.5+.
- The `civiccast doctor` CLI (Sprint 0.1) reports the detected CUDA driver version, GPU model and VRAM, and CTranslate2 / faster-whisper compatibility.
- The captions module's verification log entry (Sprint 0.5) confirms a clean transcription of a known-good test asset on the Tier 1 reference hardware.
- The runtime adapter protocol is documented as part of `civiccast.captions.runtime` and gets its own ADR if its surface changes after 1.0.

## References

- CivicCastUnifiedSpec-v2.md §11.2 Captions
- CivicCastUnifiedSpec-v2.md §8.7 civiccast-captions
- CivicCastUnifiedSpec-v2.md §22 Open Decisions (D4 — Whisper runtime)
- CivicCastUnifiedSpec-v2.md §4.3 Prohibited uses (no resident-audio retention in third-party AI systems)
- CivicCast-ReleasePlan-0.1-to-1.0.md — "Architecture decisions baked in" (D4 resolution)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — MIT
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) — MIT
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — MIT (registered future alternate)
- ADR 0001 — Messaging substrate: NATS JetStream
- ADR 0003 — Project development hardware and primary deployment OS target

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*

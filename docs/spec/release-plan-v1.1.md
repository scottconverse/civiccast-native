# SPDX-License-Identifier: Apache-2.0
# CivicCast Post-1.0 Release Plan

## 1.1 - Public Availability Release

**Proves:** CivicCast v1.1.0 is installable from public release artifacts, runs real local AI, proves real external provider publication on controlled test surfaces, produces veraPDF-validated PDF/A-3B records, and passes cleanroom release verification.

**Release claim:** CivicCast v1.1.0 is publicly available as an installable Linux x64 release. It does not claim a real station pilot, five or more station adoption, seated governance, TSA or legal signing authority proof, or production deployment proof.

**Required package areas:** `civiccast-captions`, `civiccast-summary`, `civiccast-translate`, `civiccast-installer`, `civiccast-publish`, `civiccast-archive`, `civiccast-syndicate`, `civiccast-subscribe`, `civiccast-podcast`, and `civiccast-records`.

**Public availability posture:**
- Preferred: publish the source repository publicly for v1.1.0, consistent with the CivicCast public-source posture.
- Fallback only with explicit Scott approval: keep the repository private while publishing public release artifacts. If used, documentation must say source publication is deferred.
- The release is not publicly available until the chosen posture is resolved and documented.

**Real local AI:**
- Captions default to faster-whisper running `whisper-large-v3` INT8 on the actual caption path.
- Summary defaults to Ollama `gemma4:e4b`; `ModelProvenance` records the live model tag, digest, runtime version, and manifest source.
- Spanish translation defaults to Ollama `translategemma:4b`.
- Deterministic AI adapters remain test-only behind explicit opt-in and must not appear on the release proof path.
- `civiccast model download` pulls and verifies `whisper-large-v3`, `gemma4:e4b`, and `translategemma:4b`.
- Air-gapped offline model bundle installs all three real models without network access.
- Hardware-aware tier selection uses VRAM probe results to select tier-0, tier-1, or tier-2 behavior and documents degraded CPU and tier-0 limits.

**Positive runtime proof signals:**
- Faster-whisper emits a machine-readable runtime line such as `runtime=faster-whisper model=whisper-large-v3 compute=int8`.
- Ollama summary emits a machine-readable runtime line such as `runtime=ollama model=gemma4:e4b digest=sha256:...`.
- Ollama translation emits a machine-readable runtime line such as `runtime=ollama model=translategemma:4b digest=sha256:...`.
- Release gates fail if these positive signals are absent or if deterministic runtime tags appear on the release proof path.

**First real-AI baseline:**
- v1.1.0 establishes the first real WER, BLEU, ROUGE-L, and factuality baseline.
- v1.2.0 and later enforce regression tolerances against the v1.1.0 baseline.
- Minimum sanity floors for v1.1.0 are caption WER <= 50%, translation BLEU >= 5, and summary sourced-claim/refusal pass rate 100%.
- Summary output must pass the refusal-on-uncertainty and transcript-citation gates; unsupported uncited claims block release.

**Fixture licensing:**
- Every benchmark audio, transcript, and translation fixture has a license or consent row before it enters the repository or release evidence.
- AMI license status must be verified before use.
- Earnings22 license status must be verified before use.
- Municipal fixtures must be sanitized, PII-reviewed, and accompanied by a redaction ledger.

**Real external publish proof:**
- Internet Archive controlled test item upload.
- YouTube Live private or unlisted ingest proof.
- YouTube VOD private or unlisted upload proof.
- Local NAS rsync hash-verified copy.
- Local NAS ZFS snapshot/send proof unless Scott explicitly defers it before release.
- Email proof covers signup, outbound confirmation, confirmation click or token validation, and publish notification delivery.
- Webhook proof uses a controlled HTTPS endpoint and HMAC verification.
- Public podcast RSS feed validates from the test portal.

**Installer and operator gates:**
- First-run wizard covers CDN, syndication, Internet Archive, NAS, staff token, model download, portal, and publish-target test-and-verify.
- A 14-step pre-flight checklist is a required publish gate before live or publish approval.
- `civiccast doctor audit` verifies hash-chain audit integrity.
- Staff routes remain bearer-token protected and fail closed without configured tokens.
- Operator user-visible error copy removes API jargon or records any remaining jargon as known minor risk before release approval.

**Reliability gates:**
- Nightly six-hour synthetic-meeting broadcast soak runs through the live, caption, summary, and publish pipeline.
- Streaming loudness CI validates the -16 LUFS target using ITU-R BS.1770 / EBU R128.
- Public and operator portals pass WCAG 2.2 AA with zero serious or critical axe violations.
- No GitHub-hosted runners are used for proof or release workflows.

**Release identity and documentation:**
- Version is v1.1.0 everywhere.
- README, SECURITY, USER-MANUAL, rendered PDF/DOCX, API reference, credential matrix, release notes, changelog, and docs index are updated.
- Credential matrix flips proven external surfaces to real-provider proof with redacted evidence links.
- Spec-alignment ledger marks each relevant item as implemented, proven, deferred, or out of scope.
- Repository visibility and public artifact posture are resolved before any tag.

**Explicit deferrals by Scott for post-public release:**
- Real station pilot.
- Five or more station adoption proof.
- Seated governance body.
- TSA or legal signing authority proof.
- Production deployment proof.

**Phase-2 or later carry rows in the spec-alignment ledger:**
- Mode B / `civicclerk_bridge`.
- NATS JetStream / ADR 0001 implementation.
- mTLS internal service traffic.
- Cable add-on.
- ActivityPub federation.

**Local NAS ZFS handling:**
- Preferred: prove ZFS snapshot/send in v1.1.0.
- If Scott explicitly defers ZFS before release, the spec ledger must state that Local NAS rsync to a separate controlled volume is the v1.1.0 bit-for-bit local archive peer to Internet Archive under sections 4.6 and 16.5, and that ZFS remains post-v1.1 hardening.

**Exit criteria:**
- Real AI gates pass on the self-hosted RTX runner: faster-whisper large-v3 INT8 WER <= 50%, Ollama `gemma4:e4b` summary sourced-claim/refusal pass rate 100%, Ollama `translategemma:4b` Spanish translation BLEU >= 5, runtime-tag/digest positive-signal checks, fixture license ledger, and no deterministic runtime tags on the release proof path.
- External provider proof passes for Internet Archive, YouTube Live, YouTube VOD, local NAS rsync, local NAS ZFS unless explicitly deferred, email double opt-in, webhook HMAC, and public podcast RSS.
- Local gates pass: full pytest, ruff check, ruff format check, mypy, policy checks, docs render PDF/DOCX, API/type generation, operator build, public/operator WCAG 2.2 AA, operator copy sweep, veraPDF, loudness compliance, and audit hash-chain verification.
- Cleanroom gates pass: VM install from release candidate artifact, air-gapped VM install from offline model bundle, first-run wizard end-to-end verification, and six-hour synthetic-meeting soak.
- Release artifacts are built and verified: wheel, source, container, Linux packages, docs, offline model bundle manifest, artifact names, sizes, SHA-256 hashes, and Sigstore or cosign sidecars.
- GitHub Release and public install instructions are published only after final approval.

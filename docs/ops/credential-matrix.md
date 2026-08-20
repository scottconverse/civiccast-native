# CivicCast Credential Matrix

Date: 2026-05-18

Purpose: record which external credentials have real proof, which use
deterministic local/mock proof, and which are intentionally stubbed after
the public `v1.1.0` release. The v1.2 hardening run uses fail-closed
first-run gates: provider lanes without live verification evidence must report
blocked states even if placeholder credentials are configured, and local NAS
must pass a write/read/delete hash probe before it can report `ok`.

Do not paste secrets into this file. Evidence should name the credential class,
provider surface, test date, and pass/fail result without exposing tokens,
passwords, keys, subscriber addresses, or webhook secrets.

## Matrix

| Surface | Credential class | v1.1.0 release state | Next proof action |
| --- | --- | --- | --- |
| Internet Archive archive publish | Per-station IA credentials | Deferred by Scott; deterministic archive proof and release credential gate exist | Run one real IA credential pass with a non-sensitive test item and record redacted evidence |
| Local NAS rsync | SSH key or equivalent local credential | Deferred by Scott; local target/hash contract and release credential gate exist | Run against a test NAS or isolated local target |
| Local NAS ZFS | Local administrative/ZFS send permission | Deferred by Scott; no v1.1 claim of ZFS-proven local archive peer | Run on a controlled ZFS test target |
| YouTube Live | YouTube OAuth/API credential | Deferred by Scott; deterministic syndication proof and release credential gate exist | Run an unlisted/private test stream when credentials exist |
| YouTube VOD | YouTube OAuth/API credential | Deferred by Scott; deterministic VOD proof and release credential gate exist | Upload a private/unlisted test VOD when credentials exist |
| Email notifications | Provider API key or SMTP credential | Deferred by Scott; double opt-in contract and deterministic local mailbox adapter exist | Add a real provider pass after provider selection |
| Webhook notifications | Subscriber webhook secret | Deferred by Scott; deterministic local webhook adapter with HMAC verification exists | Run against a controlled external endpoint |
| Podcast feed hosting | Public portal/feed URL | Deferred by Scott for deployed/public feed discovery; local feed generation proof exists | Verify feed discovery from a deployed pilot URL |
| Signed records | PDF/A renderer, timestamp authority, signing authority, and records-policy credential | PDF/A renderer verified by veraPDF in Phase 1; timestamp authority and legal signing authority remain deterministic/local | Add real TSA/signing-authority proof only if legal-record claims enter scope |
| Real local AI | Local model downloads and Ollama/faster-whisper runtime access | v1.1.0 deferred self-hosted RTX proof by Scott; live Ollama summary/translation proof and local faster-whisper sanity proof exist. v1.2 new-box RTX caption proof passed separately on the self-hosted RTX runner. | Re-run RTX proof for future hardware, model, or release-candidate changes; keep cloud fallback optional and explicit |
| Cloud/frontier AI (S13) | Ollama Cloud + OpenRouter provider API keys | Default OFF, opt-in per feature (2026-06-18); operator stores the key write-only via the AI Models card or `civiccast model set-provider-key`, held in the OS keyring; consent (TOS + per-token cost) recorded with the selection; no silent cloud fallback — a hosted tier defers until a key is stored | Record any real provider round-trip proof separately when a provider account exists; keep local-first default |
| ActivityPub federation | Station actor private key, public base URL, optional target-instance proof account | v1.2 branch implements default-off signed federation and operator moderation; no v1.1 credential claim and no committed public fediverse account | Generate station key per install, use approval-only plus authorized fetch for technical beta, and record redacted target-instance proof; local GoToSocial signed actor-document proof passed after Docker repair, but public target-instance `Follow`/`Accept` proof remains a separate credential/operator lane |

## Rules

- No provider is marked real until an actual external credential pass has
  durable evidence.
- Deterministic mocks are valid CI proof, but they are not real-provider proof.
- Failed credential tests must record the failure mode and fix path.
- Logs must be checked for accidental secret exposure after every real-provider
  pass.
- Any new provider added to CivicCast must add a row here before release.
- The beta tester handoff reports external provider proof as
  `credential_or_secret_required` until the row has controlled live evidence
  and the evidence is redacted.

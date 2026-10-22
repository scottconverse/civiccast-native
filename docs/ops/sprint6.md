# Sprint 6 — preparation, integration and remaining corrections

Owner-authorized October 17, 2026. Status: source work complete; documentation correction verified October 17.

The earlier completion statement was incorrect: generated inventories and
multiple operational passages remained stale. The owner authorized a consolidated
documentation repair after a code-backed review of the supplied critique.
The engineering results below remain preserved. Item 12 was reopened and is now
closed after corrected source, rendered Help and PDF/Word checks. The exact
[finding dispositions and verification](manual-reconciliation-2026-10-17.md)
record this correction rather than erasing the earlier incomplete result.
Engagement: finite program. Base source `b6f7f6f3`; prior uncommitted CI coverage
corrections and manual command correction are preserved separately.

## Scope and completion criteria

| Item | Required outcome | Status |
| --- | --- | --- |
| 12 | Reconcile current architecture, capability matrix, operations guidance, manual/Help and completion records with actual behavior; preserve clearly labeled historical package evidence. | Source documentation corrected; assembled manual, rendered Help and API reference refreshed |
| 16 | Webhook subscription requires proof of destination control, random usable signing credentials and safe outbound delivery; preserve email notices, retries and unsubscribe. | Implemented and independently reviewed; affected checks passed; see sprint6-webhooks-roku.md |
| 21 | Roku handles startup and subsequent deep links after catalog readiness without duplicate playback; preserve existing native viewer functionality. | Implemented; source checks and Roku parser passed; no device execution claimed |
| 22 | Compatible cold-conform video is stream-copied; incompatible sources and operations requiring video processing still encode correctly. | Implemented and reviewed; real 120-frame preservation check passed |
| 23 | Preparation prioritizes needed upcoming content and uses bounded recoverable retry behavior instead of blanket six-hour failure suppression; retain deduplication and bounded concurrency. | Implemented and reviewed; queued promotion and cache concurrency findings corrected with focused checks |
| 24 | Evaluate fallbackswitch and direct hlssink3 against the current selector/relay requirements and record an evidence-backed adopt/defer disposition. Replacement is not presumed necessary. | Assessment complete: retain current paths; see sprint6-gstreamer-alternatives.md |
| 25 | Hardware-aware encoder selection uses available supported hardware, has clear configuration and safe software fallback. | Implemented and reviewed; CPU-default regression corrected and 14 selector checks passed |
| 26 | CivicCast station connections: published programme/catalog sharing and central channel management. TownLight (formerly CivicSuite) integration was explicitly deferred by the owner to 2.0 on October 17. | Complete in source: station federation implemented and reviewed; 18 backend and 4 new UI checks passed |

Completion requires connected source changes, affected documentation, focused
executable checks and review of the actual changes. A test-only result is not an
installed-package claim. The active goal is not complete while any required item
remains unfinished or awaits a contract decision.

## Results and owner-approved deferral

The owner renamed CivicSuite to TownLight and explicitly deferred all suite
integration, including TownLight: Station, to a 2.0 product. That removes the
previous contract blocker by an owner scope decision, not by claiming the bridge
was implemented. CivicCast station connections remain in scope and are complete
at the source/check layer. See [the deferral record](civicsuite-bridge-contract-status.md).

Evidence by workstream:

- [Preparation/encoder changes](preparation-performance.md): 255 affected
  checks, plus subsequent focused CPU/cache/promotion corrections and real
  eight-second video preservation proof. Counts overlap; do not sum runs.
- [Webhook/Roku changes](sprint6-webhooks-roku.md): 126 affected checks,
  scoped lint and Roku parser validation.
- [Federation backend](station-federation.md): 18 checks with two actual
  application instances using ASGI transport, fixed peer APIs and authorization.
- [Federation UI](sprint6-station-federation-ui.md): 4 new UI checks,
  TypeScript and scoped ESLint; parent reviewed the actual UI and navigation.
- Manual assembly regression plus affected documentation posture: 8 checks
  passed. Generated API and in-app Help currentness checks passed. Rendered
  Help was inspected for the new workflow, anchor and setup example; a stripped
  relative link was replaced with self-contained setup guidance.

These are source-level results. No deployed federation TLS connection, Roku
device session or physical GPU qualification is claimed. The Beta 20 package
record separately identifies its signed package and scoped checks.
No station settings, runtime, service or broadcast were changed. Historical
signed manuals remain with their original package; source manual/Help describe
the changes subsequently shipped in Beta 20.

## Boundaries

The subsequent October 17 installed-verification goal authorized one consolidated
Beta 20 package, isolated install/uninstall/reinstall, a full installed walkthrough,
bounded three-channel and changed-feature operation, then an upgrade of the host
station only after isolated checks pass. The signed Beta 20 verification record
reports the package's scoped results; the source checks above do not establish
them. A verified recovery backup precedes the host upgrade.

No reopening completed earlier sprint work, external station/device qualification,
store approvals, new soak, caption-percentage gates, generalized test harnesses,
broad repeated suites, interrupted-install testing or publication. No host reboot.
Necessary small correction/check cycles are authorized. Do not substitute
ActivityPub or agenda import for item 26. TownLight remains deferred to 2.0.

## Coordination

- Preparation worker: items 22, 23, 25 and their focused tests.
- Subscription/viewer worker: items 16, 21 and their focused tests.
- Coordinator: documentation, architectural alternatives, item 26 integration and
  independent review. Existing completed work and signed artifacts remain intact.

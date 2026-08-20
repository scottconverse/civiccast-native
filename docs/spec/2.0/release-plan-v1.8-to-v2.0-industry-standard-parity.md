# CivicCast v1.8-to-v2.0 Industry-Standard Parity Plan

Status: active roadmap for post-v1.7.3 development
Created: 2026-05-31
Baseline: v1.7.3 early-adoption release asset smoke PASS
Reference specs:

- `docs/spec/2.0/civiccast-2.0-industry-standard-parity-addendum.md`
- `docs/spec/2.0/civiccast-design-spec-per-dev.md`
- `docs/spec/spec.md`

## Goal

Reach real industry-standard community media platform parity or better, not
"close enough."

Do not name specific incumbent vendors in public repo-facing roadmap, marketing,
or release documents unless Scott explicitly approves it for that document. Use
"industry-standard community media platform," "incumbent platform," or a
feature-specific generic description instead. Internal research can cite named
vendors outside public release material when needed, but public docs should not
draw competitor attention before CivicCast is ready.

The v2.0 claim is that CivicCast can serve as a full community-media platform
for public-facing live/VOD/schedule operations, native TV/mobile distribution,
24/7 bulletin-board channel operation, contributor workflows, privacy-safe
reporting, remote ingest, and the major broadcast-facility integrations named
in the parity addendum.

## Baseline

v1.7.3 is complete for the 1.x target:

- GitHub Release installer is published.
- Windows release asset SHA matched.
- Install, launch, first-screen render, running-app uninstall, process cleanup,
  executable cleanup, and uninstall registry cleanup passed on the Windows
  tester.
- Closed 2026-07-21: the uninstall smoke had observed a small
  `shutdown-request` marker file after uninstall. It never blocked the release
  criteria — no app process, installed executable, or registry entry remained —
  and the keep-data uninstall path now removes both the marker and the emptied
  program folder.

Future v1.7.x work should be limited to beta-found fixes, security fixes, or
release-process repairs. New parity features start at v1.8.0.

## Process

Each stage uses one branch:

```text
stage/<version>-<short-scope>
```

Inside each stage, work in small slices. After each slice:

1. Run `audit-lite`.
2. Fix every finding.
3. Rerun `audit-lite`.
4. Repeat until clean or genuinely blocked by a human-required decision.
5. Run targeted tests, policy checks, and the pre-push hook.
6. Commit with DCO and push to GitHub.
7. Continue immediately to the next slice.

No meaningful work may live only on disk after a slice closes. Every clean
slice goes to GitHub before the next slice starts.

At the end of each stage:

1. Push the final slice.
2. Run `audit-full` on the pushed branch.
3. Fix every finding.
4. Rerun `audit-full`.
5. Repeat until `0 Blocker / 0 Critical / 0 Major / 0 Minor / 0 Nit`, or a
   genuine human-required blocker is recorded.
6. Merge to `main`.
7. Tag the stage.
8. Stop only then with a full status report.

Use local cleanroom, VM, GPU, browser, and package smoke testing whenever
possible. Bring in the separate Windows tester only when local testing cannot
reasonably prove the release surface.

## Version Ladder

The ten implementation stages run from `v1.8.0` through `v1.8.9`.
`v2.0.0` is the final parity release tag after all ten stages are complete,
integrated, audited, and release-smoked.

### Stage 1 - v1.8.0 - Parity Architecture, Contracts, And All-App Skeletons

Purpose: prevent every future parity feature from becoming a one-off.

Required outcomes:

- Canonical channel/content/app platform architecture.
- Public API contracts for channel config, branding, live state, VOD catalog,
  schedules, captions, audio tracks, chapters, playback policy, analytics
  events, CG feeds, and contributor workflow hooks.
- Shared app config format covering unbranded and branded station builds.
- Thin but real shells for Web/PWA, Roku, tvOS, Fire TV, Android TV, Android
  mobile, and iOS/iPadOS.
- Each shell loads the same station config and renders channel identity, live
  status, schedule placeholder, and VOD placeholder from the shared contract.
- Contract tests proving all app shells consume the same model, not forked
  platform-specific schemas.

Exit criteria:

- All target app surfaces exist in-repo.
- One seeded station config drives every shell.
- Generated API docs and app-contract docs are published under `docs/`.
- Local proof demonstrates the walking skeleton across all feasible local
  surfaces; non-local store/device gaps are documented as test waivers only for
  skeleton proof.

### Stage 2 - v1.8.1 - Core Channel Platform And Public Media APIs

Purpose: make the shared app and channel model real.

Required outcomes:

- Channel identity and branding tokens.
- Live stream metadata and playback URLs.
- VOD catalog APIs with series, topics, smart playlists, thumbnails, captions,
  audio tracks, chapter metadata, and publish state.
- Schedule and "coming up next" APIs suitable for public apps, CG, EPG export,
  and portal use.
- Privacy-safe analytics event ingestion contract.
- Public-record guardrail metadata exposed to downstream playback policy.
- Operator UI controls for channel/app config that match the design spec.

Exit criteria:

- Public API and operator UI can configure a station/channel once and serve it
  to Web/PWA plus every native app shell.
- Smart playlist behavior is deterministic and tested.
- OpenAPI/generated client artifacts are current.

### Stage 3 - v1.8.2 - Native OTT And Mobile App Suite

Purpose: close incumbent platform's largest audience-visible gap.

Required outcomes:

- Production-grade reference apps for Roku, tvOS, Fire TV, Android TV, Android
  mobile, and iOS/iPadOS.
- Web/PWA remains aligned as the browser reference client.
- Live playback, VOD library, smart playlists, schedule browsing, captions,
  audio track selection, chapters, and station branding work consistently.
- Basic unbranded build tier.
- Branded station build tier with app name, icon, splash, colors, and channel
  settings.
- Store-readiness checklists and certified-integrator packaging guidance.
- Monitoring checklist for broken stream/config/app connections.

Exit criteria:

- Every app can be built from the same station config contract.
- Platform-specific differences are documented, tested, and intentional.
- At least one living-room platform and one mobile platform have executable
  local/device proof; remaining store-publication steps are documented as
  external account/process requirements, not product gaps.

### Stage 4 - v1.8.3 - Full Multi-Zone CG Bulletin Board

Purpose: support 24/7 channel operation, not just event streaming.

Required outcomes:

- Multi-zone CG model with primary content, ticker/news, schedule, sponsor/logo,
  and optional audio zones.
- Template library and visual layout editor.
- RSS, iCal/CalDAV, weather API, and permitted social feed adapters.
- Community bulletin submission and approval queue for non-operator staff or
  organizations.
- Between-streams portal display.
- HLS-rendered channel output path for streaming CG.
- Integration contract for future cable L-bar/overlay rendering.

Exit criteria:

- A station can run a 24/7 branded bulletin-board channel with dynamic feeds and
  approved community announcements.
- CG output can feed the portal and streaming channel path.

### Stage 5 - v1.8.4 - Contributor Portal And Producer Workflow

Purpose: close the community-media producer workflow gap.

Required outcomes:

- Contributor account tier distinct from viewer and operator accounts.
- Contributor upload flow with title, description, tags, producer name, air-date
  request, agreements, and status notifications.
- Operator review queue for accept, decline with reason, broken-media gate,
  metadata edit, and schedule handoff.
- Producer activity reporting for grant/franchise use.
- Terms-of-submission agreement logging per submission.

Exit criteria:

- External producers can submit content without operator credentials.
- Operators retain final control over what airs and what publishes.

### Stage 6 - v1.8.5 - Playback Policy: Gated Access And Preroll

Purpose: add industry-standard private access and preroll features without
weakening public-record obligations.

Required outcomes:

- Per-channel and per-asset access tiers: public, authenticated, invite-only.
- Viewer accounts distinct from operators and contributors.
- Optional OIDC for organizations.
- Authenticated RSS for gated podcast feeds.
- Hard guardrails preventing gating on public-record meeting assets or completed
  public archive outputs.
- Per-channel and per-asset preroll configuration.
- Video prerolls and static graphic-card prerolls.
- Stacked preroll sequences, skippability rules, and accessibility defaults.
- Playback audit log recording active policy/preroll at playback time.

Exit criteria:

- Gated/private content works for non-public-record content.
- Public-record assets cannot be accidentally gated.
- Prerolls affect playback only, not archival exports or signed transcript
  exports.

### Stage 7 - v1.8.6 - Expanded Analytics, Reporting, And EPG Export

Purpose: meet grant, franchise, and operator reporting requirements while
preserving CivicCast's privacy posture.

Required outcomes:

- Per-asset view time series.
- Live concurrent viewer trends.
- Country/state-level geography only.
- Device/platform breakdown without per-viewer tracking.
- Caption/audio usage reporting.
- Subscription growth trends.
- Podcast download counts.
- Optional GA4 integration with required privacy notice.
- TV Guide X-List / EPG export from schedule data.
- Analytics data-model documentation for privacy/legal review.

Exit criteria:

- Reports are useful for station operations and grant/franchise reporting.
- No per-viewer session, per-IP tracking, or cross-session identity is required
  by default.

### Stage 8 - v1.8.7 - Cloud RTMP Relay And Remote Meeting Ingest

Purpose: remove inbound-firewall exposure as a barrier for remote/virtual
meetings.

Required outcomes:

- Optional cloud RTMP relay endpoint.
- Station outbound-only relay path back to civiccast-live.
- Direct-to-syndication mode for YouTube Live and Facebook Live when station
  hardware is offline.
- Self-hosted local RTMP remains the default free path.
- Integrator-hosted/project-hosted deployment documentation.
- Failure-state monitoring and operator visibility.

Exit criteria:

- A virtual meeting can reach CivicCast without inbound station network access.
- A remote stream can be fanned out to configured social destinations when
  enabled.

### Stage 9 - v1.8.8 - Broadcast Facility Integrations

Purpose: cover narrower but real incumbent platform parity requirements for facilities
with existing broadcast hardware and live graphics workflows.

Required outcomes:

- AV router control module for Blackmagic Design, Ross Video, Utah Scientific,
  Evertz, and generic TCP/UDP command devices.
- RS-232 serial support through USB-to-serial adapters.
- Router scheduling integration for automatic source takes.
- Mobile-friendly virtual router control panel.
- Caption hardware integration layer for ENCO enCaption and other appliances
  outputting CEA-608/708, SRT, or WebVTT.
- External caption output surfaces in the same operator review queue as local
  Whisper captions.
- Streaming overlay compositor for squeezebacks and L-bar templates.
- GPU-accelerated HLS compositing where available.
- Defined overlay z-order with bugs, lower-thirds, emergency overlays, L-bars,
  and squeezebacks.

Exit criteria:

- CivicCast can operate with common router/caption hardware already owned by
  PEG stations.
- Operators can trigger and schedule routing and L-bar/squeezeback workflows
  from the operator UI.

### Stage 10 - v1.8.9 - Parity Integration, Migration, Proof, And Docs

Purpose: turn the completed feature set into a coherent v2.0 release candidate.

Required outcomes:

- Cross-feature integration testing across apps, CG, contributor workflow,
  gated/preroll playback, analytics, EPG export, RTMP relay, and broadcast
  integrations.
- Migration and upgrade path from v1.7.3 installations.
- Full documentation set for operators, contributors, viewers, integrators, and
  station admins.
- incumbent platform parity matrix with every addendum gap marked complete, waived with
  an explicit external dependency, or blocked by a human decision.
- Public claim-boundary review: no overclaiming app-store publication, hardware
  certification, legal compliance, or managed-service operation unless proven.
- Release candidate package and local cleanroom proof.
- Remote tester/device proof only where local proof cannot cover the target.

Exit criteria:

- All ten parity gaps have implementation evidence.
- All docs, APIs, apps, and installer identity align.
- Full audit is clean or blocked only by explicit human-required external
  account/device/certification items.

## v2.0.0 Final Release

Tag `v2.0.0` only after:

- `v1.8.0` through `v1.8.9` are merged and tagged.
- The final parity matrix shows every incumbent platform addendum gap complete or
  explicitly externally blocked.
- `audit-full` is clean at `0/0/0/0/0` or has only human-required blockers.
- Installer/package release asset smoke passes.
- App/platform proof bundle is complete for all supported targets.
- The public docs describe what is proven, what requires integrator/store
  action, and what remains outside CivicCast's responsibility.

## incumbent platform Feature Coverage Matrix

| incumbent platform parity gap | Primary stage | Secondary stages |
| --- | --- | --- |
| Native OTT & mobile app suite | v1.8.2 | v1.8.0, v1.8.1, v1.8.9 |
| Gated/private video access | v1.8.5 | v1.8.1, v1.8.9 |
| VOD preroll messaging | v1.8.5 | v1.8.1, v1.8.9 |
| Full multi-zone CG bulletin board | v1.8.3 | v1.8.1, v1.8.8, v1.8.9 |
| AV router control | v1.8.8 | v1.8.1, v1.8.9 |
| ENCO enCaption integration | v1.8.8 | v1.8.1, v1.8.9 |
| Squeezebacks and L-bar live overlays | v1.8.8 | v1.8.3, v1.8.9 |
| RTMP cloud ingest relay | v1.8.7 | v1.8.1, v1.8.9 |
| Expanded audience measurement/reporting | v1.8.6 | v1.8.1, v1.8.9 |
| Contributor submission portal | v1.8.4 | v1.8.3, v1.8.6, v1.8.9 |

## Immediate v1.8.0 Work Slices

1. Reference import and roadmap.
   - Track the 2.0 parity addendum and design spec in the repo.
   - Add this v1.8-to-v2.0 release plan.
   - Run audit-lite, fix findings, test doc links, commit, and push.

2. Contract inventory.
   - Inventory existing channel, schedule, live, VOD, publish, caption,
     analytics, installer, and portal contracts.
   - Identify what can be reused for the shared channel platform and what must
     be replaced before native apps depend on it.

3. App-platform contract draft.
   - Add OpenAPI/schema artifacts for station app config, channel config, VOD
     catalog, live state, schedule feed, captions/audio/chapter metadata, and
     analytics event ingestion.

4. All-app skeleton scaffold.
   - Add minimal platform directories or documented harnesses for Roku, tvOS,
     Fire TV, Android TV, Android mobile, iOS/iPadOS, and Web/PWA alignment.
   - Prove every shell can load the same seeded config fixture.

5. v1.8.0 close-out.
   - Run full tests/policy.
   - Run `audit-full`, fix to clean, merge, tag `v1.8.0`, and report.

CivicCast 2.0 — incumbent platform Parity Feature Addendum

**Status:** Post-v1.0 roadmap draft  
**Scope:** Features required to close the capability gap between CivicCast (after spec.md v2.0.0 is fully delivered) and incumbent platform Community Media's current product suite  
**Assumes:** All Phase 0–2 spec.md deliverables are complete and stable. The civiccast-cable Phase 3+ add-on is funded and underway separately. This addendum covers the remaining gaps beyond the cable stack.

---

## Gap 1 — Native OTT & Mobile App Suite

**What incumbent platform has:** Turnkey branded native apps for Roku, Apple TV (tvOS), Amazon Fire TV, Android TV, Android mobile (Google Play), and iOS/iPadOS (App Store). incumbent platform manages app store compliance, submits updates, and proactively monitors for broken connections. Basic unbranded apps ship with a REFLECT subscription; branded apps are an upgrade. Stations get a fully maintained living-room presence without a developer.

**What CivicCast v1 has:** A Web PWA (installable on iOS and Android home screens) and reliance on the YouTube app for TV screens. The spec explicitly deferred everything else to Phase 4+ contingent on funding.

**What 2.0 needs to build:**

A reference native app codebase for each major TV and mobile platform, maintained under CivicCast/*, consuming CivicCast's public VOD, live stream, and schedule APIs. The apps must automatically update the VOD library, surface the live stream with captions, and support per-channel subscription sign-up. The deployment model needs to accommodate two tiers — a basic unbranded app (station URL configured at build time, no custom branding) and a branded tier (custom app name, icon, splash screen, and color scheme pulled from channel settings). App store compliance, update submission, and monitoring should be handled by the certified-integrator program rather than centrally, mirroring how incumbent platform does it without requiring a CivicCast Network entity.

Specific platforms in priority order based on audience share for civic content: Roku (largest civic content audience on TV), Apple TV, Amazon Fire TV, Android TV, Android mobile, iOS. The Roku reference app is already called out in the spec as Phase 4+ contingent on PEG-consortium funding; the 2.0 addendum formally schedules all six platforms together and requires that all six share a common API client library so the station's channel config, branding tokens, and content model are defined once.

Smart VOD playlists (automatically sorted by series, topic, or meeting body with no operator effort) must work identically across all platforms, matching what incumbent platform's streaming apps do today. Closed caption track selection, audio track switching, and chapter navigation must be accessible from within each app's native playback UI.

---

## Gap 2 — Gated / Private Video Access

**What incumbent platform has:** A gated video access feature that restricts viewing of specific VOD content to authenticated viewers. Used by school districts for classroom content, by houses of worship for member-only archives, and by municipalities for pre-release or executive-session-adjacent content.

**What CivicCast v1 has:** No access control on VOD content beyond the operator/staff distinction. Everything on the public portal is public.

**What 2.0 needs to build:**

A per-asset and per-channel access policy layer on top of the existing VOD module. Access policies should support three tiers: public (default, current behavior), authenticated (requires a viewer account), and invite-only (requires a token or a specific credential). Viewer accounts are distinct from operator accounts — they are resident-facing logins with minimal PII, managed separately from the RBAC system. Authenticated access should support password-based viewer login and optionally SSO via OIDC for organizations (school districts, houses of worship) that have an existing identity provider.

The gating layer must not break the public-record obligations codified in the spec. Any asset or channel marked as a public record must remain on the public access tier regardless of any operator misconfiguration — the gate should be physically impossible to engage on assets with meeting_body=true or on assets whose publish pipeline has already completed a three-tier public archive. Gating is only available on non-public-record content.

Podcast feeds for gated channels should support authenticated RSS (token-in-URL or Basic Auth), so a member of a house of worship can subscribe to private service archives without that content being publicly indexable.

---

## Gap 3 — VOD Preroll Messaging

**What incumbent platform has:** A preroll messaging feature that prepends a configurable short video or graphic card to VOD playback. Used for sponsor acknowledgments, public-service announcements, accessibility notices, and legal disclaimers before a recorded meeting plays.

**What CivicCast v1 has:** Nothing. VOD playback begins immediately at the asset.

**What 2.0 needs to build:**

A per-channel and per-asset preroll configuration in the VOD module. Prerolls should support both video clips (uploaded as assets and transcoded to match the VOD ladder) and static graphic cards (a JPEG/PNG with duration and optional text overlay). Multiple prerolls should be stackable in a defined sequence. Prerolls must be skippable after a configurable delay (default: non-skippable for accessibility notices, skippable after 5 seconds for others), consistent with the WCAG commitment.

The preroll system must be transparent to the archival pipeline — prerolls are not prepended to Internet Archive uploads or to signed transcript exports. They are a playback-layer feature, not a content feature. The audit log captures which preroll configuration was active at the time of each playback session for reporting purposes.

---

## Gap 4 — Full Multi-Zone CG Bulletin Board for Streaming

**What incumbent platform has:** incumbent platform CG — a complete multi-zone digital signage system with pre-built channel designs, a template library, dynamic bulletins pulling from RSS, iCal, weather, traffic, and social media feeds, L-bar integration with live video, a "Coming Up Next" display, a "You Were Just Watching" display, background audio, and roles-based access for non-technical staff to update community bulletins. It runs 24/7 as the between-programming filler and as a persistent frame around live content on cable.

**What CivicCast v1 has:** civiccast-cg, which is intentionally scoped to only an idle page (logo, next-event countdown, featured VOD, one-line announcement) and an emergency overlay. The spec explicitly cut multi-zone CG for the streaming-first scope.

**What 2.0 needs to build:**

A full multi-zone CG system for the streaming-first portal and live channel. Unlike the cable CG (which renders to SDI and belongs in the cable add-on), this version renders to the HLS stream and the portal idle page. It should support at minimum: a primary content zone, a news/announcement ticker zone, a schedule zone showing the next 2–3 events with times, and a sponsor/logo zone. Zone layout should be configurable from a set of pre-built templates with a visual layout editor.

Dynamic content feeds should include: RSS (news, press releases, local alerts), iCal/CalDAV (community calendar events), weather via a configured weather API, and social media feeds where platform APIs permit it. Content submission by non-operator staff (community organizations submitting bulletin-board announcements) should work through a content submission portal with a configurable approval queue — matching incumbent platform's community-contributor workflow.

Background audio during the idle/between-streams page (royalty-free music, public-domain audio) should be supported as an optional configuration.

This CG system feeds both the between-streams portal display and, when the cable add-on is installed, the cable-specific L-bar and overlay rendering handled by civiccast-cable.

---

## Gap 5 — AV Router Control

**What incumbent platform has:** RS-232 and IP-based control of external AV routing switchers, allowing incumbent platform to switch between sources on a physical router as part of the automation schedule. This is used in facilities with multiple SDI sources routed through a central patch matrix.

**What CivicCast v1 has:** No router control. Source switching is handled by civiccast-live managing IP sources (NDI, RTMP, RTSP, SRT) at the software level.

**What 2.0 needs to build:**

An AV router control module (civiccast-router) that implements IP-based control protocols for common router brands used in broadcast facilities — Blackmagic Design, Ross Video, Utah Scientific, and Evertz as the initial set — plus a generic TCP/UDP command interface for less common devices. RS-232 serial control should be supported via USB-to-serial adapters, the primary physical connection method in existing installations.

Router control is not a standalone feature — it connects into the scheduling and live-source system so that a scheduled live event can automatically issue a router take command at the scheduled start time, routing a physical SDI source through the router and into the capture input. This brings CivicCast to parity with incumbent platform for facilities that have invested in an AV router infrastructure.

The module should include a virtual control panel in the operator UI, exposing the router's source/destination matrix as a visual grid usable from a phone, matching the mobile-first UX non-negotiable.

---

## Gap 6 — ENCO enCaption Integration

**What incumbent platform has:** Integration with ENCO enCaption hardware captioning appliances, allowing stations that have already purchased enCaption hardware to manage and display its output within the incumbent platform interface.

**What CivicCast v1 has:** No integration with third-party captioning hardware. The spec's captioning module is entirely software-based (faster-whisper).

**What 2.0 needs to build:**

A captioning hardware integration layer in civiccast-captions that can receive caption output from external captioning appliances via their standard output protocols — primarily CEA-608/708 streams from enCaption, and secondarily SRT/WebVTT output from other hardware captioners. The integration should surface the external captioner's output in the same operator review queue as locally generated Whisper captions, so the station's review workflow is identical regardless of whether a human CART provider, a hardware captioner, or local Whisper is producing the captions.

This is valuable not because CivicCast's local Whisper is inferior to enCaption (it isn't, by most measures) but because stations that have already purchased and paid for enCaption hardware should not have to abandon that investment to adopt CivicCast.

---

## Gap 7 — Squeezebacks & L-Bar Live Overlays

**What incumbent platform has:** Squeezebacks (scaling the main video into a reduced frame size) and L-bar overlays (surrounding the video with a graphic frame) during live playout, typically used to present sponsor messages, public-service announcements, or emergency information alongside live content without interrupting the broadcast.

**What CivicCast v1 has:** Emergency overlay on the live stream (full-screen or partial). No squeezeback or L-bar rendering in the streaming HLS output.

**What 2.0 needs to build:**

An overlay compositor in civiccast-stream that can apply L-bar and squeezeback templates to the HLS output stream in real time. The compositor should accept a set of pre-configured overlay layouts (defined by a template system matching the CG module's template library) and switch between them via the operator UI during a live broadcast. Operators should be able to trigger a squeezeback with a sponsor message, sustain it for a configured duration, and release back to full-screen from their phone.

The compositing should be GPU-accelerated using the same NVENC/VA-API path already used for HLS encoding, keeping the performance impact minimal on the Tier 1 reference build. The compositor should be aware of the existing lower-third and bug overlay system so all overlay layers are composited in a defined z-order without conflict.

---

## Gap 8 — RTMP Cloud Ingest for Cable (Streaming Tier)

**What incumbent platform has:** incumbent platform RTMP as a standalone cloud service that accepts virtual meeting streams (Zoom, Teams, WebEx RTMP output) and routes them to cable, web, streaming apps, YouTube Live, and Facebook Live simultaneously from a single cloud dashboard, with no need to have access to the local hardware.

**What CivicCast v1 has:** civiccast-live handles RTMP ingest, but the ingest endpoint runs on the station's local server. Remote RTMP ingest requires network access to the station (port forwarding, VPN, or public IP), which is an operational barrier for many stations.

**What 2.0 needs to build:**

A cloud RTMP relay service that accepts inbound RTMP streams at a cloud endpoint and forwards them to the station's civiccast-live ingest path without requiring any inbound network exposure on the station side. This is architecturally a lightweight RTMP relay (stations push to the cloud relay; the relay pushes into the station's outbound-only WebSocket or SSE channel), not a full cloud encoding service.

The relay should also support direct-to-syndication mode, where an inbound stream is fanned out to YouTube Live and Facebook Live from the cloud relay without requiring the station's server to be online at all — covering the scenario where a remote meeting must get to social platforms even if the station's primary hardware is temporarily offline.

The self-hosted path (station exposes RTMP endpoint directly) remains the default and costs nothing. The cloud relay is an optional add-on operated by certified integrators or a project-hosted relay for stations that need it. This matches incumbent platform RTMP's value proposition without requiring the project to operate a permanent cloud service.

---

## Gap 9 — Audience Measurement & Reporting (Expanded)

**What incumbent platform has:** Audience measurement across cable, web, OTT, and mobile platforms — view counts, live viewer counts, reporting dashboards, Google Analytics integration, and TV Guide X-List export for EPG systems.

**What CivicCast v1 has:** Aggregate-only view counts (total views per asset, total concurrent live viewers, total bandwidth). Explicit privacy posture: no per-viewer identification. Stations may optionally add third-party analytics.

**What 2.0 needs to build:**

An expanded analytics module (civiccast-analytics) that provides station-level insight without compromising the privacy posture. The module should produce: per-asset view counts with time-series breakdown (views per day/week), per-channel concurrent viewer trends during live events, geographic distribution (at the country/state level, not the IP level), device/platform breakdown (desktop web, mobile web, PWA, YouTube, podcast app — inferred from user-agent and referrer without per-viewer tracking), caption track selection rates (what percentage of viewers use captions, and in which language), subscription growth trends per channel, and podcast download counts per episode.

All analytics must remain aggregate-only and privacy-safe by default. No per-viewer sessions, no per-IP logging, no cross-session identity. The module's data model should be explicitly documented so stations can demonstrate GDPR/CCPA compliance to counsel.

TV Guide X-List export for EPG systems should be added to civiccast-schedule — a standard EPG data format that cable and IPTV headend systems use to pull program guide data. This is a low-complexity integration that removes a specific barrier for any station trying to feed a multi-channel EPG alongside CivicCast.

Google Analytics integration (GA4) as an optional opt-in for stations that need it for grant reporting, with a required privacy notice on the public portal when enabled.

---

## Gap 10 — Content Submission Portal for Community Contributors

**What incumbent platform has:** A content submission portal that allows external community members, organizations, and producers to upload video content for review and scheduling — with producer tracking, user accounts, and permissions distinguishing contributors from operators.

**What CivicCast v1 has:** Operator-only asset upload. No external contributor workflow.

**What 2.0 needs to build:**

A producer/contributor portal (civiccast-contribute) with its own authentication tier below the operator level. Community producers should be able to create a contributor account, submit video files for operator review, attach metadata (title, description, tags, producer name, air-date requests), and receive status notifications (submitted, under review, accepted, scheduled, declined with reason).

Operators manage the contributor queue: review submitted files, run the broken-media gate, accept or decline with a templated or custom message, and schedule accepted content to the channel. The operator never loses control over what airs — the contributor portal is a submission system, not a self-service publishing system.

Producer tracking should record which contributor submitted which content, allowing reporting on contributor activity for grant applications and franchise reporting. Configurable content-submission agreements (contributors must accept terms of service before uploading) should be logged per submission.

This closes the community media workflow gap: a PEG station that uses CivicCast as its full platform can accept community producer submissions through the same system it uses to manage everything else, rather than relying on a separate Google Form, Dropbox folder, or email workflow.

---

## Summary Priority Order

Ranked by gap impact on stations most likely to consider switching from incumbent platform, taking into account audience breadth, operational barrier, and implementation complexity:

1. **Native OTT & Mobile App Suite** — highest audience visibility gap; stations evaluate this first  
2. **Full Multi-Zone CG Bulletin Board** — required for 24/7 community channel operations  
3. **Content Submission Portal** — needed for any community media station managing external producers  
4. **Expanded Audience Measurement & Reporting** — grant reporting and franchise reporting requirements  
5. **Gated Video Access** — needed for school districts and houses of worship  
6. **RTMP Cloud Ingest Relay** — enables remote/virtual meeting workflows without inbound firewall exposure  
7. **VOD Preroll Messaging** — low complexity; common operational request  
8. **AV Router Control** — needed only for facilities with physical router infrastructure  
9. **Squeezebacks & L-Bar Overlays** — cable-era feature; lower priority for streaming-first stations  
10. **ENCO enCaption Integration** — needed only for stations with existing enCaption hardware investment  

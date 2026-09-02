# CivicCast Roadmap

> **Current release:** `v1.0.0-beta.1` (USB-delivered); `v1.0.0-beta.2` was
> never published -- it exists only as an internal Gate A upgrade-baseline
> kit. `v1.0.0-beta.3` is the current owner-held unpublished candidate and is
> intended to be the first downloadable one. See
> [`docs/releases/release-truth.yaml`](releases/release-truth.yaml) for the
> authored release-state record. (The `v1.0.0-rc18` release named on this
> page below was the retired, separate WSL2 line's -- repository
> `scottconverse/civiccast`, not this repository -- last published release;
> its GitHub release page and verification record are not present here.)
>
> **About the numbering on this page:** the `0.1.0` / `0.2.x` / `0.3.x` labels below are
> *capability rungs* on the road to a 1.0 general release — they are not the version you
> download. The shipping artifact is versioned separately on the `v1.0.0-rcNN` release-candidate
> line. A rung is "Now" when its capability is proven, regardless of the installer's rc number.

A plain-English view of where CivicCast is today and where it's headed. "Now" is the
capability rung the product has actually reached. "Next" and "Later" are ordered by
dependency — each step generally needs the one before it.

This roadmap describes intent and sequence, not committed dates. Rung numbers advance
as each step lands and passes its own verification.

## Now -- rung 0.1.0 (shipped as `v1.0.0-rc18` on the retired WSL2 line)

The proven operator core, plus public video viewing working out of the box:

- 24/7 channel playout, scheduling, and on-channel bulletins/graphics.
- Live ingest (RTMP/RTSP/NDI/SRT) and scheduled recording from cameras and network streams.
- A production control room for camera/scene switching during a live meeting or broadcast.
- Captions, translation, and loudness handling.
- The public portal: residents can now **watch both recorded meetings and live
  broadcasts** directly, with no extra setup required. This was the last major gap in
  the everyday experience and is the headline of this release.
- As-run logging, proof-of-performance reporting, and underwriting/sponsorship tracking.
- A Windows installer that provisions everything the station needs on a single commodity
  PC, self-hosted, with no recurring cloud bill for the platform itself.

**Known limits at this rung:** viewing is proven at small-to-moderate audience sizes served
directly from the station's own machine, not yet load-tested at large scale; agenda
import and migration from other systems is not yet automated; disaster-recovery failover
is partial (backup write/read/delete and a scoped database restore drill were proven on
the retired WSL2 line's rc18 -- that verification record is not present in this
repository -- but automatic
failover that keeps a channel on air through a hardware failure is not yet built); archive/tape
workflows and broad third-party audio hardware support are not yet built out.

## Next

### 0.2.x — Scale and delivery hardening
Prove public viewing holds up for a real public meeting with a large audience, not just a
handful of testers. This means CDN-backed delivery options (so a big audience doesn't all
pull video from one station PC) and a real load test at meaningful concurrent-viewer
scale, with the results published.

**0.2.0 progress so far (not yet complete — measured and published where noted below):**
the direct-from-station ceiling is now measured —
about **216 HD (1080p) viewers on a 1 Gbps link** (fewer on slower connections), bound by
the station's upload speed rather than the software
([direct-delivery ceiling](releases/0.2.0-direct-delivery-ceiling.md)). To carry a bigger
crowd, 0.2.0 adds an **automatic CDN surge switch** (off by default): under load the
station publishes one copy to a CDN and hands viewers off, then releases back to local at
idle. The switch is **validated end-to-end in the lab — a simulated crowd rides it with
zero stalls, it holds the CDN copy fresh under load, and it evicts at idle**
([switch validation](releases/0.2.0-switch-validation.md)); provisioning the reference CDN
is reproducible via OpenTofu, an infrastructure-automation tool (`deploy/tofu/cdn-r2`). The remaining claim — that a **real**
CDN then holds *thousands* of concurrent viewers — is measured at beta against a real CDN,
not asserted from the lab.

### 0.3.0 — Agenda import
Bring meeting agendas in automatically instead of manual entry, starting with the most
common government agenda-management systems and expanding from there, so agenda items
sync to video timecodes with minimal staff effort.

### 0.4.0 — Migrating from other systems
Import existing recordings, schedules, and metadata from other PEG/broadcast automation
systems stations already use today, so switching to CivicCast doesn't mean losing
historical records or starting over.

## Later

### 0.5.0 — Redundancy and disaster recovery
Complete failover and recovery so a hardware failure doesn't take a channel off the air
or lose in-progress recordings. Includes tested backup/restore drills, not just backup
files that have never been restored.

### 0.6.0 — Archive and production depth
Bring older tape-based archives into the system (digitization workflows), broaden support
for third-party audio mixers and hardware beyond what's been tested so far, and round out
day-to-day producer tooling based on real operator feedback.

### 0.7.0 — Education vertical and device certification
Extend the platform to school-board and education use cases, and move hardware support
claims (capture cards, SDI output, etc.) from "should work" to actually certified against
real devices.

### 0.8.0 – 0.9.0 — Field hardening
Extended real-world soak testing — sustained multi-day production use, not just lab runs —
plus performance tuning and security hardening based on what that surfaces.

### 1.0.0 — Public, field-proven
Every capability above is either genuinely finished or honestly and clearly scoped as a
known limitation — no capability is claimed as done without evidence behind it. CivicCast
has been running in real, sustained production use at one or more stations, not just in a
lab. At that point CivicCast graduates from controlled beta (already available today, at
`v1.0.0-rcNN`) to a fully supported 1.0 general release.

## How this roadmap is used

Each step above ships as its own version, gets verified against its own goal before the
next step starts, and is reflected here as it lands. If a step turns out to need
splitting or reordering, this document updates to say so honestly rather than silently
dropping a promise.

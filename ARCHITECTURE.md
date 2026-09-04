# CivicCast Architecture

> **Release state: `v1.0.0-beta.4` is the current release**, a download-only
> upgrade for stations already on `v1.0.0-beta.3` (the first downloadable
> release, now superseded) -- `setup.exe` and the runtime `.ccpack` packs
> are attached to its [GitHub Release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.4).
> It is still a beta, not a finished production release; it describes the
> state a technical reviewer finds by checking out `main` today. See
> [BRANCHES.md](BRANCHES.md) for release identity and status.
>
> Treat the repository state as bounded source and local contract-lab proof,
> not as approval of any withdrawn candidate or as broad validation across
> many machines, live external provider delivery, app stores, live hardware,
> downstream cable headends, QAM, SDI/DeckLink, EAS, CEA-708 broadcast
> compliance, or production operations. Local contract-lab work is
> development work and must not be described as public-beta, LPM field, or
> production proof until its own gates pass and station-device evidence is
> attached.

> **This repository ships one product line: native Windows.** Earlier
> revisions of this notice described "two parallel Windows product lines"
> shipping from this repository -- that described the OLD
> `scottconverse/civiccast` repository. This repository (`civiccast-native`)
> was created by copying only the native product out of it with fresh
> history, and the WSL2 lane was retired outright under the owner's "no
> linux" decision (2026-08-19). See [BRANCHES.md](BRANCHES.md) for the full
> explanation and where the retired line's history now lives (private, not
> archived).
> differs architecturally.

This document orients engineers and integrators to the current CivicCast
system. The binding product contract is
[docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md](docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md);
the earlier [docs/spec/spec.md](docs/spec/spec.md) is superseded and retained
for historical reference only (its own header says so).

## System Shape

CivicCast is a self-hostable civic broadcast platform. A single FastAPI
umbrella app mounts the public, staff, installer, release, and federation
routers. Three Vite/React frontends cover the operator console, resident portal,
and installer shell. Installer-managed local SQLite is the default durable data
store for operator and beta use; technical deployments can point `DATABASE_URL`
at Postgres. In-memory stores exist for tests and throwaway development only.

```mermaid
flowchart LR
    Operator["Operator console"]
    Resident["Resident portal"]
    Installer["Installer app"]
    API["FastAPI umbrella app"]
    DB[("Durable DB")]
    CDN["CDN adapters"]
    AI["Local AI runtimes"]
    External["Archive, NAS, YouTube, email/webhooks"]

    Operator -->|staff bearer token| API
    Resident -->|public read APIs| API
    Installer -->|bootstrap and health checks| API
    API --> DB
    API --> CDN
    API --> AI
    API --> External
    Resident --> CDN
```

## Runtime Entry Points

- `civiccast/app.py` builds the FastAPI app and wires router dependencies.
- `civiccast/cli.py` exposes operator commands such as `doctor`, `token`,
  `installer`, `model`, `cert`, and `cable`.
- `civiccast/apps/portal-operator/` is the staff/operator console.
- `civiccast/apps/portal-public/` is the resident portal and HLS playback UI.
- `civiccast/apps/installer/` is the Tauri-compatible installer shell.
- `alembic/` plus per-module migration directories manage schema changes.

## Major Modules

| Area | Package | Responsibility |
| --- | --- | --- |
| Platform | `civiccast.platform` | Hardware probe, broker contract, store bundle. |
| Auth | `civiccast.auth` | Staff bearer-token middleware and token lifecycle store. |
| Streaming | `civiccast.stream`, `civiccast.vod` | HLS packaging, public embeds, CDN upload. |
| Schedule | `civiccast.schedule` | Assets, premieres, embargoes, operator asset library. |
| Live | `civiccast.live` | Live sessions, fail-closed source verification, and recording finalization. |
| Captions | `civiccast.captions` | Faster-whisper contracts, stabilization, WebVTT output, review queue. |
| Summary | `civiccast.summary` | Sourced summaries, approval, transcript CSV export. |
| Records | `civiccast.records` | PDF/A-3B signed-record export and provenance. |
| Publish | `civiccast.publish` | Portal, Internet Archive, NAS, YouTube, subscriber, and podcast surfaces. |
| Subscribe | `civiccast.subscribe` | Double opt-in, signed unsubscribe, webhook payloads. |
| Podcast | `civiccast.podcast` | Podcast episode and RSS generation. |
| Installer | `civiccast.installer` | First-run plan, fail-closed health checks, handoff summaries. |
| Cable | `civiccast.cable` | PEG/headend file packages and NDI planning/readiness. |
| ActivityPub | `civiccast.activitypub` | Opt-in station actor with signed federation, durable follower/outbox state, and operator federation controls. |

The stock build has no configured production media probe, so `civiccast.live`
fails closed on live-start until an operator connects one.

## Data And Durability

CivicCast prepares a durable local SQLite database by default when
`DATABASE_URL` is unset, applies the Alembic migration graph, and wires
database-backed stores at app startup. Technical deployments can set
`DATABASE_URL` to use Postgres instead. The app refuses volatile staff-write
stores unless `CIVICCAST_ALLOW_EPHEMERAL_STORES=1` is set explicitly for tests
or throwaway development.

The CDN holds derived HLS bytes. The database remains the source of truth for
asset metadata, schedules, publish state, summaries, signed records,
subscriptions, and podcast state. External provider proofs are credential-gated;
deterministic mocks are not public-provider evidence.

## Core Flows

### Recorded Meeting

```mermaid
sequenceDiagram
    actor Staff
    participant API
    participant DB as Durable DB
    participant Stream as HLS Packager
    participant CDN
    participant Publish

    Staff->>API: Upload or register asset
    API->>DB: Persist asset metadata
    Staff->>Stream: Package recording
    Stream->>CDN: Upload HLS ladder
    Stream->>DB: Store manifest URL
    Staff->>Publish: Approve surfaces
    Publish->>DB: Store per-surface evidence
```

### First Run

The installer and CLI inspect the platform, verify package artifacts, check
local models, confirm local-CA mTLS posture, and report external
provider lanes as blocked until real credentials and controlled proof exist.
Blocked lanes are instructions, not success claims.

### ActivityPub Follow And Publish

```mermaid
sequenceDiagram
    actor Remote as Remote ActivityPub actor
    participant AP as CivicCast ActivityPub router
    participant DB as Durable DB
    participant Staff as Operator Federation screen
    participant Publish as Publish workflow

    Remote->>AP: Signed Follow
    AP->>AP: Verify HTTP Signature, Digest, keyId, domain policy
    AP->>DB: Store pending or accepted follower
    Staff->>AP: Approve, reject, or block pending follower
    AP->>Remote: Signed Accept or Reject
    AP->>DB: Store outbox and delivery evidence
    Publish->>AP: Approved recording creates ActivityPub Note
    AP->>Remote: Signed Create delivery to accepted followers
    Remote->>AP: Signed Undo Follow
    AP->>DB: Mark follower removed unless operator-blocked
```

## Security Boundaries

- `/api/public/*`, `/health`, `/api/version`, and `/api/hardware` are public.
- `/api/staff/*` routes require CivicCast bearer-token authentication.
- Staff tokens are hashed, revocable, rotatable, and auditable when the
  durable lifecycle store is configured.
- Operator deployments must bind FastAPI to loopback or place it behind an
  authenticating reverse proxy; `CIVICCAST_AUTH_ACK=1` only acknowledges that
  network posture.
- Local CA and service key material are part of the security surface. Windows
  writes apply restrictive `icacls` permissions to private keys.
- The machine-readable OpenAPI contract declares the CivicCast staff bearer
  scheme on `/api/staff/*` operations and includes 401 responses.

## Deployment Posture

This repository's Windows product runs CivicCast as a native Windows
service, registered through the SCM under a session-0 identity, built
under [ADR 0021](docs/adr/0021-native-windows-runtime.md) -- no WSL, no
Docker, no Linux install target (see [BRANCHES.md](BRANCHES.md)). The
retired WSL2/Ubuntu-with-systemd deployment described in earlier revisions
of this section belonged to the separate, private `scottconverse/civiccast`
repository. Native Linux is the Linux CI-oriented path. macOS package proof
exists as metadata/posture until signing and notarization funding are
available. Local-CA mTLS is a production-like foundation. The in-process
broker (`civiccast.platform.broker.InProcessBrokerClient`) is the sole
event-bus implementation for all deployments (see ADR 0023, which
supersedes ADR 0001's NATS JetStream choice).

## Beta-Readiness Gates

The current beta-readiness posture closes the audit gates that affected
operator handoff:

- Staff-write stores fail closed without managed durable storage or `DATABASE_URL` unless ephemeral mode
  is explicitly acknowledged for local development.
- OpenAPI exposes the staff bearer-token security scheme for generated clients.
- ActivityPub is disabled by default unless an operator opts in with an
  explicit base URL and station key; when enabled it verifies signed inbox
  traffic, signs outbound delivery, persists federation state, and exposes
  open, limited, approval-only, blocklist, allowlist, and authorized-fetch
  controls.
- Real-Postgres tests exercise summary, records, publish, subscribe, podcast,
  schedule, and live-store paths.
- The installer UI is a guided wizard with an operator-console handoff URL.
- Windows private-key writes apply local ACL restrictions.
- Browser gates include a full-stack operator publish-approval cycle against a
  live FastAPI fixture.

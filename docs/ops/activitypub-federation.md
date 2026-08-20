# CivicCast ActivityPub Federation Ops

CivicCast ships ActivityPub as an opt-in station actor. Fresh installs keep the
surface disabled, which is the right default for civic deployments: no
followable actor is advertised, no inbox traffic is accepted, and no remote
server can fetch federation collections until an operator intentionally enables
the feature.

When enabled, ActivityPub is a real federation path, not a scaffold. CivicCast
uses signed HTTP Signatures for inbox traffic and outbound delivery, persists
followers/outbox/delivery attempts, and gives operators Mastodon-style policy
controls in the operator console Federation screen.

## Modes

Set `CIVICCAST_ACTIVITYPUB_MODE` to one of:

- `disabled` - default. Public ActivityPub routes return disabled/not-found
  responses.
- `open` - accept signed follows from any instance except blocked domains.
- `limited` - accept signed follows only from `CIVICCAST_ACTIVITYPUB_ALLOWLIST`
  or `CIVICCAST_ACTIVITYPUB_ALLOWLIST_FILE`.
- `approval-only` - queue signed follows as pending until staff approve them.

Optional authorized fetch is controlled with
`CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH=1`. When enabled, `/ap/actor`,
`/ap/followers`, and `/ap/outbox` require a valid signed fetch from a remote
actor.

## Enablement

Generate station key material:

```bash
civiccast activitypub keygen \
  --private-key-path C:\CivicCast\secrets\activitypub-station.pem \
  --base-url https://station.example.gov \
  --handle council \
  --mode approval-only
```

The command prints non-secret environment settings and the public key. The
private key stays on disk and should be protected with OS filesystem ACLs.

Required settings for enabled mode:

```bash
CIVICCAST_ACTIVITYPUB_MODE=approval-only
CIVICCAST_ACTIVITYPUB_BASE_URL=https://station.example.gov
CIVICCAST_ACTIVITYPUB_HANDLE=council
CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH=C:\CivicCast\secrets\activitypub-station.pem
CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH=1
```

The app derives `publicKey.publicKeyPem` from the configured private key at
startup. If mode is not `disabled` but the key path or base URL is missing,
CivicCast falls back to disabled.

## Routes

- `/.well-known/webfinger` resolves `acct:<handle>@<base-url-host>`.
- `/ap/actor` returns the station actor and public key.
- `/ap/inbox` accepts signed `Follow` and `Undo Follow` activities.
- `/ap/followers` lists accepted followers.
- `/ap/outbox` lists local `Accept` and publish `Create` activities.
- `/nodeinfo/2.0` reports ActivityPub support.
- `/api/staff/activitypub/status` reports non-secret policy and counts.
- `/api/staff/activitypub/followers` lists pending, accepted, blocked,
  rejected, or removed followers.
- `/api/staff/activitypub/followers/approve` approves a pending follower and
  delivers a signed `Accept`.
- `/api/staff/activitypub/followers/reject` rejects a pending follower and
  delivers a signed `Reject`.
- `/api/staff/activitypub/followers/block` blocks a follower.
- `/api/staff/activitypub/outbox` lists local staff-visible outbox evidence.
- `/api/staff/activitypub/deliveries` lists signed delivery attempts.

## Security Controls

- Inbox requests must carry HTTP Signature, Date, Host, and Digest headers.
- CivicCast verifies the remote actor public key by fetching the signed actor
  document and matching `keyId`.
- Remote actor and inbox URLs must be public HTTPS URLs; localhost, private IP,
  link-local, reserved, multicast, and `.local` targets are rejected.
- `CIVICCAST_ACTIVITYPUB_BLOCKLIST` and
  `CIVICCAST_ACTIVITYPUB_BLOCKLIST_FILE` block domains.
- `CIVICCAST_ACTIVITYPUB_ALLOWLIST` and
  `CIVICCAST_ACTIVITYPUB_ALLOWLIST_FILE` define limited federation.
- `CIVICCAST_ACTIVITYPUB_INBOX_RATE_LIMIT` and
  `CIVICCAST_ACTIVITYPUB_INBOX_RATE_WINDOW_SECONDS` rate-limit remote domains.
- Outbound `Accept`, `Reject`, and publish `Create` deliveries are signed with
  the station key and recorded as delivery attempts.
- `CIVICCAST_ACTIVITYPUB_LAB_ALLOW_LOCAL=1` exists only for local interop
  proofs against loopback/container targets. Leave it unset for deployed
  stations; production remote actor and inbox URLs must remain public HTTPS.

## Operator Console

Open **Federation** in the operator console after enabling ActivityPub and
restarting CivicCast. The screen shows whether federation is off or enabled,
the actor URL, mode, authorized-fetch posture, allow/block counts, follower
counts, moderation tabs, outbox activities, and delivery attempts. Pending
follows can be approved, rejected, or blocked. Accepted, rejected, and removed
followers can be blocked if the station needs to stop future traffic.

## Operator Posture

For a non-technical beta, leave ActivityPub disabled unless federation is part
of that tester's scenario. For technical testers, prefer `approval-only` plus
authorized fetch for the first public run. Move to `limited` only when the
partner instances are known. Use `open` only after the station has a moderation
policy and an instance blocklist.

## Interop Proof

Run a controlled local GoToSocial proof when Docker is healthy:

```bash
python scripts/prove_activitypub_interop.py --execute
```

The proof runner starts a disposable GoToSocial container, creates a local
account through the official container CLI, signs the actor fetch through a
lab-only CivicCast actor/WebFinger origin, fetches the real GoToSocial actor
document, parses it through CivicCast's explicit lab-mode remote actor
validator, writes JSON/Markdown evidence, and removes the container. On the
RTX validation host after Docker Desktop repair, the local proof passed with
proof level `real_actor_document`.

This is an internal interop proof, not a public fediverse compatibility claim.
Before public rollout, run a redacted target-instance proof that exercises a
real signed `Follow`/`Accept` path against the partner instance.

# CivicCast Admin Guide

_Covers `v1.0.0-rc17` and later._

This guide is for the person who installs CivicCast, owns station settings,
keeps recovery material safe, and helps meeting staff when the console says a
step needs IT help.

## Your Job

You make sure the station can answer four questions:

1. Can we sign in and recover access if the first admin is unavailable?
2. Can video, captions, records, and subscriber data survive a restart?
3. Can the station show whether it is safe to broadcast tonight?
4. Can support diagnose a problem without exposing secrets or resident data?

## First Install

1. Download the Windows setup executable from the official GitHub Release. Do
   not use the repository source ZIP for installation.
2. Verify the installer using
   [Windows Release Trust And Verification](install/windows-release-trust.md).
3. Run the setup app and let it complete the host bootstrap and console handoff.
4. Create the first admin account.
5. Save or print the recovery kit during first-admin setup.
6. Open the operator console and review **System Health**.
7. Run a private rehearsal before the first public meeting.

The setup app and console hide first-admin identity, recovery-kit,
operator-token handoff, local durable storage bootstrap, upload-folder setup,
database migrations, local Ollama AI runtime and model provisioning, service
startup, and dashboard launch behind guided screens. Use
[Technical Operations Reference](technical-ops-reference.md) for exact command
and evidence details when an advanced service boundary appears.

## First Admin And Recovery Kit

The first-admin setup creates the station's first local admin identity, stores
only password/recovery/token hashes, and returns the recovery kit once. Save or
print the kit before continuing; CivicCast cannot display the recovery codes
again. If the browser token is lost later, use **Setup -> Admin sign-in** to
get a fresh token. If the password is lost, use **Setup -> Use recovery code**
to consume one printed code and set a new admin password.

The recovery kit should include:

- Station name and public base URL.
- Admin username or local account identifier.
- Recovery-code instructions.
- Where backups are stored.
- Where installer/release evidence is stored.
- How to rotate credentials if the kit is exposed.

Do not store bearer tokens, provider secrets, private keys, resident email
addresses, or database passwords in support tickets or screenshots.

## Storage And Backups

Real stations need durable storage before handling real meeting content. The
installer and console present this as **where should CivicCast store the station
record?** CivicCast prepares local durable storage and migrations by default;
technical admins can still point `DATABASE_URL` at Postgres when the station
requires an external database.

Before the first public meeting, confirm:

- The station can restart without losing assets, schedules, captions,
  subscribers, summaries, signed records, or publish evidence.
- Recordings and archive copies have enough disk space for the expected
  meeting schedule.
- Someone knows where backups live and how to test a restore.

The setup flow creates the first-admin account and recovery kit. A full
backup destination check is available in **Setup**, and **System Health** can
run a restore rehearsal that writes a proof file to the backup destination,
copies it into an isolated restore area, verifies the checksum, checks
representative admin, portal, media, captions, records, publish, provider, and
credential-metadata state, and cleans up temporary proof files. Treat that as a
tester restore proof for the backup destination and representative station
state, not as a substitute for a full disaster-recovery drill with real meeting
archives.

Use the explicit
[restore, update, rollback, and observed beta proof protocol](ops/v1.4-restore-update-beta-proof.md)
before claiming a station has passed beta operations proof.

## System Health

Use **System Health** to see whether the station is ready, needs attention, or
should not broadcast yet. The admin view may show technical detail. Meeting
operators should see plain-language results.

Common health outcomes:

- **Ready:** required checks passed with live proof attached to the report.
- **Check before meeting:** required items are configured but still need live
  proof, or optional/recoverable checks need attention.
- **Do not broadcast yet:** a required broadcast dependency is missing.
- **Needs IT help:** the next step is technical and should not be handed to a
  meeting operator.

## Provider Setup

External providers such as YouTube, Internet Archive, BunnyCDN, Cloudflare R2,
ActivityPub, podcast feeds, and subscriber delivery should be optional unless
your station has selected them for a meeting or retention policy.

**Setup** shows provider readiness and setup guidance. Each provider
card names what you need, the setup steps, the write-only credential fields,
and the proof required before the provider can be called ready. Provider
details are saved locally and secret values are never printed back to the
browser, support bundle, or API response. Configured credentials alone do not
prove a live provider; run the provider proof before telling residents that
surface is ready.

### Cloudflare R2 CDN concierge (paste-one-token setup)

A big meeting can outgrow what your station's own internet connection can
serve directly — roughly 200 viewers on a typical connection. CivicCast can
rent overflow capacity from Cloudflare's R2 storage service, free until
usage is high, but setting up a CDN by hand normally means collecting five
technical values (account ID, two keys, a bucket name, a public URL). The
concierge on the Cloudflare R2 card in **Setup** collapses that to one step:

1. Make a free Cloudflare account (skip if you already have one — a signup
   link is on the card).
2. Create one API token scoped to R2 Edit (a second link on the card opens
   the right Cloudflare screen).
3. Paste the token and click **Provision for me**.

CivicCast verifies the token, creates the storage bucket, turns on its
public web address, and derives the storage keys itself — nothing else to
copy or paste, and the token itself is never stored or shown again. If your
Cloudflare account has never used R2 before, CivicCast says so plainly and
links straight to the one-time "Enable R2" screen (Cloudflare may ask for a
payment method even though the free tier covers most stations); click
**Retry** on the card once you have enabled it. You can still enter the five
R2 fields by hand instead, if you already have them.

## AI Models

Each AI feature — captions, summary, and translation — runs a model you can
choose in the operator console under **Settings -> AI Models**. Every feature
ships on a **local** default: it runs on this machine, keeps meeting content
private, and has no per-token cost. The summary default adapts to the hardware
(the larger local model on a 16 GB-or-more box, the smaller one on a smaller
box); the console shows which one this station got and lets you change it.

Changing a model selection requires the **setup_admin** role. A
**meeting_operator** can open the AI Models console to see the current models
but cannot change them.

### Cloud & frontier models (optional, paid)

The AI Models console also offers **hosted cloud and frontier models** for
**summary and translation** as an opt-in alternative to their local defaults.
Captions has no hosted option and always runs locally on faster-whisper.
Treat a hosted selection as a deliberate cost-and-privacy decision, not a
default:

- **Default OFF.** Summary and translation stay on their private local models
  until a setup_admin explicitly selects a hosted one. Nothing is sent to the
  cloud and nothing is billed unless you opt in.
- **Content leaves the station.** Selecting a hosted model sends that feature's
  transcript text (for summary or translation) to a third-party provider
  (Ollama Cloud or OpenRouter). These models are not private and require
  network access.
- **Billed per token in $USD.** The console shows the per-token cost on each
  option. A hosted selection produces a real, recurring provider bill that
  scales with how much you broadcast.
- **Consent is required.** Before a hosted selection is saved, the operator must
  tick a checkbox accepting the provider's terms of service and the per-token
  cost. CivicCast records who accepted and when alongside the selection.
- **Who can enable it.** Only a **setup_admin** can turn a hosted model on. Make
  this an intentional station decision — confirm the budget and the privacy
  implication for your jurisdiction before enabling content egress to a paid
  provider.

### Storing a provider API key

A hosted model needs an API key from its provider (Ollama Cloud or OpenRouter).
Until a key is stored, a hosted selection **defers** — the feature keeps using
its local behavior and the AI Models card shows a "no provider credential is
stored" hint. Only a **setup_admin** can store a key, two ways:

- **In the console.** On the AI Models card, stage a hosted model; a write-only
  **Provider API key** field appears. Paste the key and choose **Save key**. The
  key is never shown back, and the defer hint clears once it is stored.
- **On the command line** (headless / air-gapped):
  `civiccast model set-provider-key ollama-cloud` (or `openrouter`). Supply the
  key via `--key` or, preferably, the `CIVICCAST_PROVIDER_API_KEY` environment
  variable so the secret stays out of shell history; pass `--clear` to remove it.

Keys live in the operating-system keyring — never written to the database or
config files, and never echoed to logs or API responses.

For the model catalog, registry slugs, and the API contract, see the
[Technical Operations Reference](technical-ops-reference.md) ("AI models:
defaults and operator selection").

## Support Reports

When asking for help, include:

- CivicCast version.
- Operating system.
- System Health state.
- The exact screen and action that failed.
- Redacted diagnostic evidence.

Use **System Health -> Support bundle** to generate the redacted evidence file.
It includes versions, health state, setup state, provider readiness, source
guidance, backup/restore/update state, and an environment summary with secrets
redacted.

Do not include secrets, private keys, resident data, private meeting content,
or raw bearer tokens.

## Technical Reference

Use [Technical Operations Reference](technical-ops-reference.md) for exact
commands, CLI JSON evidence, certificate rotation, NATS, mTLS, ActivityPub,
model bundles, cable/NDI checks, release proof, and recovery details.

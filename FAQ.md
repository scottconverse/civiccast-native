# CivicCast FAQ

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **This repository ships one product line: native Windows.** Earlier
> revisions of this notice described "two parallel Windows product lines"
> shipping from this repository -- that described the OLD
> `scottconverse/civiccast` repository. This repository (`civiccast-native`)
> was created by copying only the native product out of it with fresh
> history, and the WSL2 lane was retired outright under the owner's "no
> linux" decision (2026-08-19). See [BRANCHES.md](BRANCHES.md) for the full
> explanation and where the retired line's history now lives (private, not
> archived).

## What is CivicCast?

CivicCast is open-source broadcast software for public meetings and community
media. It helps a small organization stream or upload a meeting, publish it to
a public portal, preserve archive copies, create captions and summaries, and
notify residents when the replay is ready.

## Who is it for?

School boards, HOA boards, city councils, county boards, commissions,
nonprofits, public-access stations, and community groups that need durable
public video without per-minute vendor fees or appliance lock-in.

## How do I install it?

Do not install rc11, rc12, or rc13. The current release line is `v1.0.0-rc18`,
the published controlled beta; `v1.0.0-rc17` remains available as the rollback
target. Use `INSTALL-WINDOWS.md` and the active tester handoff to verify
the exact release, filename, SHA-256, signature status, and verification record. Do not
use `releases/latest` for a controlled beta unless that handoff explicitly says
to do so.

CivicCast's Windows product (this repository, [ADR 0021](docs/adr/0021-native-windows-runtime.md))
runs its services as a native Windows service -- no WSL, no Ubuntu, no
Linux runtime. The signed setup app is the guided entry point; it installs
the bundled Python/GStreamer/FFmpeg runtime, prepares local storage and
upload folders, registers the Windows service, and hands you to the
operator console. (Earlier revisions of this FAQ described a retired
WSL2/Ubuntu-hosted deployment; that lane's history lives in the separate,
private `scottconverse/civiccast` repository -- see
[BRANCHES.md](BRANCHES.md).)

**rc17 and later:** the setup app also sets up the local Ollama AI runtime for you
(reusing a healthy existing install, or installing a pinned version if none
is present) and ensures the same three-tag target set of standard summary
and translation models, downloading only the tags still missing, in the
background once the console is already open, rather than making you install
Ollama yourself.

## How do I verify the installer download?

Read [docs/install/windows-release-trust.md](docs/install/windows-release-trust.md).
At minimum, compare the SHA-256 hash published with the release to the hash of
the `.exe` you downloaded. A checksum proves the bytes match the release; code
signing or attestation status is called out separately in each release.

## What do I need before the first real meeting?

- A Windows 11, Linux, or macOS host that passes `civiccast doctor`.
- Local durable storage prepared by the setup app, or Postgres 17+ with
  `DATABASE_URL` configured by a technical admin.
- A first local admin account and saved recovery kit from the Setup screen.
- FFmpeg for packaging video.
- Ollama and model bundles if you want local summaries or translation.
  **(rc17 and later: the Windows setup app provisions Ollama and downloads the model
  bundles for you automatically in the background.)** Bring your own API
  key instead if you choose a paid hosted model.
- The camera, encoder, or NDI/RTMP/RTSP/SRT source you plan to use.
- Archive and notification credentials only if your station will use those
  providers during the test.

## Do I need Postgres?

Not for the default beta path. CivicCast prepares local durable SQLite storage
and applies migrations automatically when `DATABASE_URL` is not set. Technical
admins can use Postgres by setting `DATABASE_URL`. By default, your data is
always saved to durable storage; only a developer explicitly testing the
software can turn on a throwaway, non-persistent mode.

## How do I connect a camera?

The stock build cannot verify a live source because no production server-side media
probe is configured. It shows **Source preview unavailable** and keeps live
start disabled. An integrator can connect RTMP, RTSP, SRT, or NDI-style sources,
but live instructions apply only after that integrator supplies and separately
proves the media probe and station egress path.

The stock acceptance path does not use a camera: create or upload recorded
sample media, package it privately, explicitly approve Portal publication, and
confirm resident playback.

## Does CivicCast support NDI?

Yes for planning and readiness checks. CivicCast can inspect the local NDI
handoff posture and generate FFmpeg-to-NDI command plans. Some NDI components
cannot be redistributed publicly with CivicCast, so the operator may need to
install approved NDI runtime or SDK pieces on the station host.

Technical admins can use the `civiccast cable` CLI for detailed NDI evidence,
but meeting operators should start with the plain-language source setup guide
in **Run Meeting**.

## What happens if the network drops during a live meeting?

The stock build does not claim a working live broadcast. Without an integrator-
provided media probe, the live room shows **Source preview unavailable** and
keeps live start disabled. The resident portal should show a clear unavailable
state rather than a blank or simulated player.

For a meeting that must be preserved, also record locally at the camera,
encoder, or station machine. After the meeting, upload the local recording,
package it, and publish the replay even if the live stream was interrupted.

## How do captions, summaries, and translation work?

Captions can be generated locally and reviewed before publication. Summaries
are sourced: quantitative claims must be backed by transcript timestamps before
approval. Spanish translation can publish an additional WebVTT track while
keeping the original English captions available.

Test builds may use simplified stand-in captions and summaries that are not
meant for real meetings. A real beta station should use the local model
runtime or leave that lane blocked until the model bundle is installed and
hash-verified.

## Where does the public watch the meeting?

Residents use the public portal URL. In the stock acceptance path it shows
recordings only after private packaging and explicit Portal approval. A current
live broadcast requires the separately proven integrator media/egress path.
Residents do not need an operator account.

## How do subscribers work?

Residents can use email double opt-in, public RSS feeds, podcast feeds, or
webhook delivery depending on what the station enables. Email handles and
webhook secrets are encrypted at rest. Public subscribe endpoints are
rate-limited to reduce spam and abuse.

## Can CivicCast publish to YouTube or the Internet Archive?

The source tree includes those optional surfaces, but stock acceptance is
Portal-only. Internet Archive, YouTube, NAS, podcast, and notification delivery
require real station credentials plus separate redacted provider evidence. A
missing or unverified credential must show as blocked, not successful.

## Does ActivityPub work?

ActivityPub is fully operator-gated and off by default. Technical stations can
enable it with a public base URL, generated station key, moderation mode, and
operator policy controls. The recommended beta posture is approval-only mode
with authorized fetch enabled.

Do not enable public federation for a station until you have a controlled
target instance and can keep redacted evidence of follow, moderation, and
delivery behavior.

## Is the signed record legally notarized?

No, not by default. CivicCast can export PDF/A-3B signed-record artifacts with
provenance and approval metadata. A station needs its own legal review and a
real timestamp or signing authority before making jurisdiction-specific legal
record claims.

## What should I do if setup gets stuck?

Open **System Health** and choose **Create support bundle**. Include the
generated bundle path or attach the bundle if your support channel allows it.
Also include the exact screen and button where you stopped. Do not paste
tokens, passwords, private keys, resident data, or private meeting content.

## Where are the technical details?

- [User Manual](docs/USER-MANUAL.md)
- [Admin Guide](docs/admin-guide.md)
- [Meeting Operator Guide](docs/meeting-operator-guide.md)
- [Records Clerk Guide](docs/records-clerk-guide.md)
- [Technical Operations Reference](docs/technical-ops-reference.md)
- [Operator Language Guide](docs/operator-language-guide.md)
- [Architecture overview](ARCHITECTURE.md)
- [API guide and reference](docs/API-REFERENCE.md)
- [ActivityPub ops](docs/ops/activitypub-federation.md)
- [NDI output ops](docs/ops/ndi-output.md)
- [v1.0.0-rc18 candidate verification](docs/releases/v1.0.0-rc18-verification.md) (current)
- [v1.0.0-rc17 candidate verification](docs/releases/v1.0.0-rc17-verification.md) (rollback target)
- [v1.0.0-rc15 candidate verification](docs/releases/v1.0.0-rc15-verification.md) (superseded, historical)
- [v1.0.0-rc13 incident record](docs/releases/v1.0.0-rc13-verification.md)
- [v0.2.0 verification](docs/releases/v0.2.0-verification.md)
- [v0.1.0-rc6 verification](docs/releases/v0.1.0-rc6-verification.md) (historical clean-Windows evidence, not approval for the current line)
- [LPM beta handoff](docs/tester/lpm-beta-test-handoff.md) for the controlled
  Longmont Public Media tester artifact and station-side proof steps.

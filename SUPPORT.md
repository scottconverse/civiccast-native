# Support

> **Current native release posture:** `v1.0.0-beta.11` is the current
> release, published 2026-10-08 as a GitHub pre-release (a beta candidate) --
> `setup.exe` and the runtime
> `.ccpack` packs are attached to its
> [GitHub Release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.11).
> `v1.0.0-beta.10`, `v1.0.0-beta.7`, `v1.0.0-beta.4` and `v1.0.0-beta.3` (the first downloadable
> release) are now superseded.
> `v1.0.0-beta.1` (USB-delivered, no downloadable assets) is also
> superseded. `v1.0.0-beta.2` was never published -- it exists only as an
> internal Gate A upgrade-baseline kit. `v1.0.0-beta.8`
> and `v1.0.0-beta.9` were never published; their work is inside beta.10.
> Community support does not turn this beta into a
> supported, SLA'd field release.

> **This repository ships one product line: native Windows.** Earlier
> revisions of this notice described "two parallel Windows product lines"
> shipping from this repository -- that described the OLD
> `scottconverse/civiccast` repository. This repository (`civiccast-native`)
> was created by copying only the native product out of it with fresh
> history, and the WSL2 lane was retired outright under the owner's "no
> linux" decision (2026-08-19). See [BRANCHES.md](BRANCHES.md) for the full
> explanation and where the retired line's history now lives (private, not
> archived).

CivicCast is an open-source public-good project. Support is community-driven;
there is no commercial support contract or SLA.

## How To Get Help

1. **Read the early-adopter docs first.** Start with
   [docs/adoption/early-adopter-quickstart.md](docs/adoption/early-adopter-quickstart.md),
   [docs/adoption/support-intake.md](docs/adoption/support-intake.md),
   [FAQ.md](FAQ.md), [docs/USER-MANUAL.md](docs/USER-MANUAL.md), and
   [docs/tester/START-HERE.md](docs/tester/START-HERE.md).
2. **Search existing issues.** [GitHub Issues](https://github.com/scottconverse/civiccast-native/issues)
   may already cover your question.
3. **Open a question or bug issue.** Use **Report a beta issue** in the
   installer, operator console, or resident portal, or open the repository's
   bug-report template directly. Include the CivicCast version, operating
   system, the screen where the issue happened, the exact operator
   message, and the steps already tried. Never
   include passwords, recovery codes, staff tokens, or private meeting
   material in a public report.
4. **Use [GitHub Issues](https://github.com/scottconverse/civiccast-native/issues) for
   open-ended planning too** (GitHub Discussions is not enabled on this
   repository). Examples: whether CivicCast is a fit for an HOA,
   public-access station, school board, or nonprofit workflow.

## Retired WSL2 Support History

The following paragraph records the old WSL2 product line only. It is not
installation or support guidance for the native product in this repository.

`v1.0.0-rc13` was withdrawn after a genuine clean-host bootstrap failure;
`v1.0.0-rc18` was the most recently published release on that retired line.
The full clean-host product walkthrough was last completed against rc17's
exact bytes on 2026-07-20 and passed -- install with no restarts, first admin
and recovery kit, backup and scoped database restore, private rehearsal and
packaging, the publish privacy gate, resident playback, and unaided
cold-reboot recovery. Captions were not exercised in that pass. (The
verification record for that run is not present in this repository -- it
belongs to the separate, private `scottconverse/civiccast` repository.)
Preserve the installer log and support bundle for every failure.

Supported early-adopter paths are documented self-hosted deployment profiles,
with Windows running CivicCast as a native Windows service (no WSL, no
Ubuntu). Operator or beta-test installs require durable storage. The native
installer provisions the bundled local PostgreSQL service and saves its
connection URL for the supervisor; a `DATABASE_URL` service-environment value
overrides that URL. The Setup screen prepares the database schema before the
first admin and recovery kit are created. Standalone app use can prepare a
local SQLite database when no database URL is configured; this is not the
native Windows service default. In-memory stores are for tests and explicitly
enabled throwaway development.

## Native Windows Beta

The native Windows runtime ([ADR 0021](docs/adr/0021-native-windows-runtime.md))
is a **public beta**, not a finished production release. Its current
release, `v1.0.0-beta.11`, is downloadable (setup.exe and the runtime packs
on its [GitHub Release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.11)),
published 2026-10-08 as a GitHub pre-release (a beta candidate), not a
production release. There is still no dedicated, SLA'd support intake for it --
the same community-driven, no-SLA posture above applies. Its tested scope and
known limits are in the [Beta 11 verification record](docs/releases/v1.0.0-beta.11-verification.md).
earlier `v1.0.0-beta.7` is superseded.

If you are working on, evaluating, or running the native line:

- Read [ADR 0021](docs/adr/0021-native-windows-runtime.md) and
  [BRANCHES.md](BRANCHES.md) first.
- Use a regular [GitHub Issue](https://github.com/scottconverse/civiccast-native/issues)
  for questions (GitHub Discussions is not enabled on this repository), and say explicitly in the report
  that it concerns the native line and which release tag or source commit you're on -- the templates don't yet
  have a native-specific path, so context has to be spelled out by hand.
- Do not treat anything reported against the native line as a supported,
  SLA'd, or fully field-proven path. The same "community-driven, no SLA"
  posture above applies. The Beta 11 verification record
  ([`docs/releases/v1.0.0-beta.11-verification.md`](docs/releases/v1.0.0-beta.11-verification.md))
  states what was and was not proven. The superseded Beta 10 and Beta 7
  verification records are
  [`docs/releases/v1.0.0-beta.10-verification.md`](docs/releases/v1.0.0-beta.10-verification.md)
  and
  [`docs/releases/v1.0.0-beta.7-verification.md`](docs/releases/v1.0.0-beta.7-verification.md);
  these are engineering records, not a support commitment.

This section will be replaced with a real support surface once the native
line has its own proof boundary document beyond those verification records.

## What Is Not Supported

- Untagged branch snapshots as production releases.
- Public ActivityPub exposure without the documented base URL, station key,
  policy mode, operator moderation, and redacted target-instance proof.
- Provider readiness claims without configured credentials and controlled
  evidence.
- SDI, DeckLink, Comcast/headend, streaming-TV app-store, DRM, or hardware
  claims without separate partner proof.
- Legal, accessibility, retention, or procurement certification.
- Custom integrations, white-labels, or vendor-specific deployments outside the
  documented module catalog.

## Security

For security vulnerabilities, see [SECURITY.md](SECURITY.md). Do not file public
issues for security reports.

## Bugs And Feature Requests

Use the bug-report and feature-request issue templates at
[.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE/). Follow
[docs/adoption/support-intake.md](docs/adoption/support-intake.md) when deciding
which logs or support-bundle details are safe to share publicly.

# Support

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Release state:** `v1.0.0-rc18` is the current release line and the published
> controlled beta; `v1.0.0-rc17` remains the rollback target. The proof boundary
> is recorded in
> [docs/releases/v1.0.0-rc18-verification.md](docs/releases/v1.0.0-rc18-verification.md).

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
   [docs/installer/beta-tester-handoff.md](docs/installer/beta-tester-handoff.md).
2. **Search existing issues.** [GitHub Issues](https://github.com/scottconverse/civiccast-native/issues)
   may already cover your question.
3. **Open a question or bug issue.** Use **Report a beta issue** in the
   installer, operator console, or resident portal, or open the repository's
   bug-report template directly. Include the CivicCast version, operating
   system, the screen where the issue happened, the exact operator
   message, and the steps already tried. Never
   include passwords, recovery codes, staff tokens, or private meeting
   material in a public report.
4. **Use [Discussions](https://github.com/scottconverse/civiccast/discussions) for
   open-ended planning.** Examples: whether CivicCast is a fit for an HOA,
   public-access station, school board, or nonprofit workflow.

## What Is Supported For Early Adoption

`v1.0.0-rc13` is withdrawn after a genuine clean-host bootstrap failure.
Existing rc13 failure reports remain useful; do not begin a new rc13 or
older-candidate installation. The most recently published release is
`v1.0.0-rc18`. The full clean-host product walkthrough was last completed against
**rc17's** exact bytes on
2026-07-20 and passed — install with no restarts, first admin and recovery kit,
backup and scoped database restore, private rehearsal and packaging, the publish
privacy gate, resident playback, and unaided cold-reboot recovery. Captions were
not exercised in that pass; see the
[rc17 verification record](docs/releases/v1.0.0-rc17-verification.md).
Preserve the installer log and support bundle for every failure.

Supported early-adopter paths are documented self-hosted deployment profiles,
with Windows running CivicCast as a native Windows service (no WSL, no
Ubuntu). Operator or beta-test installs require durable storage. The
installer and API prepare local durable
storage and migrations by default, then the Setup screen creates the first local
admin and browser token. Technical admins can configure Postgres with
`DATABASE_URL` instead. In-memory stores are for tests and throwaway
development.

## Native Windows Beta

The native Windows runtime ([ADR 0021](docs/adr/0021-native-windows-runtime.md),
developed on `release/native-beta-1.0.0-beta.1-rc1`) is **not a public beta**.
Its development candidate, `v1.0.0-beta.1`, is an owner-held build, not a
published GitHub release, so there is no public installer to support yet and
no dedicated support intake for it.

If you are working on or evaluating the native line as a contributor:

- Read [ADR 0021](docs/adr/0021-native-windows-runtime.md) and
  [BRANCHES.md](BRANCHES.md) first.
- Use [GitHub Discussions](https://github.com/scottconverse/civiccast/discussions)
  or a regular GitHub Issue for questions, and say explicitly in the report
  that it concerns the native line and which commit on
  `release/native-beta-1.0.0-beta.1-rc1` you're on — the templates don't yet
  have a native-specific path, so context has to be spelled out by hand.
- Do not treat anything reported against the native line as a supported,
  SLA'd, or field-proven path. The same "community-driven, no SLA" posture
  above applies, and the native line additionally has no public release or
  proof boundary document yet. A clean-machine verification record exists at
  `.agent-runs/native-windows/k1-clean-box-proof/evidence/` (clean-box
  install → activation → clerk loop → captions → product-engine egress,
  2026-08-19); it is an engineering proof, not a support commitment.

This section will be replaced with a real support surface once the native
line has a published release and its own proof boundary document.

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

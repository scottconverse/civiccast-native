# CivicCast Release Policy

> **Release state:** `v1.0.0-beta.12` is the current GitHub pre-release,
> published October 10, 2026; its station-download distribution repair was
> added October 11. The release assets include the signed installer, five
> runtime packs, four manual assets, checksums, sidecar, release-matched
> downloader, station bundle manifest and multipart station archive. The
> downloader stages the complete kit and runs setup with `/S`. The October 11
> R9 attempt failed with exit 123 against the earlier incomplete asset set; it
> is not an install result for the repaired distribution. No completed
> installation or sustained-operation result for the repaired asset set is
> recorded. The recorded upgrade preserved its initial-data marker but the
> recorder snapshot failed. See the [Beta 12 verification
> record](../releases/v1.0.0-beta.12-verification.md) and [GitHub
> release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.12).
> `release-truth.yaml` is the authored release-state record. Earlier published
> beta releases are superseded; Beta 8 and 9 were never published. Beta 2 was
> never published and exists only as an internal upgrade-baseline kit. See
> [`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for the
> authored release-state record and current version.

Status: current beta adoption guidance

## Release Channels

- **Source/runtime release:** code, docs, tests, generated API artifacts, and
  release identity are aligned and tagged.
- **Packaged Windows release:** a Windows setup executable is attached to a
  GitHub Release and has exact-asset checksum and smoke proof.
- **Partner hardware proof:** a station or lab validates hardware or headend
  behavior and records redacted evidence.

Do not use evidence from one channel to claim another channel passed.

## Required Before A Source/Runtime Tag

- Release plan updated.
- Changelog updated.
- Runtime version updated.
- Generated OpenAPI and TypeScript artifacts updated.
- Release verification page added.
- Targeted tests pass.
- Policy suite passes.
- audit-lite passes for each meaningful slice.
- audit-full passes before merge/tag.

## Required Before A Packaged Windows Claim

- GitHub Release contains the exact Windows setup executable.
- SHA-256 checksum is published.
- The exact downloaded asset is smoke-tested, not a local build artifact.
- Authenticode signing status is stated. The Windows installer is signed (Azure Trusted
  Signing; verified publisher Scott Converse); release notes explain that SmartScreen may
  still warn until the certificate earns reputation, and how to verify.
- Installer proof records Windows version, CivicCast version, setup outcome,
  first-admin handoff, and System Health result.

The draft-first sequence is mandatory:

1. Verify the complete owner-held asset set without publishing it:
   `python scripts/policy/check_published_release_assets.py <tag> --candidate`.
2. Obtain the owner's explicit publication approval.
3. Publish the release, then immediately verify its live publication state and
   asset set with
   `python scripts/policy/check_published_release_assets.py <tag> --require-published`.
4. Run the live visitor audit before announcing the release.

## Required Before A Hardware Or Platform Claim

- The exact hardware, platform, or distribution target is named.
- Proof is run on the named target.
- Evidence records what passed, what failed, and what was outside scope.
- Claims are limited to the proven configuration.

Examples: SDI, DeckLink, Comcast/headend delivery, Roku Channel Store
publication, Fire TV, Apple TV, Android TV, DRM readiness, and hosted-service
operation all require separate proof.

## Security Release Handling

Security reports follow `SECURITY.md`. Public issues should not be used for
vulnerability reports. A security fix release should describe impact, affected
versions, fixed versions, and operator action without exposing exploit details
before coordinated disclosure.

## Overclaim Rules

- Do not call a provider, platform, hardware path, or release artifact proven
  until the exact path has evidence.
- Do not hide unfinished work by changing docs.
- Do not replace failed proof with softer marketing language.
- Do not claim legal, procurement, accessibility, public-records, or retention
  certification.

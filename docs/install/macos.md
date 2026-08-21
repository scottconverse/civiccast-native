# macOS Installation Posture

Date: 2026-05-22
Last reviewed: 2026-07-23 against rc18 — status confirmed.

Status: no supported public macOS package in the current beta.

## Support Level

CivicCast can be evaluated from source on macOS by technical users, but the
project does not currently publish a supported `.pkg` installer for operators.
Do not describe macOS as a supported self-install path until package build,
signing/notarization posture, install, first launch, upgrade, and uninstall
evidence are recorded.

Future macOS package work should target Apple Silicon first. Intel macOS
packaging is not a current beta target.

## Signing Posture

No current CivicCast macOS package should be treated as signed or notarized
unless the specific GitHub Release says so and provides verification evidence.
Gatekeeper warnings are expected for unsigned local builds; they are not proof
that a package is safe.

## Approved Installation Sources

Technical testers should use only:

- the official repository at `https://github.com/scottconverse/civiccast`; or
- artifacts attached to the official GitHub Release, when a release explicitly
  includes macOS evidence.

Do not install CivicCast from third-party mirrors, repackaged binaries,
unsolicited downloads, files sent through chat or email, or packages whose name
does not match the official release.

## Evidence Required Before Supported macOS Claims

Before a macOS package is called supported, record:

- Apple Silicon model and macOS version;
- package artifact name, size, and SHA-256 digest;
- package signing and notarization result, or an explicit unsigned posture;
- install command or Finder flow;
- first launch result;
- `civiccast doctor` output;
- first-run setup wizard result;
- upgrade and uninstall behavior;
- Gatekeeper warning text and approved operator guidance;
- screenshots or terminal logs with secrets redacted.

CI or durable manual evidence must also show package artifact build, sidecar
generation, sidecar verification, release upload, and the explicit
Apple Silicon package result.

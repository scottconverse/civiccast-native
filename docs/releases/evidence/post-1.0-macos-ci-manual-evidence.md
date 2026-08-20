# Post-1.0 macOS CI + Manual Evidence

Date: 2026-05-15

Status: Apple Silicon macOS package support is deferred until after `v1.0.0`.
This evidence log records the current CI state and the manual evidence required
before macOS package support can move beyond beta.

## Current CI Evidence

- `v1.0.0` release artifact run: `25927680770`.
- Result: green for Linux, Python, docs, portable artifacts, package artifacts,
  release upload, and Sigstore sidecars.
- macOS package input: `include_macos_pkg=false`.
- macOS package result: intentionally skipped for final `v1.0.0` because macOS
  package support is beta.

Earlier tag-triggered artifact run `25927524614` attempted the macOS package
job and failed before runner steps started. That failure is not a `v1.0.0`
release blocker because Scott scoped macOS package support to post-1.0.

## Manual Evidence Still Required

Before CivicCast claims supported macOS package installation, record:

- Apple Silicon model;
- macOS version;
- package artifact name, size, and SHA-256 digest;
- install flow;
- first launch result;
- `civiccast doctor` output;
- first-run plan output;
- uninstall or upgrade behavior;
- Gatekeeper warning copy;
- operator-facing safe-install guidance;
- screenshots or terminal logs with secrets redacted.

## Current Decision

The likely target is a v1.1 unsigned Apple Silicon `.pkg`, only if demand
warrants it. Operators should install only from the official GitHub Release or
from source they build themselves.

# CivicCast Cable File Package Ops

CivicCast v1.2 adds a local cable file-package output for PEG stations and
cable headends that accept file handoff instead of live SDI delivery. This is
the first cable add-on rung. It is not NDI, SDI, DeckLink, or live headend
proof.

## What The Package Contains

`civiccast cable package` creates:

- `media/<source filename>` copied from the local recording file;
- `captions/<sidecar filename>` copied from a WebVTT or SRT caption sidecar;
- `manifest.json` with asset id, title, portal URL, loudness proof posture,
  and explicit not-claimed rows;
- `SHA256SUMS` for package contents;
- `<asset-id>-cable-package.zip` with a package-level SHA-256 proof.

The builder fails if either the source media or caption sidecar is missing.
It does not synthesize placeholder media or placeholder captions.

## CLI

```bash
civiccast cable package \
  --asset-id council-2026-05-08 \
  --title "Council - May 8, 2026" \
  --media /recordings/council-2026-05-08.mp4 \
  --captions /captions/council-2026-05-08.vtt \
  --output-dir /exports/cable \
  --portal-url https://portal.example/watch/council-2026-05-08
```

Use `--json` for automation.

## Publish Surface

The publish dashboard includes an optional `Cable file package` surface. It
succeeds only when these are configured:

- `CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR`: where ZIP packages are written.
- `CIVICCAST_CABLE_CAPTIONS_DIR`: folder containing `<asset-id>.vtt` or
  `<asset-id>.srt`.
- the asset has a local `file_path`.

If any input is missing, the surface fails with a next step and does not block
portal, archive, or subscriber surfaces.

## Proof Boundary

Implemented in this slice:

- local file-package generation;
- package and content SHA-256 proof;
- optional publish surface integration.

Separate v1.2 cable surfaces:

- NDI output planning/readiness is covered in
  [NDI Output Ops](ndi-output.md). It is a command-plan and runtime-readiness
  surface, not live receiver proof.

Deferred:

- live NDI receiver proof;
- SDI / DeckLink output;
- live headend delivery proof;
- FCC Part 79 field certification;
- real station cable proof.

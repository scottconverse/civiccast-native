# portal-public

CivicCast public portal: resident-facing live broadcast status, upcoming
premieres, published recordings, and adaptive HLS playback for civic meetings.

## Stack

- React 19 + TypeScript + Vite 8
- Tailwind CSS v4 via `@tailwindcss/vite`
- [hls.js](https://github.com/video-dev/hls.js) for adaptive HLS playback in
  browsers without native HLS. Safari and iOS use the `<video>` element's
  native HLS support directly.

## Prerequisites

- Node 20 or newer.
- npm 10 or newer.
- For the a11y test gate: a Chromium browser is downloaded by Playwright on
  first run. Run `npx playwright install chromium` once.

## Run locally

```bash
npm install
npm run dev
npm run build
npm run test:a11y
```

## Public API Contracts

The portal reads three unauthenticated public endpoints:

- `GET /api/public/live/current` for the current on-air session.
- `GET /api/public/schedule/coming-up` for scheduled public premieres.
- `GET /api/public/assets` for packaged recordings with public HLS manifests.

Each section loads independently. If one endpoint fails, the portal keeps the
other sections visible and shows an actionable partial-state message.

## Loading A Manifest

The page accepts a manifest URL via the `manifest` query parameter:

```text
http://localhost:5173/?manifest=https://your-cdn/path/playlist.m3u8
```

If a manifest parameter is present, it takes precedence over the live-status
manifest. If no live manifest and no query manifest are available, the video
area shows the offline state instead of loading a third-party demo stream.

## v0.4 Resident Portal Scope

What is in this rung:

- HLS.js attachment, manifest parsing, and native-HLS fallback path.
- Caption controls for WebVTT subtitle tracks advertised by HLS
  `EXT-X-MEDIA TYPE=SUBTITLES`.
- Loading, success-with-data, success-empty, error, and partial portal states.
- Current live-session display.
- Coming Up widget for scheduled public premieres.
- Published recordings directory.
- Dark theme, accessible labels, and keyboard-reachable controls.
- Production build verified clean with TypeScript and Vite.

What is not in this rung:

- Server-side rendering or SEO metadata from asset metadata.
- Per-channel portal routes beyond the current query-filterable API shape.
- Packager-authored live manifest truth; Slice 4 owns packager precision and
  manifest path hardening.

## v0.5 Caption Control Evidence

- Desktop screenshot: `../../../docs/releases/evidence/v0.5-public-caption-controls-desktop.png`
- Mobile screenshot: `../../../docs/releases/evidence/v0.5-public-caption-controls-mobile.png`
- Browser gate: `npm run test:a11y -- --reporter=line` covers loading,
  success, empty, partial, caption-toggle keyboard behavior, and
  serious/critical axe scans.

# CivicCast brand kit

Mark: **Civic Mast** — a town-hall pediment transmitting from its peak.
Tagline: **Public meetings, on the air.**

Suggested location in the repo: `docs/brand/`. All SVGs are self-contained (wordmark text is outlined to paths; no font needed to render).

## Files

| File | Use |
| --- | --- |
| `svg/civiccast-lockup.svg` | Primary logo. README header, docs, manual cover, light backgrounds |
| `svg/civiccast-lockup-reversed.svg` | Primary logo on dark backgrounds (Night Session or darker) |
| `svg/civiccast-lockup-tagline.svg` / `-reversed.svg` | Covers, title pages, release notes header, installer splash |
| `svg/civiccast-lockup-mono-black.svg` / `-mono-white.svg` | One-color print, fax, embossing, over photos |
| `svg/civiccast-mark.svg` / `-reversed.svg` | Mark alone, 32 px and up |
| `svg/civiccast-mark-small.svg` | Simplified mark (one heavier arc) for 16–31 px |
| `svg/civiccast-mark-mono-black.svg` / `-mono-white.svg` | One-color mark; white version for the on-air station bug |
| `svg/civiccast-app-icon.svg` | Square icon on Night Session (installer, OTT apps, PWA) |
| `svg/civiccast-social-preview.svg` | GitHub social preview source |
| `favicon.svg` | Browser favicon; switches to light colors in dark mode |
| `favicon.ico` | 16/32/48 legacy favicon, Windows shortcuts |
| `png/` | Raster exports: mark 64–512, app icon 180/192/512/1024, favicons 16/32/48, lockups at 8×, social preview 1280×640 |
| `tokens/civiccast-colors.css` | CSS custom properties |
| `tokens/civiccast-tokens.json` | Same values for scripts / build tooling |

## README header

```html
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/svg/civiccast-lockup-tagline-reversed.svg">
    <img alt="CivicCast — Public meetings, on the air." src="docs/brand/svg/civiccast-lockup-tagline.svg" width="420">
  </picture>
</p>
```

## Favicon (portal, console, docs site)

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="/civiccast-app-icon-180.png">
```

Replaces the default Vite favicon at `civiccast/apps/portal-public/public/favicon.svg`.

## Platform icons

- Installer (Tauri): generate from `png/civiccast-app-icon-1024.png` with `npx tauri icon`.
- Roku / Tizen / webOS: scale from `png/civiccast-app-icon-1024.png` to each store's required sizes.
- On-air station bug: `svg/civiccast-mark-mono-white.svg` at 60–80% opacity.

## Colors

| Name | Hex | Use |
| --- | --- | --- |
| Chamber Ink | `#1D1F20` | Mark, body type |
| Agenda Paper | `#F2F2F3` | Default background |
| Signal Steel | `#5980A6` | Broadcast arcs, icons, large accents (3:1 on paper — not for body text) |
| Record Steel | `#416180` | "CAST" in the wordmark, links, accent text |
| Night Session | `#1D2D3D` | Dark / reversed field |
| On-Air Light | `#94BCE3` | Arcs and "CAST" on dark |
| Slate | `#424244` | Tagline and secondary text on light |
| Mist | `#D6EBFF` | Tagline and secondary text on dark |

Proportion: mostly paper and ink; steel is the signal, used sparingly.

## Type

- Display / headings: **Barlow Condensed** SemiBold 600, uppercase for the wordmark, tracking +2%.
- Tagline: Barlow Condensed Regular 400, uppercase, tracking +8%.
- Body: **Barlow** 400/500/700.
- Both are free on Google Fonts under the SIL Open Font License.

## Rules

- **Clear space:** keep empty space around the logo at least the height of the pediment (the roof triangle) on every side.
- **Minimum size:** lockup 120 px wide on screen / 30 mm in print. Mark 32 px; below that, use `civiccast-mark-small.svg`.
- Wordmark is one word: **CivicCast** in running text, **CIVICCAST** only inside the logo.
- Don't recolor outside the palette, stretch, rotate, add shadows/gradients, outline, or rearrange the mark and wordmark.
- Don't place the full-color logo on mid-tone backgrounds or busy photos; use the mono white or mono black version.
- The broadcast arcs are always the accent color in the full-color logo; the building is always ink (or paper when reversed).

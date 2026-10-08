// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Kept out of ManualScreen.tsx (react-refresh/only-export-components: a
// screen file may only export components) so every setup guide and
// provider card across the console can share the exact same "/help#<id>"
// shape ManualScreen.tsx itself uses to scroll to a section.

const MANUAL_SECTION_ALIASES: Record<string, string> = {
  glossary: 'app-glossary',
  'publish-surfaces': 'the-publishing-steps-surfaces',
  'where-recordings-live': 'configuration-storage',
  'provider-internet-archive': 'publishing-providers',
  'provider-youtube': 'publishing-providers',
  'provider-subscriber-notifications': 'publishing-providers',
  'provider-local-archive-folder': 'publishing-providers',
  'provider-podcast-feed': 'publishing-providers',
  'provider-cloudflare-r2': 'cdn-and-provider-options',
  'provider-alternative-cdns': 'cdn-and-provider-options',
  'provider-federation': 'federation-activitypub',
  'cdn-cost-estimate': 'cdn-and-provider-options',
  'report-without-github': 'report-a-beta-issue',
  'your-first-beta-workflow': 'ch-before-meeting',
  'live-captions-switch': 'live-captions-what-the-settings-change',
}

/** Build a link into the in-product manual, normalizing legacy section ids to
 * current heading anchors in docs/USER-MANUAL.md. */
export function manualLink(sectionId: string): string {
  return `/help#${MANUAL_SECTION_ALIASES[sectionId] ?? sectionId}`
}

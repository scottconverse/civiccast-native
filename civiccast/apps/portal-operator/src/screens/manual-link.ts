// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Kept out of ManualScreen.tsx (react-refresh/only-export-components: a
// screen file may only export components) so every setup guide and
// provider card across the console can share the exact same "/help#<id>"
// shape ManualScreen.tsx itself uses to scroll to a section.

/** Build a link into the in-product manual, e.g. `manualLink('glossary')`
 * -> `/help#glossary`. The id must match a heading anchor in
 * docs/USER-MANUAL.md (civiccast/docsite/manual.json's table of contents). */
export function manualLink(sectionId: string): string {
  return `/help#${sectionId}`
}

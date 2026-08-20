// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// vitest's `include` glob ("src/**/*.test.ts") runs from this package's own
// root (civiccast/apps/installer), so process.cwd() there is stable --
// import.meta.url is not a plain file:// URL under vitest's transform here.
const STYLES_PATH = join(process.cwd(), "src", "styles.css");

function readStyles(): string {
  return readFileSync(STYLES_PATH, "utf-8");
}

function ruleBody(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) {
    throw new Error(`selector not found in styles.css: ${selector}`);
  }
  const end = css.indexOf("}", start);
  return css.slice(start, end + 1);
}

describe("plan-row grid layout (F-20: 'Not included' badge collision)", () => {
  it("does not fix the first grid column to a width narrower than the status pill it must hold", () => {
    // .plan-row-check (the first grid column) holds either a 20x20
    // checkbox or the "Not included" / "Included" text pill
    // (AcquisitionFlow.tsx's PlanRow). A CSS Grid item that is wider than
    // its track is NOT clipped -- it overflows visually into the next
    // column -- so a hard 40px first column let the pill collide with the
    // row's own heading. A fixed pixel-only first column (e.g. "40px 1fr
    // auto") is exactly the regression this guards against; the column
    // must be allowed to grow to fit its content.
    const rule = ruleBody(readStyles(), ".plan-row");
    const match = rule.match(/grid-template-columns:\s*([^;]+);/);
    expect(match, `.plan-row rule: ${rule}`).not.toBeNull();
    const firstTrack = match![1].trim().split(/\s+/)[0];
    expect(firstTrack).not.toMatch(/^\d+(\.\d+)?(px|em|rem)$/);
  });

  it("still gives the checkbox/pill column a sane minimum so it does not collapse to zero width", () => {
    const rule = ruleBody(readStyles(), ".plan-row");
    const match = rule.match(/grid-template-columns:\s*([^;]+);/);
    const firstTrack = match![1].trim().split(/\s+/)[0];
    // Accepts the chosen fix (minmax(40px, auto)) or any equivalent
    // auto-sizing track with a floor -- not pinned to the exact string, so
    // a reasonable alternative fix does not spuriously fail this test.
    expect(firstTrack === "auto" || /^minmax\(/.test(firstTrack)).toBe(true);
  });
});

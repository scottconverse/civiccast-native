// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-23: the repo ships LICENSE, LICENSE-CODE, LICENSE-DOCS, and
// LEGAL-NOTICES.md, but the installer surfaced none of it. App.tsx's own
// header/effects/state make a full React-render test disproportionate for
// what is fundamentally a copy addition (no @testing-library/react in this
// project either -- see AcquisitionFlow.test.ts's own comment on that), so
// this pins the footer at the source level: present, in the wizard shell
// every install path reaches, naming both licenses and linking to the
// full published text.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function readAppSource(): string {
  return readFileSync(join(process.cwd(), "src", "App.tsx"), "utf-8");
}

describe("license/attribution footer (F-23)", () => {
  it("renders a license-footer element inside the main wizard shell", () => {
    const source = readAppSource();
    expect(source).toMatch(/<footer className="license-footer">/);
  });

  it("names both licenses CivicCast actually ships (Apache-2.0 code, CC BY 4.0 docs)", () => {
    const source = readAppSource();
    expect(source).toContain("Apache License 2.0");
    expect(source).toContain("CC BY 4.0");
  });

  it("links to the published full legal notices, not a dead or invented path", () => {
    const source = readAppSource();
    expect(source).toContain("https://github.com/scottconverse/civiccast/blob/main/LEGAL-NOTICES.md");
  });
});

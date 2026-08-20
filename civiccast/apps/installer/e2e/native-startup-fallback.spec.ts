// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { expect, test } from "@playwright/test";

/**
 * The first-run window a native operator can actually land in: the app is up,
 * the supervisor's control-plane child has not bound its port yet, and there
 * is no saved progress file. loadInstallerState falls back to
 * installerFixtures.blocked.
 *
 * N-07 corrected that fallback's `platform` field. Its LANE still carried the
 * WSL2 remedy -- "Windows helper missing ... Choose Set up Windows helper ...
 * ask IT to enable CPU virtualization, Windows Virtual Machine Platform, and
 * Windows Subsystem for Linux" -- which named a remedy this product does not
 * have and, once that button stopped rendering on native, left an instruction
 * pointing at nothing.
 *
 * This drives the real UI rather than asserting on the state object, because
 * the defect was only visible on screen: the state looked plausible; what was
 * wrong was the words next to a missing button.
 */
test("native first-run with the control plane still starting says so, and promises no button", async ({
  page
}) => {
  await page.addInitScript(() => {
    // A native Tauri bridge whose local-state read fails: a freshly launched
    // station before its first status write.
    (window as unknown as { __TAURI__: unknown }).__TAURI__ = {
      core: {
        invoke: async () => {
          throw new Error("no local installer state file yet");
        }
      }
    };
    // ...and a control plane that is not listening yet. Only the installer's
    // own API is failed -- blanket-failing window.fetch also breaks Vite's
    // module loading, so the app never mounts and the test proves nothing.
    const realFetch = window.fetch.bind(window);
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/")) {
        throw new Error("ECONNREFUSED: local control plane not listening yet");
      }
      return realFetch(input as RequestInfo, init);
    }) as typeof window.fetch;
  });

  // downloadExperience=0 skips the acquisition screen ("Checking This
  // Computer") and lands on the lane wizard, which is where the fallback
  // copy appears. Same switch the rest of this suite uses.
  await page.goto("/?downloadExperience=0");
  await expect(page.getByRole("heading", { name: "CivicCast Installer" })).toBeVisible();

  const body = await page.locator("body").innerText();

  // The screen must not name a remedy this product does not have.
  expect(body).not.toMatch(/Set up Windows helper/i);
  expect(body).not.toMatch(/Windows Subsystem for Linux/i);
  expect(body).not.toMatch(/WSL/i);

  // It must say what is actually happening...
  await expect(page.getByText(/Starting CivicCast/i).first()).toBeVisible();
  await expect(page.getByText(/updates by itself/i).first()).toBeVisible();

  // ...and offer nothing to press, because there is nothing to do but wait.
  // A promised-but-absent action is the dead end this test exists to prevent.
  await expect(page.locator(".detail-primary-action")).toHaveCount(0);
});

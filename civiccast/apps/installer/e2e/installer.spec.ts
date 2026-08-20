// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { expect, test } from "@playwright/test";

const states = [
  "loading",
  "success",
  "empty",
  "error",
  "partial",
  "blocked",
  "progress",
  "skipped_model",
  "offline_bundle",
  "credential_gated",
  "beta_handoff",
  "activitypub_setup"
];
const retryActions = new Map([
  ["error", "Retry"],
  ["skipped_model", "Set up models"]
]);

for (const state of states) {
  test(`installer ${state} state is actionable`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        errors.push(message.text());
      }
    });
    await page.goto(`/?state=${state}`);
    await expect(page.getByRole("heading", { name: "CivicCast Installer" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Installer wizard" })).toBeVisible();
    await expect(page.getByLabel("Installer wizard steps")).toBeVisible();
    await expect(page.getByText(/Next:|Run |Choose |Rebuild |Import |Set /i).first()).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toBeVisible();
    const retryAction = retryActions.get(state);
    if (retryAction) {
      await page.getByRole("button", { name: retryAction, exact: true }).click();
      await expect(page.getByRole("status")).toContainText(/Retrying/);
    } else {
      await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("installer shows one primary action and only state-appropriate recovery actions", async ({ page }) => {
  const expectedPrimaryByState = new Map<string, string | null>([
    ["loading", null],
    ["success", "Open operator console"],
    ["empty", "Continue"],
    ["error", "Retry"],
    ["partial", "Continue"],
    // The blocked fixture is now the native "Starting CivicCast" state: the
    // station is coming up, there is nothing for the operator to press, and
    // a loading lane promises no action. It used to expect "Set up Windows
    // helper" -- a WSL2 remedy this product does not have.
    ["blocked", null],
    ["progress", null],
    ["skipped_model", "Set up models"],
    ["offline_bundle", "Continue"],
    ["credential_gated", null],
    ["beta_handoff", null],
    ["activitypub_setup", null]
  ]);
  for (const [state, expectedPrimary] of expectedPrimaryByState) {
    await page.goto(`/?state=${state}`);
    const primary = page.locator(".detail-primary-action");
    if (expectedPrimary === null) {
      await expect(primary).toHaveCount(0);
    } else {
      await expect(primary).toHaveCount(1);
      await expect(primary).toHaveText(expectedPrimary);
      await expect(primary).toBeEnabled();
    }
  }

  await page.goto("/?state=blocked");
  await expect(page.locator(".top-primary-action")).toHaveCount(0);
  // 0, not 1: see the table above -- the native startup state offers nothing.
  await expect(page.locator(".detail-primary-action")).toHaveCount(0);
  // The WSL2 remedy is gone, so assert its ABSENCE rather than deleting the
  // check -- if that button ever comes back on a native station, this fails.
  await expect(page.getByRole("button", { name: "Set up Windows helper" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await page.getByText("More options").click();
  // No repair either: canRepairLane suppresses the platform lane, and repair
  // on a non-runtime lane only ever wrote a state that queued nothing.
  await expect(page.getByRole("button", { name: "Repair this step" })).toHaveCount(0);

  await page.goto("/?state=progress");
  await expect(page.locator(".top-primary-action")).toHaveCount(0);
  await expect(page.locator(".detail-primary-action")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(1);
  await page.getByText("More options").click();
  await expect(page.getByRole("button", { name: "Repair this step" })).toHaveCount(0);

  await page.goto("/?state=error");
  await expect(page.locator(".top-primary-action")).toHaveCount(0);
  await expect(page.locator(".detail-primary-action")).toHaveCount(1);
  await expect(page.locator(".detail-primary-action")).toHaveText("Retry");
  await expect(page.locator(".detail-primary-action")).toBeEnabled();
  await expect(page.locator(".actions > button")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
  await page.getByText("More options").click();
  await expect(page.getByRole("button", { name: "Repair this step" })).toHaveCount(1);

  await page.goto("/?state=skipped_model");
  await expect(page.locator(".detail-primary-action")).toHaveCount(1);
  await expect(page.locator(".detail-primary-action")).toHaveText("Set up models");
  await expect(page.locator(".detail-primary-action")).toBeEnabled();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);

  await page.goto("/?state=success");
  await expect(page.getByRole("button", { name: "Open operator console" })).toHaveCount(1);
});

test("restart handoff is explicit and installer failures provide a working log action", async ({ page }) => {
  await page.addInitScript(() => {
    const initialProgress = {
      schema_version: 1,
      current_lane_id: "wsl2",
      status: "blocked",
      message: "Windows enabled the required features. Restart Windows before setup can continue.",
      reboot_required: true,
      updated_at_unix: 1
    };
    if (!window.localStorage.getItem("civiccast.testNativeProgress")) {
      window.localStorage.setItem("civiccast.testNativeProgress", JSON.stringify(initialProgress));
    }
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return window.localStorage.getItem("civiccast.testNativeProgress") ?? "null";
          }
          if (command === "open_installer_log") {
            return "Opened the CivicCast installer log.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });

  await page.goto("/?downloadExperience=0");
  await expect(page.getByRole("button", { name: "Resume after reboot" })).toBeVisible();

  await page.evaluate(() => {
    window.localStorage.setItem(
      "civiccast.testNativeProgress",
      JSON.stringify({
        schema_version: 1,
        current_lane_id: "runtime",
        status: "error",
        message: "CivicCast runtime setup failed (exit code: 43).",
        reboot_required: false,
        updated_at_unix: 2
      })
    );
  });
  await page.reload();

  const openLog = page.getByRole("button", { name: "Open installer log" });
  await expect(openLog).toBeVisible();
  await openLog.click();
  await expect(page.getByRole("status")).toContainText("Opened the CivicCast installer log.");
});

test("installer live summary preserves the backend platform", async ({ page }) => {
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "windows-wsl2",
        operator_console_url: "http://127.0.0.1:5173",
        lanes: [
          {
            id: "platform",
            label: "Platform bootstrap",
            status: "blocked",
            ready: false,
            next_step:
              "Choose Set up Windows helper. Approve the Windows security prompt, restart if Windows asks, then reopen CivicCast Installer."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        lanes: [
          {
            id: "clean-windows-install-proof",
            label: "Clean Windows install proof",
            status: "blocked",
            ready: false,
            message: "Clean Windows proof is blocked until an isolated target is exercised.",
            operator_action: "Rerun the proof command on an isolated Windows target.",
            evidence_target: "docs/releases/evidence/v1.2-clean-windows-install-proof.md"
          },
          {
            id: "external-providers",
            label: "External provider proof",
            status: "credential_or_secret_required",
            ready: false,
            message: "External provider proof requires approved credentials.",
            operator_action: "Run controlled provider proof with redacted evidence.",
            evidence_target: "docs/ops/credential-matrix.md"
          }
        ]
      })
    });
  });
  await page.goto("/?downloadExperience=0");
  await expect(page.getByLabel("Selected platform")).toContainText("windows-wsl2");
  await expect(page.getByRole("button", { name: /Platform bootstrap/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Clean Windows install proof/ })).toBeVisible();
});

test("installer ready state hands off to the operator console", async ({ page }) => {
  await page.goto("/?state=success");
  const consoleButton = page.getByRole("button", { name: "Open operator console" }).first();

  await expect(consoleButton).toBeVisible();
  await expect(consoleButton).toHaveAttribute("title", "http://127.0.0.1:8000/operator/");
  await expect(consoleButton).toBeEnabled();
  await expect(page.getByRole("link", { name: "Report a beta issue" })).toBeVisible();
  await expect(page.getByText("CivicCast is installed and ready.")).toBeVisible();
});

test("background polling preserves the step the operator selected", async ({ page }) => {
  await page.addInitScript(() => {
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return JSON.stringify({
              schema_version: 1,
              current_lane_id: "wsl2",
              status: "ready",
              message: "CivicCast is running and healthy on this computer.",
              reboot_required: false,
              updated_at_unix: Date.now()
            });
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: true,
        platform: "windows-wsl2",
        lanes: [
          { id: "wsl2", label: "Windows helper", status: "success", ready: true, next_step: "Ready." },
          { id: "runtime", label: "CivicCast setup", status: "success", ready: true, next_step: "Ready." }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => route.abort());

  await page.goto("/");
  await page.getByRole("button", { name: /CivicCast setup/ }).click();
  await expect(page.getByRole("heading", { name: "CivicCast setup" })).toBeVisible();
  await page.waitForTimeout(2300);
  await expect(page.getByRole("heading", { name: "CivicCast setup" })).toBeVisible();
});

test("installer skipped-model state tells operators how to finish AI setup", async ({ page }) => {
  await page.goto("/?state=skipped_model");
  await expect(page.getByRole("heading", { name: "AI models skipped" })).toBeVisible();
  await expect(page.getByText("The installer has not verified Whisper or Ollama model hashes for this workstation.")).toBeVisible();
  await expect(page.getByText("Choose Set up models to download or import verified model files before the first captioned meeting.")).toBeVisible();
});

test("installer blocked non-Windows platform does not offer Windows helper action", async ({ page }) => {
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "linux",
        operator_console_url: "http://127.0.0.1:5173",
        lanes: [
          {
            id: "platform",
            label: "Setting up CivicCast",
            status: "blocked",
            ready: false,
            next_step: "This Linux computer is missing a required setup component."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ready: false, lanes: [] })
    });
  });

  await page.goto("/?downloadExperience=0");

  await expect(page.locator(".detail-primary-action", { hasText: "Set up Windows helper" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Continue" }).first()).toHaveCount(0);
  await expect(page.locator(".step-detail > p").first()).toContainText(
    "This Linux computer is missing a required setup component."
  );
});

test("installer reconciles a stale in-memory blocked state once the on-disk state turns ready, without a reload (T-3)", async ({ page }) => {
  await page.addInitScript(() => {
    let reads = 0;
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            reads += 1;
            // The first two reads (initial load + its fetch-failure fallback) see nothing
            // recorded yet, matching an operator who opened the installer before the helper
            // finished. From the third read on, the on-disk state file has since turned ready
            // -- simulating a change that happened while this window stayed open.
            if (reads <= 2) {
              return "null";
            }
            return JSON.stringify({
              schema_version: 1,
              current_lane_id: "runtime",
              status: "ready",
              message: "CivicCast prepared storage, started, and opened the dashboard.",
              reboot_required: false,
              updated_at_unix: 2,
              operator_console_url: "http://127.0.0.1:8000/operator/"
            });
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.abort();
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.abort();
  });

  await page.goto("/?downloadExperience=0");
  await expect(page.getByRole("heading", { name: "Windows helper missing" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open operator console" })).toHaveCount(0);

  // No reload, no user action: the background poll (2s interval) must pick up the change.
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toBeEnabled({ timeout: 5000 });
  await expect(page.getByRole("heading", { name: "Windows helper missing" })).toBeHidden();
});

test("installer revokes stale Ready when the installed runtime becomes unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    let reads = 0;
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command !== "read_local_installer_state") {
            throw new Error(`unexpected command ${command}`);
          }
          reads += 1;
          return JSON.stringify({
            schema_version: 1,
            current_lane_id: "runtime",
            status: reads <= 2 ? "ready" : "unavailable",
            message:
              reads <= 2
                ? "CivicCast is running and healthy on this computer."
                : "CivicCast is not responding. The background runtime host is attempting recovery.",
            reboot_required: false,
            updated_at_unix: reads,
            operator_console_url: "http://127.0.0.1:8000/operator/?nonce=proof"
          });
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => route.abort());
  await page.route("/api/staff/installer/beta-handoff", async (route) => route.abort());

  await page.goto("/?downloadExperience=0");
  await expect(page.locator(".ready-pill")).toHaveText("Ready");
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toBeEnabled();

  await expect(page.locator(".blocked-pill")).toHaveText("Not ready", { timeout: 6000 });
  await expect(page.getByText(/background runtime host is attempting recovery/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Open operator console" })).toHaveCount(0);
});

test("installer never shows the optimistic 'finishing setup' banner over a stale runtime error card (UX-2 / G-9a)", async ({ page }) => {
  await page.addInitScript(() => {
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return "null";
          }
          if (command === "run_local_installer_action") {
            await new Promise((resolve) => window.setTimeout(resolve, 300));
            return "CivicCast is running at http://127.0.0.1:8000.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  // The runtime lane starts out showing a previous run's failure -- the exact stale card the
  // walkthrough screenshotted underneath the "finishing setup" banner.
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "windows-wsl2",
        lanes: [
          {
            id: "platform",
            label: "Windows helper",
            status: "success",
            ready: true,
            next_step: "CivicCast is finishing setup."
          },
          {
            id: "runtime",
            label: "CivicCast setup",
            status: "partial",
            ready: false,
            next_step: "Broadcast engine setup failed: CivicCast runtime setup failed (exit code 43)."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "text/plain",
      body: "not found"
    });
  });

  await page.goto("/?downloadExperience=0");

  // The auto-retry banner and the exit-43 failure card must never render at the same time.
  await expect(page.getByRole("status")).toContainText("CivicCast is finishing setup.");
  await expect(page.getByText(/exit code 43/)).toBeHidden();
  await expect(page.getByLabel("Installer wizard").getByText("Retrying automatically")).toBeVisible();
});

test("installer local helper-ready progress continues to CivicCast setup", async ({ page }) => {
  await page.addInitScript(() => {
    let progress = {
        schema_version: 1,
        current_lane_id: "platform",
        status: "ready",
        message: "The Windows helper CivicCast needs is ready.",
        reboot_required: false,
        updated_at_unix: 1
      };
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return JSON.stringify(progress);
          }
          if (command === "run_local_installer_action") {
            progress = {
              ...progress,
              current_lane_id: "runtime",
              status: "ready",
              message: "CivicCast prepared storage, started, and opened the dashboard."
            };
            return "CivicCast is running at http://127.0.0.1:8000.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.abort();
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.abort();
  });

  await page.goto("/?downloadExperience=0");

  await expect(page.getByRole("button", { name: /CivicCast setup/ })).toContainText("Ready");
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toBeEnabled();
});

test("installer continue uses freshly saved runtime-ready progress", async ({ page }) => {
  await page.addInitScript(() => {
    let progress: null | {
      schema_version: number;
      current_lane_id: string;
      status: string;
      message: string;
      reboot_required: boolean;
      updated_at_unix: number;
      operator_console_url?: string;
    } = null;
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return progress === null ? "null" : JSON.stringify(progress);
          }
          if (command === "run_local_installer_action") {
            progress = {
              schema_version: 1,
              current_lane_id: "runtime",
              status: "ready",
              message: "CivicCast prepared storage, started, and opened the dashboard.",
              reboot_required: false,
              updated_at_unix: 2,
              operator_console_url: "http://127.0.0.1:8000/operator/"
            };
            return "CivicCast prepared storage, started, and opened the dashboard.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "windows-wsl2",
        operator_console_url: "http://127.0.0.1:5173",
        lanes: [
          {
            id: "runtime",
            label: "CivicCast setup",
            status: "partial",
            ready: false,
            next_step: "Choose Continue to finish setup and open the operator dashboard."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "text/plain",
      body: "not found"
    });
  });

  await page.goto("/?downloadExperience=0");
  await expect(page.getByRole("heading", { name: "CivicCast setup" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).first().click();

  await expect(page.getByRole("button", { name: /CivicCast setup/ })).toContainText("Ready");
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toHaveAttribute(
    "title",
    "http://127.0.0.1:8000/operator/"
  );
});

test("installer polls native progress until delayed runtime ready is visible", async ({ page }) => {
  await page.addInitScript(() => {
    let progress: null | {
      schema_version: number;
      current_lane_id: string;
      status: string;
      message: string;
      reboot_required: boolean;
      updated_at_unix: number;
      operator_console_url?: string;
    } = null;
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return progress === null ? "null" : JSON.stringify(progress);
          }
          if (command === "run_local_installer_action") {
            progress = {
              schema_version: 1,
              current_lane_id: "runtime",
              status: "running",
              message: "CivicCast is finishing setup. Keep this window open.",
              reboot_required: false,
              updated_at_unix: 2,
              operator_console_url: "http://127.0.0.1:8000/operator/"
            };
            window.setTimeout(() => {
              progress = {
                schema_version: 1,
                current_lane_id: "runtime",
                status: "ready",
                message: "CivicCast prepared storage, started, and opened the dashboard.",
                reboot_required: false,
                updated_at_unix: 3,
                operator_console_url: "http://127.0.0.1:8000/operator/"
              };
            }, 250);
            return "CivicCast is finishing setup. Keep this window open while the dashboard starts.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "windows-wsl2",
        operator_console_url: "http://127.0.0.1:5173",
        lanes: [
          {
            id: "wsl2",
            label: "Windows helper missing",
            status: "blocked",
            ready: false,
            next_step: "Choose Set up Windows helper."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "text/plain",
      body: "not found"
    });
  });

  await page.goto("/?downloadExperience=0");
  await page.getByRole("button", { name: "Set up Windows helper" }).first().click();

  await expect(page.getByRole("button", { name: /CivicCast setup/ })).toContainText("Ready");
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toBeEnabled();
});

test("installer shows live runtime activity and opens the console once when setup becomes ready", async ({ page }) => {
  await page.addInitScript(() => {
    let progress = {
      schema_version: 1,
      current_lane_id: "platform",
      status: "ready",
      message: "The Windows helper CivicCast needs is ready.",
      reboot_required: false,
      updated_at_unix: Math.floor(Date.now() / 1000)
    };
    (window as Window & { __openedOperatorConsoleCount?: number; __TAURI__?: unknown }).__openedOperatorConsoleCount = 0;
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return JSON.stringify(progress);
          }
          if (command === "run_local_installer_action") {
            progress = {
              ...progress,
              current_lane_id: "runtime",
              status: "running",
              message: "CivicCast is staging its bundled offline runtime files."
            };
            window.setTimeout(() => {
              progress = {
                ...progress,
                status: "ready",
                message: "CivicCast prepared storage and started the dashboard.",
                operator_console_url: "http://127.0.0.1:8000/operator/?nonce=proof"
              };
            }, 4500);
            return "CivicCast is finishing setup. Keep this window open.";
          }
          if (command === "open_operator_console") {
            (window as Window & { __openedOperatorConsoleCount?: number }).__openedOperatorConsoleCount =
              ((window as Window & { __openedOperatorConsoleCount?: number }).__openedOperatorConsoleCount ?? 0) + 1;
            return "Opening the operator console.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => route.abort());
  await page.route("/api/staff/installer/beta-handoff", async (route) => route.abort());

  await page.goto("/?downloadExperience=0");
  await expect(page.getByRole("status", { name: "CivicCast setup activity" })).toContainText(
    "CivicCast is staging its bundled offline runtime files."
  );
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toBeEnabled({ timeout: 10000 });
  await expect(page.getByRole("status")).toContainText("Opening the operator console.");
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as Window & { __openedOperatorConsoleCount?: number }).__openedOperatorConsoleCount
      )
    )
    .toBe(1);
});

test("installer reads packaged helper-ready progress before backend fixtures", async ({ page }) => {
  await page.addInitScript(() => {
    const readyProgress = JSON.stringify({
      schema_version: 1,
      current_lane_id: "platform",
      status: "ready",
      message: "The Windows helper CivicCast needs is ready.",
      reboot_required: false,
      updated_at_unix: 1,
      operator_console_url: "http://127.0.0.1:8000/operator/"
    });
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return readyProgress;
          }
          if (command === "run_local_installer_action") {
            return "CivicCast is finishing setup. Keep this window open.";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        platform: "windows-wsl2",
        lanes: [
          {
            id: "wsl2",
            label: "Windows helper missing",
            status: "blocked",
            ready: false,
            next_step: "Choose Set up Windows helper."
          }
        ]
      })
    });
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.abort();
  });

  await page.goto("/?downloadExperience=0");

  await expect(page.getByRole("button", { name: /Windows helper/ })).toContainText("Ready");
  await expect(page.getByRole("heading", { name: "CivicCast setup" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" }).first()).toBeEnabled();
});

test("installer marks local runtime-ready progress as dashboard ready", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "civiccast.installerProgress",
      JSON.stringify({
        schema_version: 1,
        current_lane_id: "runtime",
        status: "ready",
        message: "CivicCast prepared storage, started, and opened the dashboard.",
        reboot_required: false,
        updated_at_unix: 1,
        operator_console_url: "http://127.0.0.1:8000/operator/"
      })
    );
  });
  await page.route("/api/staff/installer/summary", async (route) => {
    await route.abort();
  });
  await page.route("/api/staff/installer/beta-handoff", async (route) => {
    await route.abort();
  });

  await page.goto("/?downloadExperience=0");

  await expect(page.getByText("Ready").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Open operator console" }).first()).toHaveAttribute(
    "title",
    "http://127.0.0.1:8000/operator/"
  );
  await expect(page.getByRole("button", { name: /CivicCast setup/ })).toContainText("Ready");
});

test("installer saves repair progress and can reset it", async ({ page }) => {
  await page.goto("/?state=blocked");
  await page.getByText("More options").click();
  await page.getByRole("button", { name: "Repair this step" }).click();

  await expect(page.getByRole("status")).toContainText("queued");
  await page.reload();
  await expect(page.getByLabel("Resume installer state")).toContainText("CivicCast queued this installer lane.");

  await page.getByRole("button", { name: "Reset progress" }).click();
  await expect(page.getByRole("status")).toContainText("reset installer progress");
  await expect(page.getByLabel("Resume installer state")).toBeHidden();
});

test("installer presents ActivityPub as optional advanced post-install setup", async ({ page }) => {
  await page.goto("/?state=activitypub_setup");
  await page.getByRole("button", { name: /ActivityPub federation/ }).click();

  await expect(page.getByRole("heading", { name: "ActivityPub federation" })).toBeVisible();
  await expect(page.getByLabel("ActivityPub setup")).toContainText("Advanced optional setup");
  await expect(page.getByLabel("ActivityPub setup")).toContainText("not required to finish installing CivicCast");
  await expect(page.getByText(/civiccast activitypub keygen/)).toHaveCount(0);
  const guide = page.getByRole("link", { name: "ActivityPub federation guide" });
  await expect(guide).toHaveAttribute(
    "href",
    "https://github.com/scottconverse/civiccast-native/blob/main/docs/ops/activitypub-federation.md"
  );
});

test("installer offline-bundle state requires hash verification before air-gapped use", async ({ page }) => {
  await page.goto("/?state=offline_bundle");
  await expect(page.getByRole("heading", { name: "Offline model bundle" })).toBeVisible();
  await expect(page.getByText("Bundle metadata is present, but the installer still needs to verify every model hash without network access.")).toBeVisible();
  await expect(page.getByText("Choose Verify bundle after inserting the approved USB media with the model bundle manifest.")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Download experience default-on (task #46's transport slice): the
// ?downloadExperience=1 opt-in gate is gone -- a fresh install now sees the
// machine-check / plan / downloading screens BEFORE the existing lane
// wizard, unless the ?downloadExperience=0 escape hatch every other test
// above now passes is present. These two specs are the ones that actually
// exercise the flip itself; every other spec in this file deliberately opts
// back out to keep testing the lane wizard directly, per its original intent.
// ---------------------------------------------------------------------------

test("installer shows the download experience first by default on a fresh install", async ({ page }) => {
  await page.addInitScript(() => {
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return "null";
          }
          // native_hardware_inventory, measure_link_speed_bytes_per_second, and
          // retry_acquisition_component all have honest browser-fallback
          // behavior in api.ts for exactly this "command not available" case
          // -- a typed {ok:false} probe failure (G011.1: the fabricated
          // hardware mock that used to stand in here is gone, so this run
          // reaches the checking screen's "Hardware check unavailable" state
          // and its Continue), a null "nothing measured" rate, and a
          // queued-retry message respectively. There is nothing to stub here.
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => route.abort());
  await page.route("/api/staff/installer/beta-handoff", async (route) => route.abort());

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Checking This Computer" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "CivicCast Installer" })).toHaveCount(0);

  const continueToPlan = page.getByRole("button", { name: "Continue" });
  await expect(continueToPlan).toBeVisible({ timeout: 5000 });
  await continueToPlan.click();

  await expect(page.getByRole("heading", { name: "What We'll Download" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Downloading" })).toBeVisible();
});

test("installer downloadExperience=0 skips straight to the existing lane wizard", async ({ page }) => {
  await page.addInitScript(() => {
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          if (command === "read_local_installer_state") {
            return "null";
          }
          throw new Error(`unexpected command ${command}`);
        }
      }
    };
  });
  await page.route("/api/staff/installer/summary", async (route) => route.abort());
  await page.route("/api/staff/installer/beta-handoff", async (route) => route.abort());

  await page.goto("/?downloadExperience=0");

  await expect(page.getByRole("heading", { name: "CivicCast Installer" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Installer wizard" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Checking This Computer" })).toHaveCount(0);
});

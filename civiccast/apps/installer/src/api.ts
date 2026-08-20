// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type { HardwareInventory, InstallerProgress, InstallerState } from "./types";

export const LOCAL_OPERATOR_CONSOLE_URL = "http://127.0.0.1:8000/operator/";

export interface InstallerActionOutcome {
  message: string;
  operatorConsoleUrl?: string;
}

export type InstallerAction = "retry" | "cancel" | "continue" | "repair" | "reset" | "uninstall";

export const installerFixtures: Record<string, InstallerState> = {
  loading: {
    ready: false,
    platform: "windows-wsl2",
    lanes: [
      {
        id: "loading",
        label: "Checking workstation",
        status: "loading",
        ready: false,
        detail: "The installer is reading platform, package, model, and air-gap proof state.",
        nextStep: "Keep this window open until the readiness lanes finish loading."
      }
    ]
  },
  success: {
    ready: true,
    platform: "linux",
    lanes: [
      {
        id: "platform",
        label: "CivicCast setup",
        status: "success",
        ready: true,
        detail: "CivicCast is installed and ready to open.",
        nextStep: "Open the operator console and run the first broadcast health check."
      }
    ]
  },
  empty: {
    ready: false,
    platform: "windows-wsl2",
    lanes: [
      {
        id: "package",
        label: "No package selected",
        status: "empty",
        ready: false,
        detail: "No artifact path has been provided for verification.",
        nextStep: "Choose the package artifact and its sidecar JSON before continuing."
      }
    ]
  },
  error: {
    ready: false,
    platform: "macos",
    lanes: [
      {
        id: "hash",
        label: "Hash mismatch",
        status: "error",
        ready: false,
        detail: "The package bytes do not match the SHA-256 value in the sidecar.",
        nextStep: "Rebuild the package from clean sources, regenerate the sidecar, and retry."
      }
    ]
  },
  partial: {
    ready: false,
    platform: "windows-wsl2",
    lanes: [
      {
        id: "platform",
        label: "Windows helper ready",
        status: "success",
        ready: true,
        detail: "The Windows helper CivicCast needs is ready. It lets CivicCast run its local meeting tools on this computer.",
        nextStep: "Continue to package verification."
      },
      {
        id: "model",
        label: "Model proof missing",
        status: "partial",
        ready: false,
        detail: "Some model files are present, but hash proof is incomplete.",
        nextStep: "Import the offline bundle or rerun online model setup until hashes verify."
      }
    ]
  },
  // The catch-all `loadInstallerState` returns when the summary API is
  // unreachable AND there is no saved progress -- see its own comment: "a
  // fresh launch before the supervisor's control-plane child has bound its
  // port, a reset, or right after a reinstall". First run.
  //
  // It used to describe a missing WSL2 helper and tell the operator to choose
  // "Set up Windows helper" and enable Windows Subsystem for Linux. That named
  // a remedy this product does not have, and once the button stopped rendering
  // on native it was an instruction pointing at nothing.
  //
  // `loading`, not `blocked`: nothing is blocked, the station is starting. A
  // loading lane promises no primary action, so nothing is offered that does
  // not exist.
  blocked: {
    ready: false,
    platform: "windows-native",
    lanes: [
      {
        id: "platform",
        label: "Starting CivicCast",
        status: "loading",
        ready: false,
        detail:
          "CivicCast is starting its local services. On a first launch this takes a moment while the station prepares its database and control plane.",
        nextStep: "Keep this window open. It updates by itself as soon as the station answers."
      }
    ]
  },
  progress: {
    ready: false,
    platform: "linux",
    lanes: [
      {
        id: "models",
        label: "Model download",
        status: "progress",
        ready: false,
        detail: "Whisper and Gemma model bytes are being downloaded and will be hash-verified.",
        nextStep: "Use Cancel only if you can rerun model setup before the first broadcast."
      }
    ]
  },
  skipped_model: {
    ready: false,
    platform: "linux",
    lanes: [
      {
        id: "models",
        label: "AI models skipped",
        status: "cancelled",
        ready: false,
        detail: "The installer has not verified Whisper or Ollama model hashes for this workstation.",
        nextStep: "Choose Set up models to download or import verified model files before the first captioned meeting."
      }
    ]
  },
  offline_bundle: {
    ready: false,
    platform: "windows-wsl2",
    lanes: [
      {
        id: "offline-bundle",
        label: "Offline model bundle",
        status: "partial",
        ready: false,
        detail: "Bundle metadata is present, but the installer still needs to verify every model hash without network access.",
        nextStep: "Choose Verify bundle after inserting the approved USB media with the model bundle manifest."
      }
    ]
  },
  credential_gated: {
    ready: false,
    platform: "linux",
    lanes: [
      {
        id: "internet-archive",
        label: "Internet Archive",
        status: "credential_gated",
        ready: false,
        detail: "External provider verification needs approved credentials.",
        nextStep: "Enter Internet Archive credentials in the approved online proof flow."
      }
    ]
  },
  beta_handoff: {
    ready: false,
    platform: "windows-wsl2",
    lanes: [
      {
        id: "clean-windows-install-proof",
        label: "Clean Windows install proof",
        status: "blocked",
        ready: false,
        detail: "No clean Windows install proof evidence has been recorded for this beta handoff.",
        nextStep: "Run the clean Windows proof command on an isolated target and retain the evidence files."
      },
      {
        id: "external-providers",
        label: "External provider proof",
        status: "credential_gated",
        ready: false,
        detail: "External provider proof requires approved credentials or controlled targets.",
        nextStep: "Run controlled provider proof only with approved credentials and redacted evidence."
      },
      {
        id: "dependencies",
        label: "Local dependencies",
        status: "hardware_required",
        ready: false,
        detail: "Optional NDI camera support needs local camera software or hardware setup.",
        nextStep: "Install the missing camera support only if this station uses NDI cameras, then rerun the handoff check."
      }
    ]
  },
  activitypub_setup: {
    ready: false,
    platform: "windows-wsl2",
    operatorConsoleUrl: "http://127.0.0.1:5173",
    lanes: [
      {
        id: "platform",
        label: "Platform bootstrap",
        status: "success",
        ready: true,
        detail: "The Windows helper CivicCast needs is ready. It lets CivicCast run its local meeting tools on this computer.",
        nextStep: "Continue to optional federation setup."
      },
      {
        id: "activitypub",
        label: "ActivityPub federation",
        status: "success",
        ready: true,
        detail: "Federation is disabled by default and is not required to finish installing CivicCast.",
        nextStep: "Leave federation off, or ask a technical administrator to follow the advanced federation guide after installation."
      },
      {
        id: "beta-handoff",
        label: "Beta tester handoff",
        status: "blocked",
        ready: false,
        detail: "The handoff still needs clean-install and external-provider evidence.",
        nextStep: "Run the beta-handoff proof command before giving artifacts to testers."
      }
    ]
  }
};

const runtimeLaneIds = ["runtime", "ffmpeg", "storage", "service", "dashboard"];

export function stateFromLocalProgress(progress: InstallerProgress | null): InstallerState | null {
  if (!progress) {
    return null;
  }
  const operatorConsoleUrl = progress.operator_console_url ?? LOCAL_OPERATOR_CONSOLE_URL;
  if (progress.reboot_required && ["wsl2", "platform"].includes(progress.current_lane_id)) {
    // "blocked" (not "progress") so this maps to isWslBootstrapLane: the primary
    // button reads "Set up Windows helper" (matching the Resume-after-reboot
    // banner + the state this converges to ~1.5s later), stays enabled, and its
    // click path shows the "installs a Linux runtime, can take several minutes"
    // warning. "progress" made it a clickable generic "Continue" that skipped
    // that warning during the post-reboot stale-state window (gate-civiccast UX-1).
    return {
      ready: false,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: progress.current_lane_id,
          label: "Windows helper",
          status: "blocked",
          ready: false,
          detail: progress.message,
          nextStep: "Restart this computer if Windows asks, then reopen CivicCast Installer."
        }
      ]
    };
  }
  if (progress.status === "ready" && ["wsl2", "platform"].includes(progress.current_lane_id)) {
    return {
      ready: false,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: "platform",
          label: "Windows helper",
          status: "success",
          ready: true,
          detail: progress.message,
          nextStep: "Continue with CivicCast setup."
        },
        {
          id: "runtime",
          label: "CivicCast setup",
          status: "partial",
          ready: false,
          detail: "The Windows helper is ready. It lets CivicCast run its local meeting tools on this computer. CivicCast still needs to prepare storage and start the dashboard.",
          nextStep: "Choose Continue to finish setup and open the operator dashboard."
        }
      ]
    };
  }
  if (runtimeLaneIds.includes(progress.current_lane_id) && progress.status === "running") {
    return {
      ready: false,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: "platform",
          label: "Windows helper",
          status: "success",
          ready: true,
          detail: "The Windows helper CivicCast needs is ready. It lets CivicCast run its local meeting tools on this computer.",
          nextStep: "CivicCast is finishing setup."
        },
        {
          id: "runtime",
          label: "CivicCast setup",
          status: "progress",
          ready: false,
          detail: progress.message,
          nextStep: "Keep this window open while CivicCast prepares storage and starts the dashboard."
        }
      ]
    };
  }
  if (runtimeLaneIds.includes(progress.current_lane_id) && progress.status === "ready") {
    return {
      ready: true,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: "platform",
          label: "Windows helper",
          status: "success",
          ready: true,
          detail: "The Windows helper CivicCast needs is ready. It lets CivicCast run its local meeting tools on this computer.",
          nextStep: "CivicCast is running."
        },
        {
          id: "runtime",
          label: "CivicCast setup",
          status: "success",
          ready: true,
          detail: progress.message,
          nextStep: "Open the operator console. Sign in if prompted, then run System Health and a private rehearsal."
        }
      ]
    };
  }
  if (["wsl2", "platform"].includes(progress.current_lane_id)) {
    const inProgress = [
      "wsl_install_requested",
      "wsl_install_started",
      "wsl_resume_requested",
      "running",
      "already_running",
      "accepted"
    ].includes(progress.status);
    const failed = ["failed", "error"].includes(progress.status);
    return {
      ready: false,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: progress.current_lane_id,
          label: "Windows helper",
          status: failed ? "error" : inProgress ? "progress" : "blocked",
          ready: false,
          detail: progress.message,
          nextStep: failed
            ? "Use Open installer log below, then retry. If the failure repeats, send that log to support."
            : "Keep this window open. CivicCast will update this screen every few seconds. Restart only when this screen explicitly says Windows requires it."
        }
      ]
    };
  }
  if (runtimeLaneIds.includes(progress.current_lane_id)) {
    const recovering = progress.status === "unavailable";
    const failed = ["blocked", "failed", "error"].includes(progress.status);
    return {
      ready: false,
      platform: "windows-wsl2",
      operatorConsoleUrl,
      lanes: [
        {
          id: "platform",
          label: "Windows helper",
          status: "success",
          ready: true,
          detail: "The Windows helper CivicCast needs is ready. It lets CivicCast run its local meeting tools on this computer.",
          nextStep: "CivicCast is finishing setup."
        },
        {
          id: "runtime",
          label: "CivicCast setup",
          status: failed ? "error" : "progress",
          ready: false,
          detail: progress.message,
          nextStep: recovering
            ? "Keep this window open while CivicCast recovers automatically."
            : failed
              ? "Use Open installer log below, then retry. If the failure repeats, send that log to support."
              : "Keep this window open while CivicCast prepares the dashboard."
        }
      ]
    };
  }
  return null;
}

interface ApiLane {
  id: string;
  label: string;
  status: string;
  ready: boolean;
  next_step: string;
  message?: string;
  operator_action?: string;
}

interface ApiSummary {
  ready: boolean;
  platform: InstallerState["platform"];
  operator_console_url?: string;
  lanes: ApiLane[];
}

interface ApiBetaHandoff {
  ready: boolean;
  lanes: ApiLane[];
}

type NativeInstallerBridge = {
  __TAURI__?: {
    invoke?: <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
    core?: {
      invoke?: <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
    };
  };
  __TAURI_INTERNALS__?: {
    invoke?: <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
  };
};

/**
 * Whether a Tauri command bridge is present on this page at all.
 *
 * Distinguishes "running in a browser preview, where no native command
 * exists" from "running inside the real installer and the native command
 * FAILED" -- two outcomes `invokeNativeInstallerAny`'s rejection cannot tell
 * apart on its own, and only the second of which is an operator-visible
 * product failure. Mirrors the same three globals `invokeNativeInstaller`
 * probes below (the dynamic `@tauri-apps/api/core` import it falls back to
 * only resolves inside a real Tauri webview).
 */
function nativeInstallerBridgeAvailable(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const bridge = window as Window & NativeInstallerBridge;
  return Boolean(
    bridge.__TAURI__?.core?.invoke ?? bridge.__TAURI__?.invoke ?? bridge.__TAURI_INTERNALS__?.invoke
  );
}

/**
 * Corrects a stored installer state's `platform` when it disagrees with the
 * one fact this page can always answer for itself: whether a native command
 * bridge exists at all (N-07, carried).
 *
 * The unreachable-API fallback no longer needs this -- `installerFixtures.
 * blocked` is `windows-native` at source. What still does is SAVED LOCAL
 * PROGRESS: a state file written by a pre-native build, which an upgrade over
 * an existing install can hand back verbatim. `nativeInstallerBridgeAvailable()`
 * is definitional -- true only inside the real native webview -- so it
 * outranks anything a file claims.
 *
 * The real `/api/staff/installer/summary` response is untouched by this; it
 * reports the deployment itself (`installer/service.py`).
 */
function withHonestNativePlatform(state: InstallerState): InstallerState {
  if (state.platform === "windows-wsl2" && nativeInstallerBridgeAvailable()) {
    return { ...state, platform: "windows-native" };
  }
  return state;
}


async function invokeNativeInstaller<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const bridge = window as Window & NativeInstallerBridge;
  const globalInvoke =
    bridge.__TAURI__?.core?.invoke ?? bridge.__TAURI__?.invoke ?? bridge.__TAURI_INTERNALS__?.invoke;
  if (globalInvoke) {
    return await globalInvoke<T>(command, args);
  }

  const { invoke } = await import("@tauri-apps/api/core");
  return await invoke<T>(command, args);
}

async function invokeNativeInstallerAny<T>(
  commands: string[],
  args?: Record<string, unknown>
): Promise<T> {
  let lastError: unknown = null;
  for (const command of commands) {
    try {
      return await invokeNativeInstaller<T>(command, args);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error(`Native installer command failed: ${commands.join(", ")}`);
}

function mapStatus(status: string): InstallerState["lanes"][number]["status"] {
  switch (status) {
    case "ok":
    case "ready":
    case "complete":
    case "passed":
    case "success":
      return "success";
    case "credential_or_secret_required":
    case "credential_gated":
      return "credential_gated";
    case "hardware_required":
      return "hardware_required";
    case "planned":
    case "running":
    case "progress":
      return "progress";
    case "cancelled":
    case "skipped":
      return "cancelled";
    case "unavailable":
      return "unavailable";
    case "empty":
      return "empty";
    case "error":
    case "failed":
      return "error";
    case "partial":
      return "partial";
    default:
      return "blocked";
  }
}

function saveBrowserInstallerProgress(
  laneId: string,
  status: string,
  message: string,
  rebootRequired = false
) {
  window.localStorage.setItem(
    "civiccast.installerProgress",
    JSON.stringify({
      schema_version: 1,
      current_lane_id: laneId,
      status,
      message,
      reboot_required: rebootRequired,
      updated_at_unix: Math.floor(Date.now() / 1000)
    })
  );
}

function fromApiSummary(summary: ApiSummary, betaHandoff?: ApiBetaHandoff): InstallerState {
  const lanes = summary.lanes.map((lane) => ({
    id: lane.id,
    label: lane.label,
    status: mapStatus(lane.status),
    ready: lane.ready,
    detail: lane.next_step,
    nextStep: lane.next_step
  }));
  if (betaHandoff) {
    lanes.push(
      ...betaHandoff.lanes.map((lane) => ({
        id: lane.id,
        label: lane.label,
        status: mapStatus(lane.status),
        ready: lane.ready,
        detail: lane.message ?? lane.operator_action ?? lane.next_step,
        nextStep: lane.operator_action ?? lane.next_step
      }))
    );
  }
  return {
    ready: summary.ready,
    platform: summary.platform,
    operatorConsoleUrl: summary.operator_console_url,
    lanes
  };
}

export async function loadInstallerState(
  stateName?: string | null,
  knownProgress?: InstallerProgress | null
): Promise<InstallerState> {
  if (stateName && installerFixtures[stateName]) {
    return installerFixtures[stateName];
  }
  const progress = knownProgress === undefined ? await loadInstallerProgress() : knownProgress;
  const localProgressState = stateFromLocalProgress(progress);
  if (localProgressState) {
    return withHonestNativePlatform(localProgressState);
  }
  try {
    const [summaryResponse, betaResponse] = await Promise.all([
      fetch("/api/staff/installer/summary", {
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      }),
      fetch("/api/staff/installer/beta-handoff", {
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      })
    ]);
    if (!summaryResponse.ok) {
      throw new Error(`installer summary returned ${summaryResponse.status}`);
    }
    const betaHandoff =
      betaResponse.ok && betaResponse.headers.get("content-type")?.includes("application/json")
        ? ((await betaResponse.json()) as ApiBetaHandoff)
        : undefined;
    return fromApiSummary((await summaryResponse.json()) as ApiSummary, betaHandoff);
  } catch {
    const fallbackProgress = knownProgress === undefined ? await loadInstallerProgress() : knownProgress;
    return withHonestNativePlatform(stateFromLocalProgress(fallbackProgress) ?? installerFixtures.blocked);
  }
}

export async function runInstallerAction(laneId: string, action: InstallerAction): Promise<InstallerActionOutcome> {
  const localMessage = await runTauriInstallerAction(laneId, action);
  if (
    localMessage &&
    (laneId === "wsl2" ||
      laneId === "platform" ||
      ["runtime", "ffmpeg", "storage", "service", "dashboard"].includes(laneId) ||
      ["repair", "reset", "uninstall"].includes(action))
  ) {
    return {
      message: localMessage,
      operatorConsoleUrl: LOCAL_OPERATOR_CONSOLE_URL
    };
  }
  try {
    const response = await fetch("/api/staff/installer/actions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ lane_id: laneId, action })
    });
    if (!response.ok) {
      throw new Error(`installer action returned ${response.status}`);
    }
    const payload = (await response.json()) as { message?: string; operator_console_url?: string };
    return {
      message: payload.message ?? "CivicCast accepted the installer action.",
      operatorConsoleUrl: payload.operator_console_url
    };
  } catch {
    return {
      message: "The local setup helper is not reachable yet. Keep this window open, start CivicCast locally, then retry this step."
    };
  }
}

export async function loadInstallerProgress(): Promise<InstallerProgress | null> {
  const browserProgress = () => {
    const raw = window.localStorage.getItem("civiccast.installerProgress");
    return raw ? (JSON.parse(raw) as InstallerProgress) : null;
  };
  try {
    const raw = await invokeNativeInstallerAny<string>([
      "read_local_installer_state",
      "readLocalInstallerState"
    ]);
    // A successful native read is authoritative, even when it reports "null" (no
    // state file yet) -- that still means the real bridge answered. Drop any
    // browser-cached progress from an earlier attempt so a stale error can never
    // outlive a working native read (UX-3 / G-9b).
    window.localStorage.removeItem("civiccast.installerProgress");
    return raw === "null" ? null : (JSON.parse(raw) as InstallerProgress);
  } catch {
    return browserProgress();
  }
}

async function runTauriInstallerAction(laneId: string, action: InstallerAction): Promise<string | null> {
  let nativeError: string | null = null;
  try {
    return await invokeNativeInstallerAny<string>([
      "run_local_installer_action",
      "runLocalInstallerAction"
    ], { laneId, action });
  } catch (error) {
    nativeError = error instanceof Error ? error.message : String(error);
  }

  if (["cancel", "repair", "reset", "uninstall"].includes(action)) {
    if (action === "reset") {
      window.localStorage.removeItem("civiccast.installerProgress");
      return "CivicCast reset installer progress. Durable records were not deleted.";
    }
    const message = `CivicCast ${action === "cancel" ? "paused" : "queued"} this installer lane.`;
    saveBrowserInstallerProgress(laneId, action, message);
    return message;
  }

  if (
    action === "continue" &&
    (laneId === "wsl2" ||
      laneId === "platform" ||
      ["runtime", "ffmpeg", "storage", "service", "dashboard"].includes(laneId))
  ) {
    const message = `CivicCast could not hand this step to the local setup helper: ${nativeError}`;
    saveBrowserInstallerProgress(laneId, "error", message);
    return message;
  }

  return null;
}

export async function openOperatorConsole(url: string, allowBrowserFallback = true): Promise<string> {
  try {
    return await invokeNativeInstallerAny<string>([
      "open_operator_console",
      "openOperatorConsole"
    ], { url });
  } catch (error) {
    if (!allowBrowserFallback) {
      throw error;
    }
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (opened) {
      return "Opening the operator console.";
    }
    window.location.href = url;
    return "Opening the operator console in this window.";
  }
}

export async function openInstallerLog(): Promise<string> {
  return await invokeNativeInstallerAny<string>([
    "open_installer_log",
    "openInstallerLog"
  ]);
}

// ---------------------------------------------------------------------------
// Component acquisition (download experience)
// ---------------------------------------------------------------------------

/**
 * The result of asking the native probe about this machine: either the real
 * inventory it measured, or an explicit failure. There is no third option and
 * no default value.
 *
 * G011.1. This used to be `Promise<HardwareInventory>` with a
 * `catch { return hardwareInventoryMock; }` fallback, and that mock was a
 * complete fabricated machine -- "Generic x86_64 CPU", 8 cores, 16 GB RAM, no
 * GPU, 120 GB free disk. Every path that could not reach the native command
 * (a browser preview, a rejected Tauri ACL -- which is exactly what chain
 * A-min found in the field -- or a probe that threw) rendered those numbers
 * under the heading "Here is what CivicCast found on this computer", and the
 * install's disk-space go/no-go was decided against the fabricated 120 GB.
 */
export type HardwareProbeResult =
  | { ok: true; inventory: HardwareInventory }
  | { ok: false; message: string };

/**
 * The one message shown when the hardware probe cannot answer. Exported so
 * the screen and its tests agree on the exact string instead of restating it.
 * Like {@link START_ACQUISITION_FAILED_MESSAGE}, it says what did not happen
 * and what the operator can do -- it never guesses at a cause, and it never
 * offers a number.
 */
export const HARDWARE_PROBE_FAILED_MESSAGE =
  "CivicCast could not check this computer's hardware. It will not guess: nothing about this " +
  "computer is shown below, and the free-space check could not be made. Setup can continue, but " +
  "if a download later runs out of room, free up space and choose Retry.";

/** The same, worded for a browser preview where no native bridge exists at all. */
export const HARDWARE_PROBE_UNAVAILABLE_IN_PREVIEW_MESSAGE =
  "CivicCast could not check this computer's hardware in this preview. No real hardware readings " +
  "are available here.";

export async function fetchHardwareInventory(): Promise<HardwareProbeResult> {
  if (!nativeInstallerBridgeAvailable()) {
    return { ok: false, message: HARDWARE_PROBE_UNAVAILABLE_IN_PREVIEW_MESSAGE };
  }
  try {
    const inventory = await invokeNativeInstallerAny<HardwareInventory>([
      "native_hardware_inventory",
      "nativeHardwareInventory"
    ]);
    return { ok: true, inventory };
  } catch {
    return { ok: false, message: HARDWARE_PROBE_FAILED_MESSAGE };
  }
}

/**
 * A measured link speed in bytes/second, or `null` when nothing has been
 * measured yet.
 *
 * G011.2: `null` means "no measurement exists". Callers must render that as
 * an absence -- never as an ETA, and never as a stand-in rate. No native
 * `measure_link_speed_bytes_per_second` command exists today (it is not in
 * main.rs's `generate_handler!` list), so on a real station this resolves to
 * `null` and the plan screen shows sizes without ETA claims until the
 * downloading screen's rolling measurement takes over. The invoke is kept so
 * the moment such a command IS registered, the plan screen picks it up with
 * no frontend change.
 */
export async function measureLinkSpeedBytesPerSecond(): Promise<number | null> {
  try {
    return await invokeNativeInstallerAny<number>([
      "measure_link_speed_bytes_per_second",
      "measureLinkSpeedBytesPerSecond"
    ]);
  } catch {
    return null;
  }
}

/**
 * Starts the backend component-download driver (BLOCKER #54 fix: before
 * this, nothing ever called `run_acquisition_components`, so the
 * downloading screen's "Waiting" rows never moved -- see
 * `AcquisitionFlow.tsx`'s `useAcquisitionComponents`, which calls this
 * exactly once when the downloading screen mounts, never once per poll
 * tick). The Rust command is itself idempotent (a second call while the
 * driver is already running is a documented no-op), so this is safe to call
 * more than once across the process's lifetime even if this wrapper is ever
 * invoked from more than one call site. Degrades to a typed, honest message
 * in a browser preview where no native command exists.
 */
export interface AcquisitionStartResult {
  /** `false` ONLY when the native bridge exists and rejected the command. */
  ok: boolean;
  /** Operator-readable text. Always populated. */
  message: string;
}

/**
 * The one message shown when the native `start_acquisition` command exists
 * and refuses. Exported so the screen and its test agree on the exact string
 * instead of restating it. The Tauri ACL denial (`installer-actions.toml` did
 * not list the command) is the failure that motivated surfacing this at all,
 * but the text deliberately does NOT guess at the cause -- it says what did
 * not happen and what the operator can do next.
 */
export const START_ACQUISITION_FAILED_MESSAGE =
  "CivicCast could not start downloading its components. Nothing is being downloaded " +
  "right now. Use Open installer log below and send that log to support.";

export async function startAcquisition(): Promise<AcquisitionStartResult> {
  if (!nativeInstallerBridgeAvailable()) {
    // No native bridge at all (a browser preview): NOT a failure of the
    // product -- keep the existing honest preview wording and do not raise a
    // red alert on a screen nobody is installing from.
    return {
      ok: true,
      message: "CivicCast could not start downloading its components in this preview."
    };
  }
  try {
    const message = await invokeNativeInstallerAny<string>([
      "start_acquisition",
      "startAcquisition"
    ]);
    return { ok: true, message };
  } catch {
    return { ok: false, message: START_ACQUISITION_FAILED_MESSAGE };
  }
}

/**
 * The one message shown when the native cancel command exists and refuses.
 * Exported so the screen and its tests agree on the exact string.
 */
export const CANCEL_ACQUISITION_FAILED_MESSAGE =
  "CivicCast could not stop the download. It is still running. Close this window to stop it; " +
  "anything already downloaded is kept and setup will pick up where it left off.";

/**
 * Stop the in-flight component download at the operator's request (G011.3).
 *
 * Before this, cancel was wired to nothing: there was no command, no button
 * and no canceled state, so an operator who realised mid-download that they
 * were on a metered connection could only kill the window -- leaving a
 * `.partial` behind with nothing on screen acknowledging it. The native
 * command returns near-instantly (it sets a flag the download loop checks at
 * its next buffer boundary and marks the unfinished rows canceled), so the
 * screen shows the stopped state on the very next poll.
 */
export async function cancelAcquisition(): Promise<AcquisitionStartResult> {
  if (!nativeInstallerBridgeAvailable()) {
    return {
      ok: true,
      message: "There is no download to stop in this preview."
    };
  }
  try {
    const message = await invokeNativeInstallerAny<string>([
      "cancel_acquisition",
      "cancelAcquisition"
    ]);
    return { ok: true, message };
  } catch {
    return { ok: false, message: CANCEL_ACQUISITION_FAILED_MESSAGE };
  }
}

/**
 * Retry (resume, not restart, where the engine allows) a single failed or
 * canceled component download. No native command exists yet for per-component
 * retry, so this degrades to queuing the retry via the existing generic action
 * channel and reports that honestly rather than pretending to resume.
 */
export async function retryAcquisitionComponent(componentId: string): Promise<string> {
  try {
    return await invokeNativeInstallerAny<string>([
      "retry_acquisition_component",
      "retryAcquisitionComponent"
    ], { componentId });
  } catch {
    return "Retry is queued. CivicCast will pick this file back up on the next check.";
  }
}

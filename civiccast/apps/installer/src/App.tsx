// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LOCAL_OPERATOR_CONSOLE_URL,
  loadInstallerProgress,
  loadInstallerState,
  openInstallerLog,
  openOperatorConsole,
  runInstallerAction
} from "./api";
import {
  acquisitionFlowAlreadyComplete,
  AcquisitionFlow,
  clearAcquisitionFlowComplete
} from "./AcquisitionFlow";
import { isActivationKey, shouldActivateWslShortcut, shouldArmWslShortcut } from "./keyboard-activation";
import { firstActionableLane, markWindowsBootstrapResultPending } from "./installer-transition";
import {
  installerActivityElapsedSeconds,
  isRuntimeBootstrapProgress,
  isWindowsBootstrapProgress,
  windowsBootstrapProgressIsIndeterminate
} from "./progress-visual";
import type { InstallerLane, InstallerProgress, InstallerState, LaneStatus } from "./types";
import { canRepairLane, isWindowsPlatform, isWslBootstrapLane } from "./wsl-affordances";
import "./styles.css";

const DEFAULT_OPERATOR_CONSOLE_URL = LOCAL_OPERATOR_CONSOLE_URL;
const SETUP_PHASES = [
  "Setting up CivicCast",
  "Preparing video tools",
  "Preparing local storage",
  "Generating local secrets",
  "Starting CivicCast",
  "Opening the dashboard"
];

const PHASE_BY_LANE_ID: Record<string, string> = {
  captions: "Preparing video tools",
  models: "Preparing video tools",
  platform: "Setting up CivicCast",
  runtime: "Starting CivicCast",
  storage: "Preparing local storage",
  wsl2: "Setting up CivicCast"
};

const stateLabels: Record<LaneStatus, string> = {
  loading: "Loading",
  success: "Ready",
  empty: "Needs input",
  error: "Error",
  partial: "Partial",
  blocked: "Needs setup",
  progress: "In progress",
  cancelled: "Cancelled",
  credential_gated: "Credential gated",
  hardware_required: "Hardware required",
  unavailable: "Not available"
};

function elapsedLabel(seconds: number) {
  if (seconds < 60) {
    return `${seconds} seconds elapsed`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes} minutes ${remainder} seconds elapsed` : `${minutes} minutes elapsed`;
}

function isActivityPubLane(lane: InstallerLane) {
  return lane.id === "activitypub";
}

function primaryActionLabel(installer: InstallerState, lane: InstallerLane, rebootRequired = false) {
  if (installer.ready) {
    return "Open operator console";
  }
  if (lane.status === "error") {
    return "Retry";
  }
  if (lane.status === "cancelled") {
    return lane.id === "models" ? "Set up models" : "Retry";
  }
  if (isWslBootstrapLane(installer, lane)) {
    return rebootRequired ? "Resume after reboot" : "Set up Windows helper";
  }
  if (lane.id === "storage" && !lane.ready) {
    return "Prepare storage";
  }
  if (lane.ready) {
    return "Next step";
  }
  return "Continue";
}

function primaryActionDisabled(installer: InstallerState, lane: InstallerLane) {
  if (isWslBootstrapLane(installer, lane) || lane.ready || canRetryLane(lane)) {
    return false;
  }
  return ["blocked", "credential_gated", "hardware_required"].includes(lane.status);
}

function canRetryLane(lane: InstallerLane) {
  return lane.status === "error" || lane.status === "cancelled";
}

function showsPrimaryAction(installer: InstallerState, lane: InstallerLane) {
  if (installer.ready || lane.ready || isWslBootstrapLane(installer, lane) || canRetryLane(lane)) {
    return true;
  }
  if (lane.id === "storage") {
    return true;
  }
  // "unavailable" belongs in this list: the lane's own remedy is stated in its
  // next_step, and every generic primary action here routes into the runtime
  // bootstrap, which cannot supply an optional capability the install does not
  // ship. A button that cannot deliver is worse than no button.
  return !["loading", "progress", "blocked", "credential_gated", "hardware_required", "unavailable"].includes(
    lane.status
  );
}

function PrimaryActionControl({
  installer,
  lane,
  consoleHref,
  onContinue,
  onRetry,
  onOpenConsole,
  className = "",
  buttonRef,
  rebootRequired = false
}: {
  installer: InstallerState;
  lane: InstallerLane;
  consoleHref: string;
  onContinue: (lane: InstallerLane) => void;
  onRetry: (lane: InstallerLane) => void;
  onOpenConsole: () => void;
  className?: string;
  buttonRef?: React.Ref<HTMLButtonElement>;
  rebootRequired?: boolean;
}) {
  if (!showsPrimaryAction(installer, lane)) {
    return null;
  }
  const label = primaryActionLabel(installer, lane, rebootRequired);
  if (installer.ready) {
    return (
      <button ref={buttonRef} className={className} onClick={onOpenConsole} type="button" title={consoleHref}>
        {label}
      </button>
    );
  }
  if (canRetryLane(lane)) {
    return (
      <button ref={buttonRef} type="button" className={className} onClick={() => onRetry(lane)}>
        {label}
      </button>
    );
  }
  return (
    <button
      ref={buttonRef}
      type="button"
      className={className}
      onClick={() => onContinue(lane)}
      disabled={primaryActionDisabled(installer, lane)}
    >
      {label}
    </button>
  );
}

function nextLaneId(installer: InstallerState, currentLaneId: string) {
  const currentIndex = installer.lanes.findIndex((lane) => lane.id === currentLaneId);
  const laterLanes = installer.lanes.slice(Math.max(currentIndex, 0) + 1);
  return (
    laterLanes.find((lane) => !lane.ready)?.id ??
    laterLanes[0]?.id ??
    installer.lanes[0]?.id ??
    currentLaneId
  );
}

function ActivityPubSetupPanel({ lane }: { lane: InstallerLane }) {
  return (
    <div className="activitypub-setup" aria-label="ActivityPub setup">
      <strong>Advanced optional setup</strong>
      <p>
        ActivityPub is off by default and is not required to finish installing CivicCast. A technical administrator
        can configure federation after the dashboard is running if this station intentionally opts in.
      </p>
      <div className="setup-grid">
        <div>
          <span>1</span>
          <strong>Decide whether to opt in</strong>
          <p>Keep federation off unless the station has an approved public-federation policy.</p>
        </div>
        <div>
          <span>2</span>
          <strong>Use the administrator guide</strong>
          <p>Have a technical administrator configure station identity, local key material, and federation policy.</p>
        </div>
        <div>
          <span>3</span>
          <strong>Prove before publishing</strong>
          <p>Run the documented federation proof before exposing an actor or accepting followers.</p>
        </div>
      </div>
      <a
        href="https://github.com/scottconverse/civiccast-native/blob/main/docs/ops/activitypub-federation.md"
        target="_blank"
        rel="noreferrer"
      >
        ActivityPub federation guide
      </a>
      <p className="next">Next: {lane.nextStep}</p>
    </div>
  );
}

function SetupPhaseStrip({ activeLaneId }: { activeLaneId: string }) {
  const activePhase = PHASE_BY_LANE_ID[activeLaneId] ?? "";
  return (
    <section className="phase-strip" aria-label="Installer progress overview">
      {SETUP_PHASES.map((phase) => (
        <div className={phase === activePhase ? "phase-active" : ""} key={phase}>
          {phase}
        </div>
      ))}
    </section>
  );
}

function ResumePanel({
  progress,
  onReset,
  bootstrapActive
}: {
  progress: InstallerProgress | null;
  onReset: () => void;
  bootstrapActive: boolean;
}) {
  if (!progress) {
    return null;
  }
  return (
    <section className="resume-panel" aria-label="Resume installer state">
      <div>
        <strong>{progress.reboot_required ? "Resume after reboot" : "Installer progress saved"}</strong>
        <p>{progress.message}</p>
      </div>
      {bootstrapActive ? null : (
        <button type="button" onClick={onReset}>
          Reset progress
        </button>
      )}
    </section>
  );
}

function WindowsSetupActivity({ progress }: { progress: InstallerProgress | null }) {
  const active = isWindowsBootstrapProgress(progress);
  const [nowUnix, setNowUnix] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = window.setInterval(() => setNowUnix(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  if (!active || !progress) {
    return null;
  }
  const current = progress.activity_current;
  const total = progress.activity_total;
  const hasStepCount = Boolean(current && total && current <= total);
  const elapsed = installerActivityElapsedSeconds(progress, nowUnix);
  return (
    <section
      className="windows-setup-activity"
      role="status"
      aria-label="Windows setup activity"
      aria-live="polite"
    >
      <strong>{progress.message}</strong>
      <div className="activity-facts">
        <span>{hasStepCount ? `Step ${current} of ${total}` : "Windows setup is active"}</span>
        <span>{elapsedLabel(elapsed)}</span>
      </div>
      {windowsBootstrapProgressIsIndeterminate(progress) ? <progress /> : <progress max={total} value={current} />}
      <p>
        Keep CivicCast Installer open. This status updates every few seconds. Restart only when this screen explicitly
        says a restart is required.
      </p>
    </section>
  );
}

function RuntimeSetupActivity({ progress }: { progress: InstallerProgress | null }) {
  const active = isRuntimeBootstrapProgress(progress);
  const [nowUnix, setNowUnix] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = window.setInterval(() => setNowUnix(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  if (!active || !progress) {
    return null;
  }
  const elapsed = installerActivityElapsedSeconds(progress, nowUnix);
  return (
    <section
      className="windows-setup-activity"
      role="status"
      aria-label="CivicCast setup activity"
      aria-live="polite"
    >
      <strong>{progress.message}</strong>
      <div className="activity-facts">
        <span>{progress.activity_phase || "CivicCast setup is active"}</span>
        <span>{elapsedLabel(elapsed)}</span>
      </div>
      <progress />
      <p>
        Keep CivicCast Installer open. The timer and activity bar remain live while bundled components are prepared.
      </p>
    </section>
  );
}

function App() {
  const searchParams = new URLSearchParams(window.location.search);
  const requestedState = searchParams.get("state");
  // The download-experience screens (machine check, plan, downloading) run
  // once before the existing install-lane wizard on a fresh install
  // (download-ux-spec.md). Coordinator-ruled default-on: the acquisition
  // engine's progress now reaches the frontend through the polled
  // installer-state JSON's `acquisition` field (component_acquisition.rs's
  // ProgressObserver, written by main.rs's acquisition driver), so this no
  // longer needs an opt-in flag to be real. `?downloadExperience=0` remains
  // as an escape hatch (used by most of e2e/installer.spec.ts, whose ~21
  // specs test the existing lane wizard's own behavior and intentionally
  // bypass this flow to keep asserting on it directly).
  const downloadExperienceDisabled = searchParams.get("downloadExperience") === "0";
  const [installer, setInstaller] = useState<InstallerState | null>(null);
  const [activeLaneId, setActiveLaneId] = useState("");
  // Set only when the OPERATOR clicks a step in the wizard rail, cleared when
  // they take an action that legitimately advances the flow. The 2-second
  // background poll below used to call setActiveLaneId unconditionally, so a
  // step the operator opened to read was yanked away within two seconds --
  // every two seconds, for as long as setup ran. Their choice outranks the
  // poll's opinion; the poll's opinion still applies when they have not made
  // one.
  const operatorPickedLaneId = useRef<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [operatorConsoleUrl, setOperatorConsoleUrl] = useState(DEFAULT_OPERATOR_CONSOLE_URL);
  const [progress, setProgress] = useState<InstallerProgress | null>(null);
  const [showAcquisitionFlow, setShowAcquisitionFlow] = useState(
    () => !downloadExperienceDisabled && !requestedState && !acquisitionFlowAlreadyComplete()
  );
  const runtimeAutoStarted = useRef(false);
  const runtimeSetupWasObserved = useRef(false);
  const operatorConsoleAutoOpened = useRef(false);
  const primaryActionRef = useRef<HTMLButtonElement | null>(null);
  const autoFocusedLaneId = useRef<string | null>(null);
  const wslActionInFlight = useRef(false);

  useEffect(() => {
    let ignore = false;
    setStatusMessage("");
    const loadState = async () => {
      try {
        const savedProgress = await loadInstallerProgress();
        const loaded = await loadInstallerState(requestedState, savedProgress);
        if (ignore) {
          return;
        }
        setInstaller(loaded);
        setProgress(savedProgress);
        const savedLane = loaded.lanes.find((lane) => lane.id === savedProgress?.current_lane_id);
        setActiveLaneId(
          savedLane && !savedLane.ready ? savedLane.id : firstActionableLane(loaded)?.id ?? loaded.lanes[0]?.id ?? ""
        );
        setOperatorConsoleUrl(loaded.operatorConsoleUrl ?? DEFAULT_OPERATOR_CONSOLE_URL);
      } catch (error) {
        if (ignore) {
          return;
        }
        setInstaller({
          ready: false,
          platform: "windows-wsl2",
          lanes: [
            {
              id: "installer",
              label: "Installer state",
              status: "error",
              ready: false,
              detail: error instanceof Error ? error.message : String(error),
              nextStep: "Close and reopen the installer, then retry the proof."
            }
          ]
        });
      }
    };
    void loadState();
    return () => {
      ignore = true;
    };
  }, [requestedState]);

  useEffect(() => {
    if (!installer || requestedState || runtimeAutoStarted.current) {
      return;
    }
    const runtimeLane = installer.lanes.find((lane) => lane.id === "runtime");
    const platformIsReady = installer.lanes.some(
      (lane) => ["platform", "wsl2"].includes(lane.id) && lane.ready
    );
    if (!platformIsReady || !runtimeLane || runtimeLane.ready || runtimeLane.status !== "partial") {
      return;
    }

    let ignore = false;
    runtimeAutoStarted.current = true;
    setStatusMessage("CivicCast is finishing setup. The dashboard will open when everything is ready.");
    // Patch the runtime lane's own card in this same update so it can never render a
    // stale error/detail underneath the optimistic banner above (UX-2 / G-9a).
    setInstaller({
      ...installer,
      lanes: installer.lanes.map((lane) =>
        lane.id === "runtime"
          ? {
              ...lane,
              status: "progress",
              detail: "Retrying automatically…",
              nextStep: "Keep this window open while CivicCast retries this step."
            }
          : lane
      )
    });
    const startRuntime = async () => {
      try {
        const outcome = await runInstallerAction("runtime", "continue");
        if (ignore) {
          return;
        }
        setStatusMessage(outcome.message);
        if (outcome.operatorConsoleUrl) {
          setOperatorConsoleUrl(outcome.operatorConsoleUrl);
        }
        const savedProgress = await loadInstallerProgress();
        const refreshed = await loadInstallerState(requestedState, savedProgress);
        if (ignore) {
          return;
        }
        setProgress(savedProgress);
        setInstaller(refreshed);
        // An action advances the flow, so the operator's sticky step pick
        // is spent here rather than pinning the wizard for the rest of
        // the install.
        operatorPickedLaneId.current = null;
        setActiveLaneId(firstActionableLane(refreshed)?.id ?? refreshed.lanes[0]?.id ?? "runtime");
      } catch (error) {
        if (ignore) {
          return;
        }
        setStatusMessage(
          `CivicCast setup did not finish: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    };
    void startRuntime();
    return () => {
      ignore = true;
    };
  }, [installer, requestedState]);

  useEffect(() => {
    if (requestedState || progress?.current_lane_id !== "runtime" || progress.status !== "running") {
      return;
    }
    const refreshRuntimeProgress = async () => {
      const savedProgress = await loadInstallerProgress();
      const refreshed = await loadInstallerState(requestedState, savedProgress);
      setProgress(savedProgress);
      setInstaller(refreshed);
      // An action advances the flow, so the operator's sticky step pick
      // is spent here rather than pinning the wizard for the rest of
      // the install.
      operatorPickedLaneId.current = null;
      setActiveLaneId(firstActionableLane(refreshed)?.id ?? refreshed.lanes[0]?.id ?? "runtime");
      if (refreshed.operatorConsoleUrl) {
        setOperatorConsoleUrl(refreshed.operatorConsoleUrl);
      }
    };
    const timer = window.setInterval(() => {
      void refreshRuntimeProgress();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [progress, requestedState]);

  useEffect(() => {
    if (isRuntimeBootstrapProgress(progress)) {
      runtimeSetupWasObserved.current = true;
    }
    if (
      !installer?.ready ||
      operatorConsoleAutoOpened.current ||
      (!runtimeAutoStarted.current && !runtimeSetupWasObserved.current)
    ) {
      return;
    }
    operatorConsoleAutoOpened.current = true;
    const consoleHref = installer.operatorConsoleUrl ?? operatorConsoleUrl;
    const openReadyConsole = async () => {
      try {
        setStatusMessage(await openOperatorConsole(consoleHref, false));
      } catch (error) {
        setStatusMessage(
          `CivicCast is ready. Choose Open operator console to continue: ${
            error instanceof Error ? error.message : String(error)
          }`
        );
      }
    };
    void openReadyConsole();
  }, [installer, operatorConsoleUrl, progress]);

  useEffect(() => {
    if (requestedState || !installer) {
      return;
    }
    const refreshSavedProgress = async () => {
      const savedProgress = await loadInstallerProgress();
      if (!savedProgress) {
        return;
      }
      const refreshed = await loadInstallerState(requestedState, savedProgress);
      setProgress(savedProgress);
      setInstaller(refreshed);
      const picked = operatorPickedLaneId.current;
      const pickedStillExists = picked ? refreshed.lanes.some((lane) => lane.id === picked) : false;
      setActiveLaneId(
        pickedStillExists && picked
          ? picked
          : firstActionableLane(refreshed)?.id ?? refreshed.lanes[0]?.id ?? activeLaneId
      );
      if (refreshed.operatorConsoleUrl) {
        setOperatorConsoleUrl(refreshed.operatorConsoleUrl);
      }
    };
    const timer = window.setInterval(() => {
      void refreshSavedProgress();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeLaneId, installer, requestedState]);

  useEffect(() => {
    if (!installer) {
      return;
    }
    const activeLane = installer.lanes.find((lane) => lane.id === activeLaneId) ?? installer.lanes[0];
    if (!activeLane || !isWslBootstrapLane(installer, activeLane)) {
      autoFocusedLaneId.current = null;
      return;
    }
    if (autoFocusedLaneId.current === activeLane.id) {
      return;
    }
    primaryActionRef.current?.focus();
    autoFocusedLaneId.current = activeLane.id;
  }, [activeLaneId, installer]);

  const refreshProgress = async () => {
    const savedProgress = await loadInstallerProgress();
    setProgress(savedProgress);
    return savedProgress;
  };

  const retryLane = async (lane: InstallerLane) => {
    setStatusMessage(`Retrying ${lane.label}. CivicCast is refreshing this proof step.`);
    if (requestedState) {
      return;
    }
    const outcome = await runInstallerAction(lane.id, "retry");
    setStatusMessage(outcome.message);
    if (outcome.operatorConsoleUrl) {
      setOperatorConsoleUrl(outcome.operatorConsoleUrl);
    }
    const savedProgress = await refreshProgress();
    const refreshed = await loadInstallerState(requestedState, savedProgress);
    setInstaller(refreshed);
    // An action advances the flow, so the operator's sticky step pick
    // is spent here rather than pinning the wizard for the rest of
    // the install.
    operatorPickedLaneId.current = null;
    setActiveLaneId(firstActionableLane(refreshed)?.id ?? lane.id);
  };

  const cancelLane = async (lane: InstallerLane) => {
    if (requestedState) {
      setStatusMessage(`${lane.label} was paused. Resume here before the first public meeting.`);
      return;
    }
    const outcome = await runInstallerAction(lane.id, "cancel");
    setStatusMessage(`${lane.label} was paused. ${outcome.message}`);
    if (outcome.operatorConsoleUrl) {
      setOperatorConsoleUrl(outcome.operatorConsoleUrl);
    }
    const savedProgress = await refreshProgress();
    const refreshed = await loadInstallerState(requestedState, savedProgress);
    setInstaller(refreshed);
    // An action advances the flow, so the operator's sticky step pick
    // is spent here rather than pinning the wizard for the rest of
    // the install.
    operatorPickedLaneId.current = null;
    setActiveLaneId(firstActionableLane(refreshed)?.id ?? lane.id);
  };

  const continueLane = async (lane: InstallerLane) => {
    if (!installer) {
      return;
    }
    if (lane.ready && !installer.ready) {
      setActiveLaneId(nextLaneId(installer, lane.id));
      setStatusMessage(`${lane.label} is complete. Continue with the next installer step.`);
      return;
    }
    if (requestedState) {
      setStatusMessage(`${lane.label} is queued for the local setup helper.`);
      return;
    }
    const startsWindowsBootstrap = isWslBootstrapLane(installer, lane);
    if (startsWindowsBootstrap) {
      if (wslActionInFlight.current) {
        return;
      }
      wslActionInFlight.current = true;
      setStatusMessage(
        // rc17 D5: never promise a single approval. A required restart re-runs
        // this same elevated step and shows the Windows prompt again -- saying
        // "once" here reads as a broken second prompt when that happens.
        "Asking Windows for permission to set up the helper CivicCast needs. Approve the Windows security prompt. This screen will then show live activity.",
      );
      setInstaller({
        ...installer,
        lanes: installer.lanes.map((candidate) =>
          candidate.id === lane.id
            ? {
                ...candidate,
                status: "progress",
                detail: "Waiting for Windows approval. CivicCast will show the active setup phase here next.",
                nextStep: "Approve the Windows security prompt, then keep this installer open."
              }
            : candidate
        )
      });
    }
    try {
      const outcome = await runInstallerAction(lane.id, "continue");
      setStatusMessage(outcome.message);
      if (startsWindowsBootstrap) {
        setInstaller(markWindowsBootstrapResultPending(installer, lane.id));
      }
      if (outcome.operatorConsoleUrl) {
        setOperatorConsoleUrl(outcome.operatorConsoleUrl);
      }
      const savedProgress = await refreshProgress();
      const refreshed = await loadInstallerState(requestedState, savedProgress);
      setInstaller(refreshed);
      // An action advances the flow, so the operator's sticky step pick
      // is spent here rather than pinning the wizard for the rest of
      // the install.
      operatorPickedLaneId.current = null;
      setActiveLaneId(firstActionableLane(refreshed)?.id ?? lane.id);
    } finally {
      if (startsWindowsBootstrap) {
        wslActionInFlight.current = false;
      }
    }
  };

  useEffect(() => {
    // See shouldArmWslShortcut: never arm the old wizard's global Enter/Space
    // shortcut while the download-experience screens are showing (this effect
    // runs before the showAcquisitionFlow early return below).
    const lane = installer?.lanes.find((candidate) => candidate.id === activeLaneId) ?? installer?.lanes[0];
    if (
      !installer ||
      !lane ||
      !shouldArmWslShortcut({
        showAcquisitionFlow,
        hasInstaller: Boolean(installer),
        requestedState: Boolean(requestedState),
        laneIsWslBootstrap: isWslBootstrapLane(installer, lane),
      })
    ) {
      return;
    }

    const activateWslAction = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat || !isActivationKey(event)) {
        return;
      }
      const target = event.target instanceof HTMLElement ? event.target : null;
      const tagName = target?.tagName.toLowerCase();
      if (target?.isContentEditable || tagName === "input" || tagName === "select" || tagName === "textarea") {
        return;
      }
      if (!shouldActivateWslShortcut(document.activeElement, primaryActionRef.current)) {
        return;
      }
      event.preventDefault();
      void continueLane(lane);
    };

    window.addEventListener("keydown", activateWslAction, true);
    window.addEventListener("keyup", activateWslAction, true);
    return () => {
      window.removeEventListener("keydown", activateWslAction, true);
      window.removeEventListener("keyup", activateWslAction, true);
    };
  }, [activeLaneId, installer, requestedState, showAcquisitionFlow]);

  const openConsole = async () => {
    const consoleHref = installer?.operatorConsoleUrl ?? operatorConsoleUrl;
    const message = await openOperatorConsole(consoleHref);
    setStatusMessage(message);
  };

  const openLog = async () => {
    try {
      setStatusMessage(await openInstallerLog());
    } catch (error) {
      setStatusMessage(
        `CivicCast could not open the installer log: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  };

  const repairLane = async (lane: InstallerLane) => {
    const outcome = await runInstallerAction(lane.id, "repair");
    setStatusMessage(outcome.message);
    const savedProgress = await refreshProgress();
    setInstaller(await loadInstallerState(requestedState, savedProgress));
  };

  // The one reachable way back into the first-run download experience once
  // its localStorage latch has been set (see clearAcquisitionFlowComplete's
  // doc comment for the four ways a station ends up latched with no packs on
  // disk). Safe to run on a healthy station: every component the engine
  // handles short-circuits on an already-verified copy -- `run_pack_item`
  // re-verifies the download destination AND the installer-staged copy
  // against the same signed manifest before touching the network, and
  // `ensure_component_available` does the same for the pinned caption and
  // model files -- so a re-entry on a fully-provisioned station downloads
  // nothing and simply reports "Found locally -- verified".
  const openAcquisitionFlow = () => {
    clearAcquisitionFlowComplete();
    setStatusMessage("");
    setShowAcquisitionFlow(true);
  };

  const resetInstaller = async () => {
    const outcome = await runInstallerAction(activeLaneId || "installer", "reset");
    setStatusMessage(outcome.message);
    await refreshProgress();
  };

  const uninstallInstaller = async () => {
    const outcome = await runInstallerAction(activeLaneId || "installer", "uninstall");
    setStatusMessage(outcome.message);
    await refreshProgress();
  };

  if (!installer) {
    return (
      <main className="shell" aria-busy="true">
        <h1>CivicCast Installer</h1>
        <p className="lead">Checking Windows settings. This can take up to a minute on a new computer.</p>
        <div className="initial-activity" role="status" aria-label="Checking Windows settings">
          <progress />
          <span>CivicCast is working. This screen will update when the check finishes.</span>
        </div>
      </main>
    );
  }

  if (showAcquisitionFlow) {
    return <AcquisitionFlow onComplete={() => setShowAcquisitionFlow(false)} />;
  }

  const activeLane = installer.lanes.find((lane) => lane.id === activeLaneId) ?? installer.lanes[0];
  const activeIndex = installer.lanes.findIndex((lane) => lane.id === activeLane.id);
  const completedCount = installer.lanes.filter((lane) => lane.ready).length;
  const consoleHref = installer.operatorConsoleUrl ?? operatorConsoleUrl;
  const windowsBootstrapActive =
    isWindowsBootstrapProgress(progress) ||
    (["wsl2", "platform"].includes(activeLane.id) && activeLane.status === "progress");
  const runtimeBootstrapActive = isRuntimeBootstrapProgress(progress);
  const installerActivityActive = windowsBootstrapActive || runtimeBootstrapActive;
  const activityCurrent = progress?.activity_current;
  const activityTotal = progress?.activity_total;
  const hasActivitySteps = Boolean(
    windowsBootstrapActive && activityCurrent && activityTotal && activityCurrent <= activityTotal
  );

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>CivicCast Installer</h1>
          <p className="lead">
            {installer.ready
              ? "CivicCast is installed and ready. Open the operator console to continue."
              : "Download, install, create the first admin, then open the dashboard without terminal commands."}
          </p>
          <a
            href="https://github.com/scottconverse/civiccast-native/issues/new?template=bug-report.yml&title=%5Bbeta%5D%20"
            target="_blank"
            rel="noreferrer"
          >
            Report a beta issue
          </a>
          <p className="privacy-note">
            Do not include passwords, recovery codes, staff tokens, or private meeting material.
          </p>
        </div>
        <div className="handoff">
          <strong className={installer.ready ? "ready-pill" : "blocked-pill"}>
            {installer.ready ? "Ready" : "Not ready"}
          </strong>
        </div>
      </header>

      <section className="platform-band" aria-label="Selected platform">
        <span>Platform</span>
        <strong>{installer.platform}</strong>
      </section>

      <SetupPhaseStrip activeLaneId={activeLane.id} />
      <ResumePanel progress={progress} onReset={resetInstaller} bootstrapActive={installerActivityActive} />
      <WindowsSetupActivity progress={progress} />
      <RuntimeSetupActivity progress={progress} />

      {statusMessage ? (
        <p className="status-message" role="status" aria-live="polite">
          {statusMessage}
        </p>
      ) : null}

      <section className="wizard" aria-label="Installer wizard">
        <nav className="steps" aria-label="Installer wizard steps">
          <div className="progress">
            <span>
              {hasActivitySteps
                ? `Windows setup: step ${activityCurrent} of ${activityTotal}`
                : installerActivityActive
                  ? runtimeBootstrapActive
                    ? "CivicCast setup is active"
                    : "Windows setup is active"
                  : `${completedCount} of ${installer.lanes.length} ready`}
            </span>
            {installerActivityActive ? (
              <progress />
            ) : (
              <progress max={installer.lanes.length} value={completedCount} />
            )}
          </div>
          {installer.lanes.map((lane, index) => (
            <button
              aria-current={lane.id === activeLane.id ? "step" : undefined}
              className={`step step-${lane.status}`}
              key={lane.id}
              onClick={() => {
                operatorPickedLaneId.current = lane.id;
                setActiveLaneId(lane.id);
              }}
              type="button"
            >
              <span className="step-number">{index + 1}</span>
              <span>
                <strong>{lane.label}</strong>
                <em>{stateLabels[lane.status]}</em>
              </span>
            </button>
          ))}
        </nav>

        <article className={`step-detail lane-${activeLane.status}`}>
          <div className="lane-head">
            <span>Step {activeIndex + 1}</span>
            <strong>{stateLabels[activeLane.status]}</strong>
          </div>
          <h2>{activeLane.label}</h2>
          {activeLane.status !== "progress" ? (
            <PrimaryActionControl
              installer={installer}
              lane={activeLane}
              consoleHref={consoleHref}
              onContinue={continueLane}
              onRetry={retryLane}
              onOpenConsole={openConsole}
              className="detail-primary-action"
              buttonRef={primaryActionRef}
              rebootRequired={Boolean(progress?.reboot_required)}
            />
          ) : null}
          <p>{activeLane.detail}</p>
          {isActivityPubLane(activeLane) ? (
            <ActivityPubSetupPanel lane={activeLane} />
          ) : (
            <p className="next">Next: {activeLane.nextStep}</p>
          )}
          <div className="actions">
            {/* The installer log is a Windows artifact either way -- main.rs's
                open_installer_log shells notepad.exe on the newest log the
                engine wrote, and a native station produces those logs too.
                Gating it on "windows-wsl2" alone would take support's only
                self-serve diagnostic away from the native product. */}
            {activeLane.status === "error" && isWindowsPlatform(installer) ? (
              <button type="button" className="secondary-action" onClick={openLog}>
                Open installer log
              </button>
            ) : null}
            {activeLane.status === "progress" && !installerActivityActive ? (
              <button type="button" onClick={() => cancelLane(activeLane)}>
                Cancel
              </button>
            ) : null}
            {installerActivityActive ? null : (
              <details className="more-actions">
                <summary>More options</summary>
                <div>
                  {canRepairLane(installer, activeLane) ? (
                    <button type="button" className="secondary-action" onClick={() => repairLane(activeLane)}>
                      Repair this step
                    </button>
                  ) : null}
                  {/* The AI models and caption engine are downloaded by the
                      first-run download screens, not by Setup itself, and
                      those screens show once per Windows account and then
                      latch themselves off forever. Until this control
                      existed, a station that reached "Ready" without them --
                      a silent (/S) install, which never launches this GUI at
                      all, or any reinstall on an account that had already
                      been through the flow -- had NO surface anywhere that
                      could start the download. This is that surface. */}
                  <button type="button" className="secondary-action" onClick={openAcquisitionFlow}>
                    Download AI models and captions
                  </button>
                  <button type="button" className="secondary-action" onClick={uninstallInstaller}>
                    Show uninstall instructions
                  </button>
                </div>
              </details>
            )}
          </div>
        </article>
      </section>

      {/* F-23 fix: the repo ships LICENSE, LICENSE-CODE, LICENSE-DOCS, and
          LEGAL-NOTICES.md, but the installer itself surfaced none of it --
          an operator had no way to reach a license or attribution notice
          from inside the wizard. A dedicated wizard page (or bundling the
          license files into the installer) was considered and rejected:
          this bootstrap installer is deliberately kept under a hard 300 MB
          size gate (scripts/build_native_bootstrap.py's
          validate_native_bootstrap_config, which pins bundle.resources to
          exactly the VC++ redistributable) precisely so it never embeds
          more than the small prerequisite it needs -- adding license text
          as a bundled resource would violate that gate for a few KB of
          text NSIS's own directory page can't usefully render anyway. The
          smallest honest fix that is still reachable: state the license
          summary in plain language, in the wizard shell every install
          path reaches, with a link to the full, published text (the same
          external-link pattern this file already uses for the ActivityPub
          federation guide above). */}
      <footer className="license-footer">
        <p>
          CivicCast is open source: program code under the Apache License 2.0, documentation under CC BY 4.0. Full
          license texts and legal notices:{" "}
          <a
            href="https://github.com/scottconverse/civiccast-native/blob/main/LEGAL-NOTICES.md"
            target="_blank"
            rel="noreferrer"
          >
            LEGAL-NOTICES.md
          </a>
          .
        </p>
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

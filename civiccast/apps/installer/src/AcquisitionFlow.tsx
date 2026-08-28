// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// The three new download-experience screens (download-ux-spec.md): machine
// inventory + recommendation, the download plan, and download progress.
// Rendered by App.tsx BEFORE the existing install-lane wizard, once per
// install, and skipped entirely for the `?state=` fixture path (those
// fixtures render specific existing lanes directly and must keep working
// unmodified) and for any run where the flow has already completed.

import { useEffect, useMemo, useRef, useState } from "react";

import {
  cancelAcquisition,
  fetchHardwareInventory,
  loadInstallerProgress,
  measureLinkSpeedBytesPerSecond,
  openInstallerLog,
  retryAcquisitionComponent,
  startAcquisition
} from "./api";
import {
  acquisitionRowIsActive,
  appendProgressSample,
  captionEngineDecision,
  defaultSelectedComponentIds,
  diskSpaceCheck,
  downloadTotalDenominator,
  emaBytesPerSecond,
  ETA_NOT_YET_MEASURED,
  etaSeconds,
  formatBytes,
  formatEta,
  gpuAccelerationDecision,
  gpuAccelerationExplanation,
  isStalled,
  largeCaptionEngineExplanation,
  noBytesMovedYet,
  planTotals,
  pollIntervalMs,
  presentAcquisitionError,
  recommendationSentence,
  UNEXPLAINED_STOP,
  type DownloadTotalDenominator,
  type ProgressSample
} from "./acquisition-progress";
import {
  catalogComponent,
  catalogComponentForWireId,
  COMPONENT_CATALOG,
  type CatalogComponent,
  type ComponentId
} from "./components-catalog";
import type { AcquisitionComponentProgress, HardwareGpu, HardwareInventory } from "./types";

const ACQUISITION_DONE_KEY = "civiccast.acquisitionFlowComplete";

export function acquisitionFlowAlreadyComplete(): boolean {
  try {
    return window.localStorage.getItem(ACQUISITION_DONE_KEY) === "1";
  } catch {
    return false;
  }
}

function markAcquisitionFlowComplete() {
  try {
    window.localStorage.setItem(ACQUISITION_DONE_KEY, "1");
  } catch {
    // Best-effort only; worst case the flow is shown again next launch.
  }
}

/**
 * Drop the "this station has already been through the download flow" latch so
 * the next render of App can enter it again.
 *
 * Why this exists at all: [`acquisitionFlowAlreadyComplete`] is the ONLY gate
 * on the first-run download experience, it lives in the WebView's
 * localStorage, and until now NOTHING in the product could clear it. That is
 * a one-way door, and it strands a station in a state where the component
 * download engine (`main.rs`'s `start_acquisition`, the only caller of
 * `run_production_acquisition`, which is in turn the only writer of
 * `%PROGRAMDATA%\CivicCast\packs\local-ai-model` and `packs\captions-floor`)
 * can never be reached again:
 *
 *   * the latch survives uninstall -- Tauri's NSIS uninstaller only removes
 *     `$LOCALAPPDATA\org.civiccast.native` when the operator ticks the
 *     "Delete the installer's saved settings for this Windows account" box
 *     (see `nsis-lang-native-english.nsh`'s `deleteAppData`), and a silent
 *     uninstall never shows that box at all -- so a REINSTALL on the same
 *     Windows account starts with the flow already suppressed and no packs on
 *     disk;
 *   * "Reset progress" does not touch it (`reset_local_installer_state`
 *     deletes installer-state files, which live somewhere else entirely);
 *   * the wizard behind the flow reports "Ready" purely from a `/health`
 *     probe (`main.rs`'s `launch_startup_native_status_if_ready`), so it
 *     cannot notice, let alone offer to fix, a station with no models.
 *
 * Exported rather than inlined so the one control that calls it (App.tsx's
 * "Download AI models and captions") shares the SAME key with
 * `markAcquisitionFlowComplete` and the two can never drift.
 */
export function clearAcquisitionFlowComplete() {
  try {
    window.localStorage.removeItem(ACQUISITION_DONE_KEY);
  } catch {
    // Best-effort only, exactly like the setter above. The caller re-enters
    // the flow either way; the worst case is that the flow is suppressed
    // again on the NEXT launch, not that this one fails.
  }
}

// ---------------------------------------------------------------------------
// Screen 1: "Checking this computer"
// ---------------------------------------------------------------------------

/**
 * The one string this screen ever prints for a value the probe could not
 * obtain. Never a zero, never a dash that could be mistaken for a reading.
 */
const UNAVAILABLE = "Unavailable";

/**
 * F-05 (newcomer walkthrough): this screen once showed "NVIDIA GeForce RTX
 * 5070 Ti (16 GB)" listed three times on a machine with no such card.
 * `collect_gpus()` (hardware_inventory.rs) pushes one `GpuFacts` per DXGI
 * adapter `EnumAdapters1` hands it, with no adapter-identity check -- a
 * virtualized/projected adapter (GPU-PV, the mechanism Windows Sandbox and
 * similar hosts use to project a host GPU into a guest) can enumerate the
 * SAME physical card more than once, and nothing amongst
 * `collect_hardware_inventory` / the wire JSON / this function used to
 * collapse that before printing it. Two identically-described adapters at
 * the same VRAM size are, as far as this screen can ever tell, the same
 * physical card counted twice -- so identity here is (name, VRAM size),
 * the same two facts the user themselves would compare to notice a
 * duplicate. This intentionally only merges EXACT duplicates: two distinct
 * cards that happen to share a model name and VRAM size are indistinguishable
 * from a duplicate-enumerated one with the facts this screen has, and would
 * previously have been printed identically twice anyway.
 */
function dedupedGpus(gpus: readonly HardwareGpu[]): HardwareGpu[] {
  const seen = new Set<string>();
  const result: HardwareGpu[] = [];
  for (const gpu of gpus) {
    const identity = `${gpu.name} ${gpu.dedicated_vram_mb}`;
    if (seen.has(identity)) {
      continue;
    }
    seen.add(identity);
    result.push(gpu);
  }
  return result;
}

function gpuSummaryLine(hardware: HardwareInventory): string {
  if (hardware.gpus === null) {
    // The graphics probe itself could not run. That is NOT the same fact as
    // "this machine has no dedicated graphics card", and must not be printed
    // as if it were.
    return UNAVAILABLE;
  }
  const dedicated = dedupedGpus(hardware.gpus.filter((gpu) => gpu.dedicated_vram_mb > 0));
  if (dedicated.length === 0) {
    return "No dedicated graphics card";
  }
  return dedicated.map((gpu) => `${gpu.name} (${(gpu.dedicated_vram_mb / 1024).toFixed(0)} GB)`).join(", ");
}

function processorLine(hardware: HardwareInventory): string {
  if (hardware.cpu_model === null) {
    return UNAVAILABLE;
  }
  if (hardware.physical_cores === null) {
    return hardware.cpu_model;
  }
  return `${hardware.cpu_model} (${hardware.physical_cores} cores)`;
}

/**
 * Exported for direct testing (see hardware-honesty.test.ts): mounting just
 * this screen with a chosen probe result is what lets "renders Unavailable,
 * never a stand-in number" be asserted deterministically, without driving the
 * whole flow.
 */
export function MachineCheckScreen({
  hardware,
  probeError,
  onContinue
}: {
  hardware: HardwareInventory | null;
  /** Set when the native probe could not answer at all -- see api.ts's HardwareProbeResult. */
  probeError: string | null;
  onContinue: () => void;
}) {
  if (!hardware && !probeError) {
    return (
      <main className="shell shell-frame">
        <header className="topbar">
          <div>
            <h1>Checking This Computer</h1>
            <p className="lead">CivicCast is looking at this computer's hardware so it can recommend the right setup.</p>
          </div>
        </header>
        {/* F-08, keyboard half: moving the scroll off the document costs the
            keyboard its default scroller, so this region is an explicit, named
            tab stop rather than a bet on Chromium's implicitly focusable
            scrollers, which not every WebView2 build on a PEG station has. */}
        <div
          className="shell-scroll"
          data-scroll-region="machine-check"
          role="region"
          aria-label="Computer check, scrollable"
          tabIndex={0}
        >
          <div className="initial-activity" role="status" aria-label="Checking this computer">
            <progress />
            <span>This usually takes a few seconds.</span>
          </div>
        </div>
      </main>
    );
  }

  if (!hardware) {
    // The probe failed. Say so and move on -- do NOT draw a machine.
    return (
      <main className="shell shell-frame">
        <header className="topbar">
          <div>
            <h1>Checking This Computer</h1>
            <p className="lead">CivicCast could not read this computer's hardware.</p>
          </div>
        </header>
        {/* F-08, keyboard half: moving the scroll off the document costs the
            keyboard its default scroller, so this region is an explicit, named
            tab stop rather than a bet on Chromium's implicitly focusable
            scrollers, which not every WebView2 build on a PEG station has. */}
        <div
          className="shell-scroll"
          data-scroll-region="machine-check"
          role="region"
          aria-label="Computer check, scrollable"
          tabIndex={0}
        >
          <section className="disk-block-banner" role="alert" aria-label="Hardware check unavailable">
            <strong>Hardware check unavailable</strong>
            <p>{probeError}</p>
          </section>
        </div>
        <div className="shell-actions">
          <button type="button" className="detail-primary-action" onClick={onContinue}>
            Continue
          </button>
        </div>
      </main>
    );
  }

  const requiredIds = defaultSelectedComponentIds(hardware);
  const requiredBytes = requiredIds.reduce((sum, id) => sum + catalogComponent(id).placeholderSizeBytes, 0);
  const disk = diskSpaceCheck(hardware.free_disk_bytes, requiredBytes);

  return (
    <main className="shell shell-frame">
      <header className="topbar">
        <div>
          <h1>Checking This Computer</h1>
          <p className="lead">Here is what CivicCast found on this computer.</p>
        </div>
      </header>

      {/* F-08, keyboard half: moving the scroll off the document costs the
          keyboard its default scroller, so this region is an explicit, named
          tab stop rather than a bet on Chromium's implicitly focusable
          scrollers, which not every WebView2 build on a PEG station has. */}
      <div
        className="shell-scroll"
        data-scroll-region="machine-check"
        role="region"
        aria-label="Computer check, scrollable"
        tabIndex={0}
      >
        <section className="hardware-facts" aria-label="Hardware summary">
          <div>
            <span>Processor</span>
            <strong>{processorLine(hardware)}</strong>
          </div>
          <div>
            <span>Memory</span>
            <strong>{hardware.ram_gb === null ? UNAVAILABLE : `${hardware.ram_gb} GB`}</strong>
          </div>
          <div>
            <span>Graphics</span>
            <strong>{gpuSummaryLine(hardware)}</strong>
          </div>
          <div>
            <span>{hardware.install_target ? `Free disk space on ${hardware.install_target}` : "Free disk space"}</span>
            <strong>
              {hardware.free_disk_bytes === null ? UNAVAILABLE : formatBytes(hardware.free_disk_bytes)}
            </strong>
          </div>
        </section>

        <section className="recommendation-banner" aria-label="Recommendation">
          <p>{recommendationSentence(hardware)}</p>
        </section>

        {disk.blocked ? (
          <section className="disk-block-banner" role="alert" aria-label="Not enough free disk space">
            <strong>Not enough free disk space</strong>
            <p>{disk.message}</p>
            <p>Free up space on this drive, then reopen CivicCast Installer.</p>
          </section>
        ) : /* An unmeasurable drive is stated plainly, in normal text -- it is
              not an alert (nothing is wrong yet) and it must not block. */
        disk.known ? null : (
          <p className="plan-row-explanation">{disk.message}</p>
        )}
      </div>

      {/* Outside the scroll region on purpose (F-08): the operator can always
          act, whatever the window size and whatever the scroll input does. */}
      {disk.blocked ? null : (
        <div className="shell-actions">
          <button type="button" className="detail-primary-action" onClick={onContinue}>
            Continue
          </button>
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Screen 2: "What we'll download"
// ---------------------------------------------------------------------------

/** Exported for direct testing (see first-run-reachability.test.ts), the same
 * reason MachineCheckScreen and DownloadingScreen are. */
export function DownloadPlanScreen({
  freeDiskBytes,
  hardware,
  selected,
  onToggleLarge,
  onToggleCudaRuntime,
  linkSpeedBps,
  onContinue
}: {
  /**
   * Measured free bytes on the install volume, or `null` when the probe could
   * not read it. This screen never needed the whole inventory -- taking just
   * the one figure it uses is what lets it stay reachable, and honest, on a
   * run where the hardware probe failed outright.
   */
  freeDiskBytes: number | null;
  /**
   * The probe result, or `null` when it failed. Used for exactly one thing
   * (F-06): deriving the large-engine row's explanation from the SAME
   * captionEngineDecision the machine-check screen's sentence comes from, so
   * the two screens cannot say opposite things about the same engine. A null
   * here produces a decision that claims nothing about this station rather
   * than one that guesses.
   */
  hardware: HardwareInventory | null;
  selected: Set<ComponentId>;
  onToggleLarge: (checked: boolean) => void;
  /**
   * Optional (unlike `onToggleLarge`) so every existing caller/test that
   * predates the `cuda_runtime` component keeps compiling unchanged: a
   * caller that omits it simply gets a non-interactive GPU-acceleration row
   * (`PlanRow`'s existing `Boolean(onToggle)` gate), never a crash.
   */
  onToggleCudaRuntime?: (checked: boolean) => void;
  linkSpeedBps: number | null;
  onContinue: () => void;
}) {
  const planItems = COMPONENT_CATALOG.map((component) => ({
    id: component.id,
    selected: selected.has(component.id),
    sizeBytes: component.placeholderSizeBytes
  }));
  const totals = planTotals(planItems, linkSpeedBps);
  const disk = diskSpaceCheck(freeDiskBytes, totals.totalBytes);
  const captionDecision = captionEngineDecision(hardware);
  const gpuDecision = gpuAccelerationDecision(hardware);

  return (
    <main className="shell shell-frame">
      <header className="topbar">
        <div>
          <h1>What We'll Download</h1>
          <p className="lead">
            CivicCast is a small program that downloads what it needs. These are the large pieces; everything else
            downloads quietly in the background.
          </p>
        </div>
      </header>

      {/* F-08, keyboard half: moving the scroll off the document costs the
          keyboard its default scroller, so this region is an explicit, named
          tab stop rather than a bet on Chromium's implicitly focusable
          scrollers, which not every WebView2 build on a PEG station has. */}
      <div
        className="shell-scroll"
        data-scroll-region="download-plan"
        role="region"
        aria-label="Download plan, scrollable"
        tabIndex={0}
      >
        <ul className="plan-list" aria-label="Components to download">
          {COMPONENT_CATALOG.map((component) => (
            <PlanRow
              key={component.id}
              component={component}
              checked={selected.has(component.id)}
              etaSeconds={etaSeconds(component.placeholderSizeBytes, linkSpeedBps)}
              onToggle={
                component.id === "captions_large"
                  ? onToggleLarge
                  : component.id === "cuda_runtime"
                    ? onToggleCudaRuntime
                    : undefined
              }
              explanation={
                component.id === "captions_large"
                  ? largeCaptionEngineExplanation(captionDecision)
                  : component.id === "cuda_runtime"
                    ? gpuAccelerationExplanation(gpuDecision)
                    : component.optionalExplanation
              }
            />
          ))}
        </ul>

        {disk.blocked ? (
          <section className="disk-block-banner" role="alert" aria-label="Not enough free disk space">
            <strong>Not enough free disk space</strong>
            <p>{disk.message}</p>
          </section>
        ) : disk.known ? null : (
          <p className="plan-row-explanation">{disk.message}</p>
        )}
      </div>

      {/* The running total and Continue sit OUTSIDE the scroll region (F-08):
          the operator's decision number and the control that acts on it are
          both on screen at every window size, with no scrolling required. */}
      <div className="shell-actions">
        <footer className="plan-footer">
          <div>
            <strong>{formatBytes(totals.totalBytes)} total</strong>
            {/* G011.2: the "measured speed" claim is made ONLY when a rate has
                actually been measured. Nothing has been downloaded yet at this
                point in the flow, so on a real station this is always the
                second branch -- and it says so plainly instead of printing a
                duration derived from a hardcoded 28 MiB/s. */}
            <span>
              {totals.totalEtaSeconds === null
                ? "Time remaining is estimated once the download starts."
                : `${formatEta(totals.totalEtaSeconds)} at this connection's measured speed`}
            </span>
          </div>
          <p>Interrupted downloads keep their progress and can be resumed.</p>
          <button type="button" className="detail-primary-action" onClick={onContinue} disabled={disk.blocked}>
            Continue
          </button>
        </footer>
      </div>
    </main>
  );
}

function PlanRow({
  component,
  checked,
  etaSeconds: rowEtaSeconds,
  onToggle,
  explanation
}: {
  component: CatalogComponent;
  checked: boolean;
  etaSeconds: number | null;
  onToggle?: (checked: boolean) => void;
  /** The extra line under the row. Derived for the large caption engine
   * (F-06), static from the catalog for anything else. */
  explanation?: string;
}) {
  // A component the production acquisition catalog cannot deliver is never
  // togglable, never "Included", and never checked -- whatever its `required`
  // flag says. Keying the pill off `deliverable` (G011.1) replaces the old
  // "does this row happen to have an onToggle wired?" heuristic, which said
  // "Not included" for the right row by coincidence rather than by fact.
  const optional = Boolean(onToggle) && component.deliverable;
  return (
    <li className={optional ? "plan-row plan-row-optional" : "plan-row"}>
      <div className="plan-row-check">
        {!component.deliverable ? (
          <span className="plan-row-unavailable-pill" title="Not available in this release">
            Not included
          </span>
        ) : optional ? (
          <input
            type="checkbox"
            checked={checked}
            aria-label={`Include ${component.name}`}
            onChange={(event) => onToggle?.(event.target.checked)}
          />
        ) : (
          <span className="plan-row-required-pill" title="Always included">
            Included
          </span>
        )}
      </div>
      <div className="plan-row-body">
        <strong>{component.name}</strong>
        <p>{component.purpose}</p>
        {explanation ? <p className="plan-row-explanation">{explanation}</p> : null}
      </div>
      <div className="plan-row-facts">
        <strong>{formatBytes(component.placeholderSizeBytes)}</strong>
        {/* Size always; a per-row time only once a rate has been measured.
            The footer carries the one "estimated once the download starts"
            sentence, so repeating it on every row would just be noise. */}
        {rowEtaSeconds === null ? null : <span>{formatEta(rowEtaSeconds)}</span>}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Screen 3: "Downloading"
// ---------------------------------------------------------------------------

function pendingComponentProgress(id: ComponentId): AcquisitionComponentProgress {
  return {
    id,
    state: "pending",
    bytes_done: 0,
    bytes_total: catalogComponent(id).placeholderSizeBytes,
    elapsed_seconds: 0
  };
}

function useNowMillis(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function useAcquisitionComponents(selectedIds: readonly ComponentId[]) {
  const [components, setComponents] = useState<AcquisitionComponentProgress[]>(() =>
    selectedIds.map(pendingComponentProgress)
  );
  // The failure text from a REJECTED `start_acquisition`, or "" while it is
  // fine. Previously the result of that call was thrown away with `void`, so
  // a native command that could not run (the Tauri ACL denied it) left the
  // screen showing "Waiting" rows and nothing anywhere saying why.
  const [startError, setStartError] = useState<string>("");
  // Which components the ENGINE has reported a size for, as opposed to the
  // ones still carrying the catalog placeholder pendingComponentProgress
  // seeded them with. F-15: summing across those two kinds of number is what
  // made the headline denominator drift downward mid-run.
  const [measuredIds, setMeasuredIds] = useState<ReadonlySet<string>>(() => new Set());
  const componentsRef = useRef(components);
  componentsRef.current = components;
  const selectedIdsRef = useRef(selectedIds);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    // Starts the backend driver exactly once, when this screen mounts --
    // NOT inside `tick` below, which re-runs on every poll interval
    // (500ms-2s). The Rust command is itself idempotent, but calling it once
    // here keeps that guarantee from ever being exercised in the normal
    // case, and matches the one-shot "the user just reached this screen"
    // semantics described in AcquisitionFlow's module doc comment.
    void startAcquisition().then((result) => {
      if (!cancelled && !result.ok) {
        setStartError(result.message);
      }
    });

    const tick = async () => {
      if (cancelled) {
        return;
      }
      let realComponents: AcquisitionComponentProgress[] | undefined;
      try {
        const progress = await loadInstallerProgress();
        realComponents = progress?.acquisition?.components;
      } catch {
        realComponents = undefined;
      }
      if (cancelled) {
        return;
      }
      if (realComponents) {
        setMeasuredIds((prev) => {
          let next: Set<string> | null = null;
          for (const component of realComponents) {
            if (component.bytes_total !== null && component.bytes_total !== undefined && !prev.has(component.id)) {
              next = next ?? new Set(prev);
              next.add(component.id);
            }
          }
          return next ?? prev;
        });
      }
      setComponents((prev) => {
        // Real polled data only (component_acquisition.rs's ProgressObserver,
        // written into installer-state.json's `acquisition` field by
        // main.rs's acquisition driver -- see write_installer_state). A
        // component this screen is tracking but the engine hasn't reported
        // on yet stays exactly as it was (or `pending` on the very first
        // tick): no simulated advancement.
        return selectedIdsRef.current.map(
          (id) =>
            realComponents?.find((component) => component.id === id) ??
            prev.find((component) => component.id === id) ??
            pendingComponentProgress(id)
        );
      });
      timer = window.setTimeout(() => void tick(), pollIntervalMs(componentsRef.current));
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
    // Intentionally runs once per mount: selectedIds is fixed for the
    // lifetime of the downloading screen (set when the user left the plan
    // screen).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { components, startError, measuredIds };
}

/** Exported for direct testing (see AcquisitionFlow.test.ts): mounting just
 * this screen, without driving the whole checking/plan phase sequence
 * through simulated clicks, is what lets the screen-entry `startAcquisition`
 * call be asserted deterministically. */
export function DownloadingScreen({
  selectedIds,
  onAllComplete
}: {
  selectedIds: readonly ComponentId[];
  onAllComplete: () => void;
}) {
  const { components, startError, measuredIds } = useAcquisitionComponents(selectedIds);
  const nowMillis = useNowMillis(true);
  const sampleHistory = useRef<Map<string, ProgressSample[]>>(new Map());
  const overallSamples = useRef<ProgressSample[]>([]);
  const lastByteChange = useRef<Map<string, { bytes: number; atMillis: number }>>(new Map());
  const screenEntryMillis = useRef<number>(Date.now());
  // `string`, not ComponentId: this only ever holds an id read back off an
  // AcquisitionComponentProgress row, which is whatever the backend sent.
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<string>("");
  const [cancelError, setCancelError] = useState<string>("");
  // Bug fix (field report 2026-08-28, candidate 9d4477b): "Open installer
  // log" had no error state at all -- its onClick awaited openInstallerLog()
  // directly, so a rejected promise (no log found yet, or the OS could not
  // launch a viewer) surfaced nowhere but the devtools console. From the
  // operator's chair the button simply did nothing. This state gives that
  // failure a visible home, the same way cancelError already does for "Stop
  // downloading".
  const [logOpenError, setLogOpenError] = useState<string>("");

  const allDone = components.every((component) => component.state === "complete" || component.state === "found_locally");
  // Something is still in flight or still waiting to start -- i.e. there is
  // something a cancel would actually stop. A canceled or errored row is NOT
  // stoppable (its own Resume/Retry is the affordance), so the control
  // disappears once every row has come to rest.
  // Shares acquisitionRowIsActive with DownloadRow so the two cannot drift:
  // a state one of them treats as "in flight" and the other does not is
  // exactly how a screen ends up with no control on it at all (F-04).
  const stoppable = components.some((component) => acquisitionRowIsActive(component.state));
  useEffect(() => {
    if (allDone) {
      markAcquisitionFlowComplete();
      onAllComplete();
    }
  }, [allDone, onAllComplete]);

  // F-15. The denominator is the total this run was ANNOUNCED with (the
  // published sizes the plan screen showed), and it holds until every file's
  // real size is known -- then it re-baselines exactly once, out loud, and is
  // frozen. It must never be re-summed per render across a mixture of
  // measured and placeholder sizes, which is what made it walk 12.8 -> 12.1
  // -> 11.6 GB in front of the operator.
  const announcedTotalBytes = useRef(
    selectedIds.reduce((sum, id) => sum + catalogComponent(id).placeholderSizeBytes, 0)
  ).current;
  const settledTotal = useRef<DownloadTotalDenominator | null>(null);
  if (settledTotal.current === null) {
    const candidate = downloadTotalDenominator(announcedTotalBytes, components, measuredIds);
    if (candidate.settled) {
      settledTotal.current = candidate;
    }
  }
  const denominator =
    settledTotal.current ?? downloadTotalDenominator(announcedTotalBytes, components, measuredIds);
  const totalBytes = denominator.totalBytes;
  const totalDone = components.reduce((sum, component) => sum + component.bytes_done, 0);

  // The overall time remaining, measured (G011.2). Same rolling window and
  // same EMA the per-row rates use, applied to the aggregate byte count, so
  // the headline number and the row numbers cannot tell different stories.
  // A fresh `Date.now()` here, NOT the `nowMillis` display clock -- see
  // appendProgressSample's doc comment for why a coarse shared clock silently
  // produces a stuck 0 B/s. `null` until two samples exist, which is rendered
  // as an absence, never as a rate.
  overallSamples.current = appendProgressSample(overallSamples.current, {
    bytesDone: totalDone,
    atSeconds: Date.now() / 1000
  });
  const overallRate = emaBytesPerSecond(overallSamples.current);
  const overallEta = etaSeconds(Math.max(0, totalBytes - totalDone), overallRate);

  const currentComponent = components.find((component) => component.state === "downloading" || component.state === "verifying");

  // Screen-level watchdog: every row still `pending` and not one byte moved
  // anywhere. The per-row `isStalled` check below cannot see this -- it only
  // fires for a row already in `downloading` -- so a driver that never
  // started produced a screen with no indication of trouble at all.
  const nothingMoving = noBytesMovedYet(components, (nowMillis - screenEntryMillis.current) / 1000);
  const alertMessage = logOpenError
    ? logOpenError
    : cancelError
    ? cancelError
    : startError
      ? startError
      : nothingMoving
        ? "No files have started downloading yet. CivicCast is still waiting for the first byte. " +
          "If this does not change, use Open installer log below and send that log to support."
        : "";

  return (
    <main className="shell shell-frame">
      <header className="topbar">
        <div>
          <h1>Downloading</h1>
          <p className="lead">Keep CivicCast Installer open. If a download is interrupted, use Resume download.</p>
        </div>
      </header>

      {alertMessage ? (
        <p className="status-message status-message-error" role="alert">
          {alertMessage}
        </p>
      ) : null}

      {/* The headline figure and the overall bar stay OUT of the scroll
          region (F-08): they are the numbers an operator watches, and in
          F-04 they were the numbers frozen on screen while the rows below
          were the thing that had to be scrolled to. */}
      <section className="overall-progress" aria-label="Overall download progress">
        <div className="activity-facts">
          <span>
            {formatBytes(totalDone)} of {formatBytes(totalBytes)}
          </span>
          <span>
            {allDone
              ? "Done"
              : overallEta === null
                ? `Time left: ${ETA_NOT_YET_MEASURED}`
                : `${formatEta(overallEta)} left`}
          </span>
        </div>
        <progress max={totalBytes || 1} value={totalDone} />
        {denominator.rebaselineNote ? (
          <p className="total-rebaseline" role="status" aria-live="polite">
            {denominator.rebaselineNote}
          </p>
        ) : null}
      </section>

      {/* F-08, keyboard half: moving the scroll off the document costs the
          keyboard its default scroller, so this region is an explicit, named
          tab stop rather than a bet on Chromium's implicitly focusable
          scrollers, which not every WebView2 build on a PEG station has. */}
      <div
        className="shell-scroll"
        data-scroll-region="downloading"
        role="region"
        aria-label="Component list, scrollable"
        tabIndex={0}
      >
        <ul className="download-list" aria-label="Component downloads">
          {components.map((component) => {
            // Wire-supplied id: `catalogComponent` THROWS on one it does not
            // know, and this call is inside render -- see
            // catalogComponentForWireId's doc for the blank-screen it caused.
            const catalog = catalogComponentForWireId(component.id);
            const history = sampleHistory.current.get(component.id) ?? [];
            if (component.state === "downloading" || component.state === "verifying") {
              // A fresh Date.now() here, NOT the `nowMillis` display-clock state:
              // see appendProgressSample's doc comment for why using a coarse
              // shared clock silently produces a stuck 0 B/s reading.
              sampleHistory.current.set(component.id, appendProgressSample(history, { bytesDone: component.bytes_done, atSeconds: Date.now() / 1000 }));
            }
            const rate = emaBytesPerSecond(sampleHistory.current.get(component.id) ?? []);
            const remaining = (component.bytes_total ?? 0) - component.bytes_done;
            const rowEta = etaSeconds(remaining, rate);

            const lastChange = lastByteChange.current.get(component.id);
            if (!lastChange || lastChange.bytes !== component.bytes_done) {
              lastByteChange.current.set(component.id, { bytes: component.bytes_done, atMillis: nowMillis });
            }
            const secondsSinceLastByte = ((nowMillis - (lastByteChange.current.get(component.id)?.atMillis ?? nowMillis)) / 1000);
            const stalled = component.state === "downloading" && isStalled(secondsSinceLastByte);

            return (
              <DownloadRow
                key={component.id}
                catalog={catalog}
                progress={component}
                rateBytesPerSecond={rate}
                etaSeconds={rowEta}
                stalled={stalled}
                expanded={expandedId === component.id}
                onToggleExpanded={() => setExpandedId((current) => (current === component.id ? null : component.id))}
                onRetry={async () => {
                  setRetryMessage(`Retrying ${catalog.name}.`);
                  const message = await retryAcquisitionComponent(component.id);
                  setRetryMessage(message);
                }}
                isCurrent={currentComponent?.id === component.id}
              />
            );
          })}
        </ul>
      </div>

      {/* G011.3: cancel, wired. Present only while something is actually in
          flight, so it never offers to stop a run that has already come to
          rest. Not styled as a primary action -- continuing is the expected
          path -- but reachable without hunting, because the operator who
          needs it (metered connection, wrong drive) needs it right now.

          F-08/F-04: it lives outside the scroll region, so on the screen the
          walkthrough dead-ended on -- a row stalled at "0 KB of 3.1 GB" with
          other rows finished -- the escape is on screen without scrolling
          and in the tab order, at any window size. */}
      <div className="shell-actions">
        {retryMessage ? (
          <p className="status-message" role="status" aria-live="polite">
            {retryMessage}
          </p>
        ) : null}
        {stoppable ? (
          <button
            type="button"
            className="secondary-action"
            onClick={async () => {
              setCancelError("");
              const outcome = await cancelAcquisition();
              if (!outcome.ok) {
                setCancelError(outcome.message);
                return;
              }
              setRetryMessage(outcome.message);
            }}
          >
            Stop downloading
          </button>
        ) : null}
        {/* F-04. The screen's guaranteed floor: while the run has not
            finished there is ALWAYS at least one control here, outside the
            scroll region, whatever state the rows are in. Nothing is in
            flight on a screen where every row has stopped, so Stop is gone
            and a row's own Retry may be scrolled out of sight -- which is the
            state the walkthrough tabbed ten times through and found nothing.
            It also makes the zero-bytes alert's own advice true: that copy
            tells the operator to "use Open installer log", and until now this
            screen had no such control. */}
        {allDone ? null : (
          <button
            type="button"
            className="secondary-action"
            onClick={async () => {
              setLogOpenError("");
              try {
                setRetryMessage(await openInstallerLog());
              } catch (error) {
                // The prior version awaited openInstallerLog() with no
                // catch at all, so a rejection (no log on disk yet, or the
                // OS could not launch a viewer for it) became a silent
                // unhandled promise rejection -- the button visibly did
                // nothing. Surface it through the same alert surface
                // "Stop downloading" already uses for its own failures.
                setLogOpenError(
                  error instanceof Error ? error.message : String(error)
                );
              }
            }}
          >
            Open installer log
          </button>
        )}
      </div>
    </main>
  );
}

function DownloadRow({
  catalog,
  progress,
  rateBytesPerSecond,
  etaSeconds: rowEtaSeconds,
  stalled,
  expanded,
  onToggleExpanded,
  onRetry,
  isCurrent
}: {
  catalog: CatalogComponent;
  progress: AcquisitionComponentProgress;
  rateBytesPerSecond: number | null;
  etaSeconds: number | null;
  stalled: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  onRetry: () => void;
  /** download-ux-spec.md: only the currently-downloading component shows "What is this?". */
  isCurrent: boolean;
}) {
  if (progress.state === "complete" || progress.state === "found_locally") {
    return (
      <li className="download-row is-complete">
        <strong>{catalog.name}</strong>
        <span>
          {progress.state === "found_locally" ? "Found locally — verified ✓" : "Verified ✓ — checked against its signature"}
        </span>
      </li>
    );
  }

  // G011.3. A stop the operator asked for is not a failure: no red error
  // treatment, no remedy to name, and the partial bytes really are still on
  // disk, so the affordance is Resume and it means it.
  if (progress.state === "canceled") {
    return (
      <li className="download-row is-canceled">
        <strong>{catalog.name}</strong>
        <p>
          Stopped. {formatBytes(progress.bytes_done)} of{" "}
          {formatBytes(progress.bytes_total ?? catalog.placeholderSizeBytes)} is already downloaded and
          kept.
        </p>
        <button type="button" className="secondary-action" onClick={onRetry}>
          Resume download
        </button>
      </li>
    );
  }

  // F-04. Anything that is neither finished above, nor stopped by the
  // operator above, nor genuinely in flight is a STOP, and a stop always
  // names itself and always offers a control. That deliberately includes two
  // cases the old `state === "error" && progress.error` guard fell through:
  // an `error` the engine attached no payload to, and a state this build does
  // not recognise (the Rust side gaining one before the frontend does). Both
  // used to land on the "still going" row shape below -- a progress bar and
  // the word "Downloading" for a component that had stopped, with no control
  // anywhere and `allDone` false forever. That is the dead end the newcomer
  // walkthrough recorded: a frozen row and nothing to press.
  if (progress.state === "error" || !acquisitionRowIsActive(progress.state)) {
    const presentation = progress.error ? presentAcquisitionError(progress.error.kind) : UNEXPLAINED_STOP;
    // Tell the operator whether Retry picks up where it left off or starts
    // this file over — it matters for a multi-gigabyte component.
    const retryLabel = presentation.retryResumes ? "Resume download" : "Retry download";
    return (
      <li className="download-row is-error">
        <strong>{catalog.name}</strong>
        <p>{presentation.line}</p>
        <button type="button" className="secondary-action" onClick={onRetry}>
          {retryLabel}
        </button>
      </li>
    );
  }

  const total = progress.bytes_total ?? catalog.placeholderSizeBytes;
  const statusLine =
    progress.state === "pending"
      ? "Waiting"
      : stalled
        ? "Stalled — retrying"
        : progress.state === "verifying"
          ? "Verifying"
          : "Downloading";

  return (
    <li className="download-row">
      <div className="download-row-head">
        <strong>{catalog.name}</strong>
        <span>{statusLine}</span>
      </div>
      <progress max={total || 1} value={progress.bytes_done} />
      <div className="activity-facts">
        <span>
          {formatBytes(progress.bytes_done)} of {formatBytes(total)}
        </span>
        <span>
          {progress.state === "pending"
            ? "Not started yet"
            : rateBytesPerSecond !== null
              ? `${formatBytes(rateBytesPerSecond)}/s — ${formatEta(rowEtaSeconds)} left`
              : "Measuring speed"}
        </span>
      </div>
      {isCurrent ? (
        <details className="what-is-this" onToggle={onToggleExpanded} open={expanded}>
          <summary>What is this?</summary>
          <p>{catalog.purpose}</p>
        </details>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

export function AcquisitionFlow({ onComplete }: { onComplete: () => void }) {
  const [hardware, setHardware] = useState<HardwareInventory | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"checking" | "plan" | "downloading">("checking");
  const [selected, setSelected] = useState<Set<ComponentId>>(new Set());
  const [linkSpeedBps, setLinkSpeedBps] = useState<number | null>(null);
  const selectedIdsAtDownloadStart = useRef<ComponentId[]>([]);

  useEffect(() => {
    let ignore = false;
    const minimumDisplay = new Promise<void>((resolve) => {
      window.setTimeout(resolve, 650);
    });
    Promise.all([fetchHardwareInventory(), minimumDisplay]).then(([probe]) => {
      if (ignore) {
        return;
      }
      if (!probe.ok) {
        // No inventory, so no facts on screen and no recommendation derived
        // from facts that do not exist. The required components are still
        // known (they are required regardless of hardware), so the install
        // can proceed -- it just proceeds having said what it does not know.
        setProbeError(probe.message);
        setSelected(new Set(COMPONENT_CATALOG.filter((component) => component.required).map((component) => component.id)));
        return;
      }
      setHardware(probe.inventory);
      setSelected(new Set(defaultSelectedComponentIds(probe.inventory)));
    });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (phase !== "plan") {
      return;
    }
    let ignore = false;
    // The ONLY source of a plan-screen rate. G011.2: there used to be a
    // second one -- a 1400ms `setTimeout` that landed a hardcoded
    // `28 * 1024 * 1024` bytes/second, described in its own comment as a
    // "demo/dev fallback ... a plausible rate". No native
    // measure_link_speed_bytes_per_second command is registered (main.rs's
    // generate_handler! list), so on every real station that fallback was
    // what the operator saw: a duration under the words "at this
    // connection's measured speed", derived from a number nobody measured.
    // It is gone, with nothing in its place. The measured rate the product
    // does have comes from real transferred bytes on the downloading screen
    // (emaBytesPerSecond over RATE_EMA_WINDOW_SECONDS).
    void measureLinkSpeedBytesPerSecond().then((bps) => {
      if (!ignore && bps !== null) {
        setLinkSpeedBps(bps);
      }
    });
    return () => {
      ignore = true;
    };
  }, [phase]);

  const memoizedCatalogIds = useMemo(() => COMPONENT_CATALOG.map((component) => component.id), []);

  // A failed probe (hardware === null, probeError set) does NOT wedge the
  // flow here the way `|| !hardware` used to: the screen says what could not
  // be read and Continue still moves on. Only the genuinely still-probing
  // state (both null) holds this screen.
  if (phase === "checking" || (!hardware && !probeError)) {
    return (
      <MachineCheckScreen hardware={hardware} probeError={probeError} onContinue={() => setPhase("plan")} />
    );
  }

  if (phase === "plan") {
    return (
      <DownloadPlanScreen
        freeDiskBytes={hardware?.free_disk_bytes ?? null}
        hardware={hardware}
        selected={selected}
        linkSpeedBps={linkSpeedBps}
        onToggleLarge={(checked) => {
          setSelected((current) => {
            const next = new Set(current);
            if (checked) {
              next.add("captions_large");
            } else {
              next.delete("captions_large");
            }
            return next;
          });
        }}
        onToggleCudaRuntime={(checked) => {
          setSelected((current) => {
            const next = new Set(current);
            if (checked) {
              next.add("cuda_runtime");
            } else {
              next.delete("cuda_runtime");
            }
            return next;
          });
        }}
        onContinue={() => {
          selectedIdsAtDownloadStart.current = memoizedCatalogIds.filter((id) => selected.has(id));
          setPhase("downloading");
        }}
      />
    );
  }

  return <DownloadingScreen selectedIds={selectedIdsAtDownloadStart.current} onAllComplete={onComplete} />;
}

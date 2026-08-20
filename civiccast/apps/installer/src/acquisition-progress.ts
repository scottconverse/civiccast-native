// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// Pure logic for the download-experience screens: EMA rate/ETA smoothing,
// poll-rate switching, the five-variant error->operator-message mapping,
// plan-screen size/ETA totals, and disk-space blocking. Kept dependency-free
// (no React, no Tauri) so it is trivial to unit test and to swap in real
// polled samples for the current local-mock fallback in AcquisitionFlow.tsx.

import { COMPONENT_CATALOG, type CatalogComponent, type ComponentId } from "./components-catalog";
import type {
  AcquisitionComponentProgress,
  AcquisitionErrorKind,
  HardwareInventory
} from "./types";

const GB_BYTES = 1024 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Rate / ETA smoothing
// ---------------------------------------------------------------------------

export interface ProgressSample {
  bytesDone: number;
  /** Monotonic seconds (elapsed_seconds from the engine, or Date.now() / 1000). */
  atSeconds: number;
}

/**
 * The rolling window every measured rate in the download experience is
 * averaged over, in seconds.
 *
 * Five seconds, chosen against the two real timescales this has to sit
 * between: the poll interval (500ms while anything is downloading, so a 5s
 * window averages ~10 samples -- enough that one late tick or one 64 KiB
 * read-buffer boundary cannot swing the number) and an operator's patience
 * (an ETA that takes longer than a few seconds to settle after a genuine
 * speed change reads as broken). Short enough to follow a real drop when a
 * shared office link gets busy; long enough not to flicker on TCP's normal
 * second-to-second variation.
 */
export const RATE_EMA_WINDOW_SECONDS = 5;

/**
 * How many samples of that window are retained. Twelve is the 5s window at
 * the 500ms active poll rate, plus headroom for a late tick.
 */
export const RATE_SAMPLE_HISTORY_LENGTH = 12;

/**
 * Exponential moving average of the download rate over the
 * {@link RATE_EMA_WINDOW_SECONDS} window, computed from successive polled
 * samples. Each step's smoothing factor is derived from that step's actual
 * time delta (`1 - e^(-dt/window)`) so uneven poll intervals (500ms vs 2s, or
 * a slow tick) still converge at a consistent effective half-life instead of
 * over- or under-weighting a step just because the poller happened to fire
 * late.
 *
 * `null` -- fewer than two samples, i.e. nothing has been measured yet -- is
 * the ONLY honest answer before bytes move, and every caller must render it
 * as an absence rather than substituting a rate. G011.2: the plan screen used
 * to substitute a hardcoded 28 MiB/s after 1400ms and print a duration under
 * the words "at this connection's measured speed".
 */
export function emaBytesPerSecond(
  samples: readonly ProgressSample[],
  windowSeconds = RATE_EMA_WINDOW_SECONDS
): number | null {
  if (samples.length < 2) {
    return null;
  }
  let ema: number | null = null;
  for (let i = 1; i < samples.length; i += 1) {
    const prev = samples[i - 1];
    const curr = samples[i];
    const dt = curr.atSeconds - prev.atSeconds;
    if (dt <= 0) {
      continue;
    }
    const instantRate = (curr.bytesDone - prev.bytesDone) / dt;
    const alpha = 1 - Math.exp(-dt / windowSeconds);
    ema = ema === null ? instantRate : alpha * instantRate + (1 - alpha) * ema;
  }
  return ema;
}

/**
 * Append one polled sample to a component's rolling history, capped to the
 * last `maxSamples` (default matches the ~5s EMA window at a 500ms poll
 * rate). Pulled out as its own pure, tested function because the caller
 * MUST timestamp each sample with a fresh, fine-grained clock read (e.g.
 * `Date.now()`) taken at the moment of the sample -- NOT a UI display clock
 * that only ticks once a second (or less, under background-tab throttling).
 * Feeding emaBytesPerSecond samples off a coarse shared clock reliably
 * produces a *silent* 0 B/s: every real byte jump lands on a repeated
 * timestamp and gets dropped by the dt<=0 guard, while every pair that DOES
 * span two distinct timestamps ends up comparing two samples that happen to
 * carry the same (stale) byte count. See the regression test below.
 */
export function appendProgressSample(
  history: readonly ProgressSample[],
  sample: ProgressSample,
  maxSamples = RATE_SAMPLE_HISTORY_LENGTH
): ProgressSample[] {
  return [...history, sample].slice(-maxSamples);
}

export function etaSeconds(bytesRemaining: number, bytesPerSecond: number | null): number | null {
  if (bytesPerSecond === null || bytesPerSecond <= 0) {
    return null;
  }
  if (bytesRemaining <= 0) {
    return 0;
  }
  return bytesRemaining / bytesPerSecond;
}

// ---------------------------------------------------------------------------
// Poll-rate switching
// ---------------------------------------------------------------------------

/**
 * download-ux-spec.md, Contracts: 500ms while any component is downloading,
 * 2s otherwise. "verifying" counts as active too -- the hash check runs
 * immediately after the last byte lands and the row should keep updating
 * live through it rather than freezing right before the checkmark.
 */
export function pollIntervalMs(components: readonly AcquisitionComponentProgress[]): number {
  const anyActive = components.some((component) => component.state === "downloading" || component.state === "verifying");
  return anyActive ? 500 : 2000;
}

// ---------------------------------------------------------------------------
// Error -> operator-facing copy (the five typed AcquisitionError variants)
// ---------------------------------------------------------------------------

export interface AcquisitionErrorPresentation {
  /** Plain-language line: no jargon, never blames the user, no exclamation marks. */
  line: string;
  /** Whether Retry can resume from where it left off, or must restart the file. */
  retryResumes: boolean;
}

const ERROR_PRESENTATIONS: Record<AcquisitionErrorKind, AcquisitionErrorPresentation> = {
  network_failed: {
    line: "The connection dropped. Nothing is damaged.",
    retryResumes: true
  },
  hash_mismatch: {
    line: "The downloaded file didn't match its signature and was discarded.",
    retryResumes: false
  },
  source_not_found: {
    line: "The download server didn't have this file. This is our problem, not yours.",
    retryResumes: false
  },
  resume_invalid: {
    line: "The paused download couldn't pick up where it left off, so this file will start over. This is our problem, not yours.",
    retryResumes: false
  },
  disk_full: {
    line: "This drive doesn't have enough free space to finish this download. Free up some space, then choose Retry.",
    retryResumes: false
  },
  // Chain H2. R7's operator was shown the disk_full line above -- "free up
  // some space" -- on a station with 175.3 GiB free, because the engine
  // filed a PermissionDenied under disk_full. These two lines exist so a
  // write failure describes the failure it actually was and names a remedy
  // that can actually work.
  permission_denied: {
    line: "Windows wouldn't let CivicCast save this file. Security software blocking the CivicCast folder is the usual cause; allow CivicCast in it, or start CivicCast with 'Run as administrator' once, then choose Retry.",
    retryResumes: false
  },
  write_failed: {
    line: "This file couldn't be saved to disk. The download folder may be unavailable or read-only. Check that the drive is connected and writable, then choose Retry.",
    retryResumes: false
  }
};

/**
 * What a row says when the engine reports a stop this build cannot explain:
 * an `error` state with no error payload attached, or an error kind added on
 * the Rust side that this frontend does not know yet.
 *
 * F-04. Before this existed, `presentAcquisitionError` indexed the record
 * directly and an unmapped kind returned `undefined`, which threw on the very
 * next line and took the whole downloading screen down; and an `error` with no
 * payload skipped the failure branch entirely, leaving a row that drew a
 * progress bar and the word "Downloading" for a component that had stopped,
 * with no control on it and `allDone` false forever. Both are the shape the
 * walkthrough recorded: a frozen row and nothing to press.
 *
 * `retryResumes: false` deliberately. We do not know what happened, so we do
 * not promise the bytes already on disk will be reused.
 */
export const UNEXPLAINED_STOP: AcquisitionErrorPresentation = {
  line:
    "This download stopped and CivicCast did not get a reason it can explain. Nothing on this computer is damaged. " +
    "Choose Retry; if it stops again, use Open installer log and send that log to support.",
  retryResumes: false
};

export function presentAcquisitionError(kind: AcquisitionErrorKind): AcquisitionErrorPresentation {
  return ERROR_PRESENTATIONS[kind] ?? UNEXPLAINED_STOP;
}

/**
 * Whether a row is genuinely in flight -- something a Stop would actually
 * stop, and something whose "still going" row shape is honest.
 *
 * Deliberately a positive allow-list over the state string rather than a
 * "not one of the finished ones" test (F-04): a state this build has never
 * heard of is NOT in flight, and treating it as if it were is what produced a
 * permanently animated row with no way off the screen.
 */
export function acquisitionRowIsActive(state: string): boolean {
  return state === "pending" || state === "downloading" || state === "verifying";
}

// ---------------------------------------------------------------------------
// Stalled-state honesty
// ---------------------------------------------------------------------------

/** download-ux-spec.md: "If stalled >10s, say 'Stalled -- retrying' honestly." */
export function isStalled(secondsSinceLastByte: number, thresholdSeconds = 10): boolean {
  return secondsSinceLastByte > thresholdSeconds;
}

/**
 * How long the whole screen may sit with every row `pending` and zero bytes
 * moved before that silence is itself reported.
 *
 * Deliberately longer than `isStalled`'s 10s per-row threshold: this covers
 * the very start of the download, where the driver legitimately spends some
 * seconds resolving the catalog and opening the first connection, and where a
 * false "nothing is happening" would be its own dishonesty. 30s is well past
 * any observed healthy start and well short of an operator giving up.
 */
export const NO_BYTES_MOVED_THRESHOLD_SECONDS = 30;

/**
 * The screen-level counterpart to {@link isStalled}: EVERY row is still
 * `pending` and not one byte has moved anywhere, for longer than the
 * threshold.
 *
 * `isStalled` alone cannot see this case. It only fires for a row whose state
 * is `downloading`, so a driver that never started at all -- the exact shape
 * of the Tauri ACL denial, where `start_acquisition` was rejected and no row
 * ever left `pending` -- produced a screen with no stall indicator anywhere,
 * forever. Pure and dependency-free like everything else in this module.
 */
export function noBytesMovedYet(
  components: readonly AcquisitionComponentProgress[],
  secondsSinceScreenEntry: number,
  thresholdSeconds = NO_BYTES_MOVED_THRESHOLD_SECONDS
): boolean {
  if (components.length === 0) {
    return false;
  }
  if (!components.every((component) => component.state === "pending")) {
    return false;
  }
  if (components.some((component) => component.bytes_done > 0)) {
    return false;
  }
  return secondsSinceScreenEntry > thresholdSeconds;
}

// ---------------------------------------------------------------------------
// A denominator that holds still (F-15)
// ---------------------------------------------------------------------------

export interface DownloadTotalDenominator {
  /** The figure to print after "of". */
  totalBytes: number;
  /**
   * Non-null exactly when the displayed total is no longer the one the run
   * was announced with. Carries BOTH figures, because a number that changes
   * without saying it changed is the defect, not the fix.
   */
  rebaselineNote: string | null;
  /**
   * True once every tracked component has reported a measured size -- i.e.
   * this answer will not change again, and the caller may freeze it.
   */
  settled: boolean;
}

/**
 * F-15. The downloading screen's denominator drifted DOWNWARD mid-run --
 * 12.8 GB, then 12.1 GB, then 11.6 GB -- because it re-summed `bytes_total`
 * across the rows on every render, and each row started at the catalog's
 * PLACEHOLDER size and was overwritten with the engine's measured size the
 * moment that component was picked up. Every replacement moved the headline
 * figure, in the direction that looks most like the product quietly dropping
 * something it promised.
 *
 * The rule: the announced total holds for the whole run, and moves at most
 * ONCE -- when every file's real size is known, so there is nothing left to
 * learn -- and when it moves it says so with both figures.
 *
 * `measuredIds` is the set of components the engine has actually reported on;
 * a component still carrying its placeholder is exactly the case that must
 * NOT be allowed to move the total.
 */
export function downloadTotalDenominator(
  announcedBytes: number,
  components: readonly AcquisitionComponentProgress[],
  measuredIds: ReadonlySet<string>
): DownloadTotalDenominator {
  const allMeasured = components.length > 0 && components.every((component) => measuredIds.has(component.id));
  if (!allMeasured) {
    return { totalBytes: announcedBytes, rebaselineNote: null, settled: false };
  }
  const measuredBytes = components.reduce((sum, component) => sum + (component.bytes_total ?? 0), 0);
  if (measuredBytes === announcedBytes) {
    return { totalBytes: announcedBytes, rebaselineNote: null, settled: true };
  }
  return {
    totalBytes: measuredBytes,
    rebaselineNote:
      `Total updated to ${formatBytes(measuredBytes)}. The download was announced as ` +
      `${formatBytes(announcedBytes)} from the published sizes; every file's real size is now known. ` +
      "This figure does not change again during this download.",
    settled: true
  };
}

// ---------------------------------------------------------------------------
// Human-readable formatting
// ---------------------------------------------------------------------------

export function formatBytes(bytes: number): string {
  if (bytes <= 0) {
    // Never round 0 up to "1 KB" -- at the very start of a download that
    // would be a small fabrication, and the no-fake-motion rule applies to
    // numbers just as much as to the progress bar itself.
    return "0 KB";
  }
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  if (bytes < GB_BYTES) {
    const mb = bytes / (1024 * 1024);
    return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
  }
  const gb = bytes / GB_BYTES;
  return `${gb.toFixed(1)} GB`;
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total} second${total === 1 ? "" : "s"}`;
  }
  const minutes = Math.floor(total / 60);
  const remainderSeconds = total % 60;
  if (minutes < 60) {
    return remainderSeconds ? `${minutes} min ${remainderSeconds} sec` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return remainderMinutes ? `${hours} hr ${remainderMinutes} min` : `${hours} hr`;
}

/**
 * The copy shown wherever a time remaining WOULD go before anything has been
 * measured. Deliberately not a number and deliberately not the word
 * "Calculating" on its own -- an operator reads that as "a number is coming
 * any moment", which is untrue on the plan screen, where nothing will be
 * measured until bytes actually start moving.
 */
export const ETA_NOT_YET_MEASURED = "Estimating…";

export function formatEta(seconds: number | null): string {
  return seconds === null ? ETA_NOT_YET_MEASURED : formatDuration(seconds);
}

// ---------------------------------------------------------------------------
// Plan-screen totals
// ---------------------------------------------------------------------------

export interface PlanLineItem {
  id: ComponentId;
  selected: boolean;
  sizeBytes: number;
}

export interface PlanTotals {
  totalBytes: number;
  totalEtaSeconds: number | null;
}

export function planTotals(items: readonly PlanLineItem[], bytesPerSecond: number | null): PlanTotals {
  const totalBytes = items.filter((item) => item.selected).reduce((sum, item) => sum + item.sizeBytes, 0);
  return { totalBytes, totalEtaSeconds: etaSeconds(totalBytes, bytesPerSecond) };
}

// ---------------------------------------------------------------------------
// Disk-space blocking
// ---------------------------------------------------------------------------

export interface DiskSpaceCheck {
  /** True ONLY for a real, measured shortfall. An unknown never blocks. */
  blocked: boolean;
  /** False when free space could not be measured at all. */
  known: boolean;
  /** download-ux-spec.md: name the number, e.g. "needs 9.4 GB free, this drive has 3.1 GB". */
  message: string | null;
}

/**
 * The install's disk go/no-go, evaluated against MEASURED free bytes.
 *
 * `freeDiskBytes === null` means the probe could not read the volume
 * (`hardware_inventory.rs`'s `collect_free_disk_bytes` returning `None`), and
 * that is reported as an unknown -- `blocked: false, known: false` -- not
 * coerced into a number first. G011.1: the parameter used to be a plain
 * `number` of whole GB, which left the two callers no way to say "unknown"
 * and gave a failed probe only bad options: `0` blocks a perfectly healthy
 * machine with "free up space", and the frontend's 120 GB mock passed a
 * genuinely full one. An unknown must masquerade as neither.
 */
export function diskSpaceCheck(freeDiskBytes: number | null, requiredBytes: number): DiskSpaceCheck {
  const requiredGb = requiredBytes / GB_BYTES;
  if (freeDiskBytes === null) {
    return {
      blocked: false,
      known: false,
      message: `CivicCast could not check free disk space on this computer. Setup needs about ${requiredGb.toFixed(
        1
      )} GB.`
    };
  }
  if (freeDiskBytes >= requiredBytes) {
    return { blocked: false, known: true, message: null };
  }
  const freeGb = freeDiskBytes / GB_BYTES;
  return {
    blocked: true,
    known: true,
    message: `This drive doesn't have enough free space: needs ${requiredGb.toFixed(1)} GB free, this drive has ${freeGb.toFixed(1)} GB.`
  };
}

// ---------------------------------------------------------------------------
// Hardware-driven defaults (screen 1 recommendation, screen 2 selection)
// ---------------------------------------------------------------------------

/**
 * THE ONE DECISION about the large ("higher-quality") caption engine.
 *
 * F-06: the machine-check screen and the download-plan screen used to make
 * opposite claims about the same engine one click apart -- "can run the
 * highest-quality caption engine in real time. We've selected it for you"
 * followed by "too slow for live captioning on this hardware". They could
 * disagree because they shared no fact: the sentence was computed from the
 * probed caption tiers, while the row's explanation was a fixed string in
 * components-catalog.ts that knows nothing about the machine. Nothing on
 * either side could have kept them in agreement.
 *
 * Every sentence about this engine on either screen is now derived from this
 * one value, so a contradiction is not something a careful author avoids --
 * it is something the code cannot express.
 */
export interface CaptionEngineDecision {
  /** The engine that will actually be installed. */
  installedTier: HardwareInventory["recommended_caption_tier"];
  /**
   * Whether the large engine would keep up with a live meeting on THIS
   * station.
   *
   * `null` means the graphics probe could not run, and it must stay null
   * rather than collapsing to `false`: `hardware_capable_caption_tier` falls
   * back to the floor tier when DXGI could not be reached, so treating a
   * missing reading as "no" would print "too slow for live captioning on this
   * station" about a card nobody looked at -- the exact class of fabrication
   * G011.1 removed from the facts panel.
   */
  largeRunsLiveHere: boolean | null;
  /** Whether the large engine can be downloaded at all in this release. */
  largeObtainable: boolean;
  /** Whether a fresh install starts out with the large engine selected. */
  largeSelectedByDefault: boolean;
}

export function captionEngineDecision(
  hardware: HardwareInventory | null,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): CaptionEngineDecision {
  const large = catalog.find((component) => component.id === "captions_large");
  return {
    installedTier: hardware?.recommended_caption_tier ?? "floor",
    largeRunsLiveHere: hardware?.gpus == null ? null : hardware.hardware_capable_caption_tier === "large-v3",
    largeObtainable: Boolean(large?.deliverable),
    largeSelectedByDefault: hardware
      ? defaultSelectedComponentIds(hardware, catalog).includes("captions_large")
      : false
  };
}

/** The live-captioning clause both screens spend, from the one fact. */
function liveCaptioningClause(decision: CaptionEngineDecision): string {
  if (decision.largeRunsLiveHere === null) {
    return "CivicCast could not check whether this station can run it during a meeting.";
  }
  return decision.largeRunsLiveHere
    ? "This station's graphics card can run it live, while the meeting is happening."
    : "It is too slow for live captioning on this station, so it captions recordings after the meeting instead.";
}

/**
 * The explanation shown under the large-engine row on the download plan.
 * Derived from {@link captionEngineDecision}, which is what makes it
 * impossible for this text to disagree with {@link recommendationSentence}.
 */
export function largeCaptionEngineExplanation(
  decision: CaptionEngineDecision,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): string {
  const live = liveCaptioningClause(decision);
  if (!decision.largeObtainable) {
    // Nothing to decide, so no size and no trade-off to weigh -- offering
    // either would be noise on a row that is only there to be honest about
    // what this release does not include.
    return `Not available to download in this release. ${live} A future update will make it available.`;
  }
  // F-22: the size and the cost of declining belong in the sentence that asks
  // for the decision, not only in the column at the far right of the row.
  const size = formatBytes(
    catalog.find((component) => component.id === "captions_large")?.placeholderSizeBytes ?? 0
  );
  if (decision.largeSelectedByDefault) {
    // 2026-08-15 owner ruling: capable hardware starts with the large engine
    // selected. The sentence must say so — "off unless you choose it" would
    // be false about the checked box sitting right next to it.
    return (
      `Selected for this station — ${size}. ${live} ` +
      "Untick it to skip the download; CivicCast still captions with the standard engine, " +
      "and you can add this one later at any time."
    );
  }
  return (
    `Optional, and off unless you choose it — ${size}. ${live} ` +
    "If you skip it, CivicCast still captions live meetings and recordings with the standard engine; " +
    "you can add this one later at any time."
  );
}

/**
 * THE ONE DECISION about the optional `cuda_runtime` component (GPU caption
 * acceleration), mirroring {@link CaptionEngineDecision}'s shape for the
 * SAME reason F-06 exists: the row's explanation and any other surface that
 * talks about this component must be derived from one fact, never a second
 * hand-written copy of the hardware condition that could drift from the
 * caption-engine decision it is coupled to.
 *
 * `cuda_runtime` is pre-selected under the EXACT same condition
 * `captions_large` is (`hardware_capable_caption_tier === "large-v3"`) --
 * see {@link defaultSelectedComponentIds}'s doc for why: a GPU capable of
 * running the large caption model live is the GPU this pack lets that model
 * actually use.
 */
export interface GpuAccelerationDecision {
  /** Whether the GPU acceleration pack can be downloaded at all in this release. */
  obtainable: boolean;
  /** Whether a fresh install starts out with the GPU acceleration pack selected. */
  selectedByDefault: boolean;
}

export function gpuAccelerationDecision(
  hardware: HardwareInventory | null,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): GpuAccelerationDecision {
  const component = catalog.find((entry) => entry.id === "cuda_runtime");
  return {
    obtainable: Boolean(component?.deliverable),
    selectedByDefault: hardware
      ? defaultSelectedComponentIds(hardware, catalog).includes("cuda_runtime")
      : false
  };
}

/**
 * The explanation shown under the GPU-acceleration row on the download plan.
 * Derived from {@link gpuAccelerationDecision}, the same F-22-survivor shape
 * {@link largeCaptionEngineExplanation} already takes: an undeliverable
 * component gets no size or trade-off to weigh (nothing to decide, so
 * offering either would be noise); a selected-by-default component says so,
 * with the size and the untick escape, never silently; an off-by-default but
 * obtainable component states the size and the cost of skipping.
 */
export function gpuAccelerationExplanation(
  decision: GpuAccelerationDecision,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): string {
  if (!decision.obtainable) {
    return "Not available to download in this release. A future update will make it available.";
  }
  const size = formatBytes(
    catalog.find((component) => component.id === "cuda_runtime")?.placeholderSizeBytes ?? 0
  );
  if (decision.selectedByDefault) {
    return (
      `Selected for this station — ${size}. This station's graphics card can run the caption engine. ` +
      "Untick it to skip the download; CivicCast still runs captions on this computer's processor, " +
      "and you can add this one later at any time."
    );
  }
  return (
    `Optional, and off unless you choose it — ${size}. If you skip it, CivicCast still runs captions ` +
    "on this computer's processor; you can add this one later at any time."
  );
}

/**
 * The one sentence screen 1 shows under the hardware facts.
 *
 * Distinct cases, because several of them used to collapse into one sentence
 * that was false in most of them (G011.1):
 *
 * 1. The graphics probe could not run (`gpus === null`) -- say so. The old
 *    copy asserted "This station has no dedicated graphics card", which is a
 *    claim about the machine, not about the probe.
 * 2. The hardware could run the quality engine live but that engine is not
 *    obtainable in this release -- say THAT, rather than telling the owner of
 *    a 4090 that their station has no dedicated graphics card.
 * 3. The hardware could run it live AND it is obtainable -- the case F-06 was
 *    captured in. The sentence now states whether it was actually selected
 *    instead of asserting "We've selected it for you" regardless (which was
 *    false whenever the component was not in the default set).
 * 4. There is a dedicated card, but not one that reaches the quality tier
 *    (an AMD/Intel card, or a small NVIDIA one) -- name the card's presence
 *    honestly instead of denying it.
 * 5. No dedicated card at all -- the original sentence, now only used when it
 *    is actually true.
 */
export function recommendationSentence(
  hardware: HardwareInventory,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): string {
  if (hardware.gpus === null) {
    return (
      "CivicCast could not check this computer's graphics card, so it is installing the standard " +
      "caption engine (Medium), which runs in real time on any supported CPU."
    );
  }
  const decision = captionEngineDecision(hardware, catalog);
  if (decision.largeRunsLiveHere) {
    if (!decision.largeObtainable) {
      return (
        "This station's graphics card could run the higher-quality caption engine live, but that " +
        "engine is not available to download in this release. CivicCast is installing the standard " +
        "caption engine (Medium), which runs in real time on this station."
      );
    }
    if (decision.largeSelectedByDefault) {
      return (
        "This station's graphics card can run the higher-quality caption engine live, and CivicCast " +
        "has selected it. You can uncheck it on the next screen."
      );
    }
    return (
      "This station's graphics card can run the higher-quality caption engine live. CivicCast " +
      "installs the standard caption engine (Medium); the next screen offers the higher-quality " +
      "one as an extra download."
    );
  }
  const hasDedicatedGpu = hardware.gpus.some((gpu) => gpu.dedicated_vram_mb > 0);
  if (!hasDedicatedGpu) {
    return "This station has no dedicated graphics card. We recommend the standard caption engine (Medium), which runs in real time on this CPU.";
  }
  return (
    "This station's graphics card is not one CivicCast can run the higher-quality caption engine " +
    "on. We recommend the standard caption engine (Medium), which runs in real time here."
  );
}

/**
 * Which components a fresh install starts out selecting: the required,
 * deliverable ones -- plus the large caption engine AND its GPU acceleration
 * pack when THIS machine's hardware can run them.
 *
 * History, both directions, so the next editor knows this line has moved
 * twice and why:
 *
 * F-22 (2026-08-01) removed the hardware-driven pre-tick of
 * `captions_large`, because at that time the component was NOT deliverable —
 * a newcomer arrived at a plan screen with a 3.1 GB download pre-ticked that
 * the backend could never drive (permanently "Waiting", `allDone` never
 * true), and a silently committed multi-gigabyte download is somebody
 * else's metered link.
 *
 * OWNER RULING (2026-08-15) reinstates the pre-tick, deliberately, now that
 * `captions_large` IS deliverable (enrolled in
 * `acquisition_catalog.rs::PRODUCTION_CATALOG_IDS` with pinned sources):
 * "the user should get the better caption model if the hardware supports
 * it." The G011.1 `deliverable` guard stays, so this can never re-create the
 * F-22 stall: an undeliverable component is never selected, whatever the
 * hardware says. The operator keeps the final word — the row renders as a
 * checked checkbox they can untick, and the machine-check sentence
 * (`recommendationSentence`'s `largeSelectedByDefault` branch) announces the
 * selection before the download screen.
 *
 * 2026-08-16 extends the SAME ruling to `cuda_runtime`: getting the better
 * caption model to actually run live needs the CUDA library that engine
 * loads, so a station capable of running it live is pre-selected for both
 * downloads together, under the identical condition and the identical
 * G011.1 guard -- never a second, looser gate for the second component.
 *
 * `hardware` is read for exactly one decision, reused for both components:
 * each joins the default set iff `hardware_capable_caption_tier ===
 * "large-v3"` (the existing >= 8 GB NVIDIA VRAM ladder in
 * `hardware_inventory.rs`) AND that component is deliverable. Every other
 * row remains hardware-independent.
 */
export function defaultSelectedComponentIds(
  hardware: HardwareInventory,
  catalog: readonly CatalogComponent[] = COMPONENT_CATALOG
): ComponentId[] {
  const selected = catalog
    .filter((component) => component.required && component.deliverable)
    .map((component) => component.id);
  const capableOfLargeV3 = hardware.hardware_capable_caption_tier === "large-v3";
  for (const id of ["captions_large", "cuda_runtime"] as const) {
    const component = catalog.find((entry) => entry.id === id);
    if (
      component?.deliverable &&
      !component.required &&
      capableOfLargeV3 &&
      !selected.includes(id)
    ) {
      selected.push(id);
    }
  }
  return selected;
}

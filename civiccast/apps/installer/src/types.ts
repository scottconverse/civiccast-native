// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

export type LaneStatus =
  | "loading"
  | "success"
  | "empty"
  | "error"
  | "partial"
  | "blocked"
  | "progress"
  | "cancelled"
  | "credential_gated"
  | "hardware_required"
  // An optional capability this install does not have (installer summary lane
  // status "unavailable"). Distinct from "blocked": nothing is waiting on the
  // operator to finish setup, and CivicCast runs without it -- so this status
  // must never offer a repair/continue affordance that cannot deliver.
  | "unavailable";

export interface InstallerLane {
  id: string;
  label: string;
  status: LaneStatus;
  ready: boolean;
  nextStep: string;
  detail: string;
}

export interface InstallerState {
  ready: boolean;
  /**
   * Mirrors `InstallerSummary.platform` (civiccast/installer/models.py).
   *
   * `"windows-native"` is the native Windows station -- CivicCast's own
   * supervisor-hosted control plane, which does not use WSL at all, and the
   * only Windows deployment this product ships today.
   *
   * `"windows-wsl2"` named the retired WSL2 deployment. Nothing in this
   * frontend renders a WSL-only affordance for it any more -- the "Set up
   * Windows helper" button and the platform lane's repair pass both routed
   * into main.rs's WSL bootstrap pipeline, which is gone. The value is kept
   * in the type only so a state file or cached progress a pre-native build
   * left on disk still type-checks; `withHonestNativePlatform` (api.ts)
   * corrects it to `"windows-native"` the moment a real native bridge is
   * present.
   */
  platform: "linux" | "macos" | "windows-native" | "windows-wsl2";
  operatorConsoleUrl?: string;
  lanes: InstallerLane[];
}

export type NativeGpuFacts = HardwareGpu;

// Returned by the `native_hardware_inventory` Tauri command
// (src-tauri/src/hardware_inventory.rs). Field names are snake_case,
// matching the Rust struct verbatim (no rename_all = "camelCase" on that
// command) -- the same convention InstallerProgress below already uses.
//
// EVERY MEASURED FIELD IS NULLABLE (G011.1). `null` means "this probe could
// not obtain a value on this machine", and the screen renders it as
// "Unavailable". Nothing in this interface may ever carry a stand-in number:
// the Rust side has no fallback value left to send, and the frontend has no
// mock left to substitute. See hardware_inventory.rs's HardwareInventory doc
// comment for the four fabrications this shape exists to make
// unrepresentable.
export interface NativeHardwareInventory {
  cpu_model: string | null;
  physical_cores: number | null;
  logical_cores: number | null;
  ram_gb: number | null;
  /**
   * `null` = the DXGI graphics probe could not run at all; `[]` = it ran and
   * this machine has no adapter with dedicated VRAM. Only the second licenses
   * the screen to say "No dedicated graphics card".
   */
  gpus: NativeGpuFacts[] | null;
  /** Free BYTES available to the caller on the install target's volume. */
  free_disk_bytes: number | null;
  /** The directory that free-space figure was taken on. */
  install_target: string | null;
  /** The tier that will actually be installed -- always one the production acquisition catalog can deliver. */
  recommended_caption_tier: RecommendedCaptionTier;
  /** The tier this hardware could RUN, before obtainability. Differs from the above only when the capable tier is not downloadable in this release. */
  hardware_capable_caption_tier: RecommendedCaptionTier;
}

export interface InstallerProgress {
  schema_version: number;
  current_lane_id: string;
  status: string;
  message: string;
  reboot_required: boolean;
  updated_at_unix: number;
  started_at_unix?: number;
  elapsed_seconds?: number;
  activity_current?: number;
  activity_total?: number;
  activity_phase?: string;
  operator_console_url?: string;
  resident_portal_url?: string;
  service_url?: string;
  /**
   * Component-download progress, written by the engine's ProgressObserver
   * (component_acquisition.rs) into this same polled installer-state JSON.
   * Optional because older engine builds (and the fallback local-progress
   * paths) never set it -- its absence means "no acquisition activity to
   * report", not an error.
   */
  acquisition?: AcquisitionState;
}

// ---------------------------------------------------------------------------
// Component acquisition (download experience) -- see
// component_acquisition.rs for the five typed AcquisitionError variants this
// mirrors, and download-ux-spec.md for the screen-by-screen behavior.
// ---------------------------------------------------------------------------

/**
 * Mirrors component_acquisition::AcquisitionError, snake_case for JSON.
 *
 * `disk_full` is NOT a catch-all for local write failures (chain H2): it is
 * reported only for a real storage-exhaustion OS error. `permission_denied`
 * and `write_failed` carry the causes that used to be misfiled under it --
 * a distinction that matters entirely here, because this `kind` is the ONLY
 * thing the operator-facing copy below is keyed off.
 */
export type AcquisitionErrorKind =
  | "network_failed"
  | "resume_invalid"
  | "hash_mismatch"
  | "disk_full"
  | "permission_denied"
  | "write_failed"
  | "source_not_found";

export interface AcquisitionComponentError {
  kind: AcquisitionErrorKind;
  /** Raw engine detail string -- never shown verbatim on screen (copy rule: no jargon). */
  detail: string;
}

export type AcquisitionComponentState =
  | "pending"
  | "found_locally"
  | "downloading"
  | "verifying"
  | "complete"
  /**
   * Stopped at the operator's request (G011.3). Deliberately its own state
   * rather than an `error` with an eighth `AcquisitionErrorKind`: nothing went
   * wrong, no remedy needs naming, and the row must offer Resume without any
   * of the red failure treatment. Partial bytes are kept on disk, so Resume
   * genuinely resumes.
   */
  | "canceled"
  | "error";

export interface AcquisitionComponentProgress {
  id: string;
  state: AcquisitionComponentState;
  bytes_done: number;
  bytes_total: number | null;
  elapsed_seconds: number;
  error?: AcquisitionComponentError;
}

export interface AcquisitionState {
  components: AcquisitionComponentProgress[];
}

// ---------------------------------------------------------------------------
// Native hardware inventory ("Checking this computer" screen)
// ---------------------------------------------------------------------------

/**
 * Exactly what hardware_inventory.rs's `vendor_name_for_pci_id` produces:
 * "NVIDIA", "AMD", "Intel", or `Unknown (0x____)` for an unrecognized PCI
 * vendor id. This used to be typed as a lowercase union ("nvidia" | "amd" |
 * ...) that the producing Rust code has never once emitted -- a contract the
 * wire never satisfied.
 */
export type GpuVendor = "NVIDIA" | "AMD" | "Intel" | (string & {});

export interface HardwareGpu {
  name: string;
  dedicated_vram_mb: number;
  vendor: GpuVendor;
}

/**
 * The two REAL caption tier ids, verbatim from the pinned registry
 * (civiccast/native/caption_tiers.py FLOOR_TIER_ID / LARGE_V3_TIER_ID,
 * mirrored in native_packs.rs): "floor" is the always-installed medium
 * engine; "large-v3" is the optional quality engine on capable hardware.
 * This is exactly what native_hardware_inventory's
 * recommended_caption_tier returns -- never a UI-local vocabulary.
 */
export type RecommendedCaptionTier = "floor" | "large-v3";

export type HardwareInventory = NativeHardwareInventory;

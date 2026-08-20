// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// Plain-English metadata for the "big components" the download-plan and
// downloading screens show. Copy follows download-ux-spec.md's copy rules:
// no jargon ("pack"/"manifest"/"SHA"), honest sizes, no exclamation marks.
//
// Sizes below are PLACEHOLDERS pending the real manifest, which supplies the
// exact measured byte count for each component at runtime (see
// download-ux-spec.md, screen 2: "Size in human units (measured, from the
// manifests -- never 'about')"). Every place that reads a size should prefer
// a measured size passed in from the manifest and fall back to this
// placeholder only until that value is available.

export type ComponentId =
  | "app_runtime"
  | "server_binaries"
  | "media_tools"
  | "captions_medium"
  | "captions_large"
  | "cuda_runtime"
  | "local_ai_model";

export interface CatalogComponent {
  id: ComponentId;
  /** Plain-English name shown on screen -- never a filename. */
  name: string;
  /** One sentence of purpose a city clerk understands. */
  purpose: string;
  /** Placeholder size in bytes -- see module doc comment. */
  placeholderSizeBytes: number;
  /** Required components are listed but not uncheckable. */
  required: boolean;
  /**
   * Whether a fresh install can actually DOWNLOAD this component -- i.e.
   * whether it is enrolled in `acquisition_catalog.rs`'s `production_catalog`,
   * the exact list `main.rs`'s `run_production_acquisition` iterates. Pinned
   * one-for-one against that file's `PRODUCTION_CATALOG_IDS` by
   * `tests/policy/test_hardware_inventory_policy.py`.
   *
   * Distinct from `required`, and the distinction is load-bearing (G011.1):
   * `captions_large` and `media_tools` are BOTH `required: false`, but for
   * completely different reasons -- one is a genuine operator choice, the
   * other is simply not obtainable in this release. Selecting a
   * non-deliverable component puts a row on the downloading screen that
   * nothing on the backend will ever drive: permanently "Waiting", with
   * `allDone` never becoming true.
   */
  deliverable: boolean;
  /** Extra explanation shown under the row for the one genuinely optional component. */
  optionalExplanation?: string;
}

const MB = 1024 * 1024;
const GB = 1024 * 1024 * 1024;

export const COMPONENT_CATALOG: readonly CatalogComponent[] = [
  {
    id: "app_runtime",
    name: "CivicCast application runtime",
    purpose:
      "The CivicCast program itself: the dashboard and meeting tools staff use every day.",
    placeholderSizeBytes: Math.round(482 * MB),
    required: true,
    deliverable: true
  },
  {
    id: "server_binaries",
    name: "Database & messaging services",
    purpose:
      "The local services CivicCast runs on this computer to store meetings and pass information between its parts.",
    placeholderSizeBytes: Math.round(94 * MB),
    required: true,
    deliverable: true
  },
  {
    id: "media_tools",
    name: "Video and audio tools",
    purpose:
      "The tools CivicCast uses to record a meeting, build the video file it publishes, and check that the file came out right.",
    // MEASURED, not a placeholder: the exact byte size of the built
    // native-ffmpeg-runtime.ccpack (scripts/build_native_ffmpeg_pack.py's
    // --report `pack_bytes`). Component packs are stored uncompressed for
    // byte-reproducibility, so this is also what actually crosses the wire.
    placeholderSizeBytes: 143_477_803,
    // This row is not downloaded by the first-run GUI because the private
    // native candidate stages the signed sidecar during bootstrap. It remains
    // absent from the public acquisition catalog until that asset is published
    // at the resolved release tag.
    // acquisition_catalog.rs's production_catalog() (Rust side) no longer
    // returns this component at all -- see that file's dated "defined but
    // NOT enrolled" doc section. required:false keeps this row out of
    // defaultSelectedComponentIds so a fresh install never selects a
    // component the backend cannot deliver. Flip back to true (and the
    // matching Rust-side one-line re-enable) once the pack is published.
    required: false,
    // Not in production_catalog() -- the pack is unpublished at the resolved
    // release tag, so a fresh install asking for it would get an HTTP 404.
    deliverable: false,
    optionalExplanation:
      "Installed with the signed CivicCast setup; no separate download is needed."
  },
  {
    id: "captions_medium",
    name: "Caption engine — Medium (recommended)",
    purpose: "Live captions for meetings as they happen. This is the standard engine and always installs.",
    placeholderSizeBytes: Math.round(1.5 * GB),
    required: true,
    deliverable: true
  },
  {
    id: "captions_large",
    name: "Caption engine — Large (optional)",
    purpose: "A higher-quality caption engine. On a capable graphics card it captions live; otherwise it captions recordings after the meeting.",
    placeholderSizeBytes: Math.round(3.1 * GB),
    required: false,
    // Enrolled in production_catalog() 2026-08-15 (owner ruling: a
    // hardware-capable station gets the better caption engine). Six pinned
    // HuggingFace files, same trust model as captions_medium -- see
    // acquisition_catalog.rs's module doc and
    // component_acquisition::caption_large_tier_file_sources.
    deliverable: true
    // NO optionalExplanation (F-06). This row's explanation is DERIVED, by
    // acquisition-progress.ts's largeCaptionEngineExplanation, from the same
    // captionEngineDecision the machine-check screen's sentence is derived
    // from. The fixed string that used to live here knew nothing about the
    // machine, so it sat one click after "can run the highest-quality caption
    // engine in real time" saying "too slow for live captioning on this
    // hardware" -- about the same engine, on the same station.
  },
  {
    id: "cuda_runtime",
    name: "GPU caption acceleration (optional)",
    purpose:
      "Lets the caption engine run on this computer's graphics card instead of its processor, so it can caption more meetings live.",
    placeholderSizeBytes: Math.round(1.3 * GB),
    required: false,
    // Enrolled in production_catalog() 2026-08-16 (owner ruling, same day as
    // captions_large's own: "the user should get the better caption model if
    // the hardware supports it", extended -- running it on the graphics card
    // needs the GPU library the caption runtime actually loads). A signed
    // pack (native-cuda-runtime.ccpack), same trust model as
    // app_runtime/server_binaries -- see acquisition_catalog.rs's module doc.
    deliverable: true
    // NO optionalExplanation (mirrors captions_large's own F-06 rationale).
    // This row's explanation is DERIVED, by acquisition-progress.ts's
    // gpuAccelerationExplanation, from the SAME hardware fact
    // captionEngineDecision already derives captions_large's explanation
    // from -- so the two rows can never disagree about whether this
    // station's graphics card qualifies.
  },
  {
    id: "local_ai_model",
    name: "Local AI model (summaries & translation)",
    purpose:
      "Generates meeting summaries and translations on this computer, without sending recordings anywhere else.",
    placeholderSizeBytes: Math.round(7.6 * GB),
    required: true,
    deliverable: true
  }
] as const;

export function catalogComponent(id: ComponentId): CatalogComponent {
  const found = COMPONENT_CATALOG.find((component) => component.id === id);
  if (!found) {
    throw new Error(`Unknown component id: ${id}`);
  }
  return found;
}

/**
 * The same lookup for an id that arrived over the wire, where the type system
 * cannot vouch for it.
 *
 * `AcquisitionComponentProgress.id` is `string`, because that is what a JSON
 * payload gives us. The downloading screen renders one row per component and
 * used to call {@link catalogComponent} directly with it -- which THROWS on an
 * id it does not know, inside `components.map(...)`, i.e. inside React's
 * render. The consequence is not a warning in a console nobody has open: the
 * downloading screen goes blank, mid-install, on the first run, with no way
 * forward.
 *
 * Today's Rust producer emits exactly the seven catalog ids
 * (`acquisition_catalog.rs`; `PRODUCTION_CATALOG_IDS` names six of them), so
 * this is not a live crash -- it is a crash waiting for someone to add an
 * eighth pack on the Rust side and ship it before the TypeScript union
 * catches up. Nothing enforces that ordering, and nothing was type-checking
 * this file at all until now.
 *
 * An unknown component degrades to a truthful row instead: the operator sees
 * it downloading, with its progress and its size, and no invented description.
 */
export function catalogComponentForWireId(id: string): CatalogComponent {
  const found = COMPONENT_CATALOG.find((component) => component.id === id);
  if (found) {
    return found;
  }
  return {
    id: id as ComponentId,
    name: "Additional component",
    purpose: "A part of CivicCast this installer version does not have a description for.",
    placeholderSizeBytes: 0,
    required: false,
    // The backend is already downloading it, whatever it is -- that is why a
    // row exists. Claiming otherwise would put the row in the permanently
    // "Waiting" state `deliverable: false` is for.
    deliverable: true
  };
}

// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { describe, expect, it } from "vitest";

import { COMPONENT_CATALOG } from "./components-catalog";
import {
  appendProgressSample,
  defaultSelectedComponentIds,
  diskSpaceCheck,
  emaBytesPerSecond,
  ETA_NOT_YET_MEASURED,
  etaSeconds,
  formatBytes,
  formatDuration,
  formatEta,
  isStalled,
  noBytesMovedYet,
  NO_BYTES_MOVED_THRESHOLD_SECONDS,
  planTotals,
  pollIntervalMs,
  presentAcquisitionError,
  recommendationSentence,
  type ProgressSample
} from "./acquisition-progress";
import type { AcquisitionComponentProgress, AcquisitionErrorKind, HardwareInventory } from "./types";

function hardware(overrides: Partial<HardwareInventory> = {}): HardwareInventory {
  return {
    cpu_model: "Generic x86_64 CPU",
    physical_cores: 8,
    logical_cores: 16,
    ram_gb: 16,
    gpus: [],
    free_disk_bytes: 120 * 1024 * 1024 * 1024,
    install_target: "C:\\Program Files",
    recommended_caption_tier: "floor",
    hardware_capable_caption_tier: "floor",
    ...overrides
  };
}

function componentProgress(overrides: Partial<AcquisitionComponentProgress> = {}): AcquisitionComponentProgress {
  return {
    id: "app_runtime",
    state: "pending",
    bytes_done: 0,
    bytes_total: 1000,
    elapsed_seconds: 0,
    ...overrides
  };
}

describe("emaBytesPerSecond", () => {
  it("returns null with fewer than two samples", () => {
    expect(emaBytesPerSecond([])).toBeNull();
    expect(emaBytesPerSecond([{ bytesDone: 0, atSeconds: 0 }])).toBeNull();
  });

  it("converges to the true rate for a constant-rate stream", () => {
    const samples: ProgressSample[] = [];
    for (let t = 0; t <= 20; t += 1) {
      samples.push({ bytesDone: t * 1_000_000, atSeconds: t });
    }
    const rate = emaBytesPerSecond(samples, 5);
    expect(rate).not.toBeNull();
    // A true EMA never fully reaches steady state, but 20s over a 5s window
    // should be within 1% of the real 1,000,000 B/s rate.
    expect(rate as number).toBeGreaterThan(990_000);
    expect(rate as number).toBeLessThan(1_010_000);
  });

  it("ignores non-positive time deltas instead of dividing by zero", () => {
    const samples: ProgressSample[] = [
      { bytesDone: 0, atSeconds: 0 },
      { bytesDone: 500, atSeconds: 0 }, // duplicate poll tick, dt = 0
      { bytesDone: 1000, atSeconds: 1 }
    ];
    const rate = emaBytesPerSecond(samples);
    expect(rate).not.toBeNull();
    expect(Number.isFinite(rate)).toBe(true);
  });

  it("reacts to a rate change within a few samples (not frozen at the first reading)", () => {
    const slow: ProgressSample[] = [
      { bytesDone: 0, atSeconds: 0 },
      { bytesDone: 100_000, atSeconds: 1 },
      { bytesDone: 200_000, atSeconds: 2 }
    ];
    const thenFast = [
      ...slow,
      { bytesDone: 5_200_000, atSeconds: 3 },
      { bytesDone: 10_200_000, atSeconds: 4 },
      { bytesDone: 15_200_000, atSeconds: 5 }
    ];
    const rateBefore = emaBytesPerSecond(slow) as number;
    const rateAfter = emaBytesPerSecond(thenFast) as number;
    expect(rateAfter).toBeGreaterThan(rateBefore * 3);
  });
});

describe("appendProgressSample + emaBytesPerSecond (regression: coarse shared clock)", () => {
  it(
    "REGRESSION -- timestamping samples off a once-a-second display clock silently produces a stuck " +
      "0 B/s: byte jumps land on a repeated stale timestamp (dt<=0, dropped), and every timestamp-" +
      "spanning pair ends up comparing two samples with the same byte count (found live in " +
      "AcquisitionFlow.tsx: DownloadingScreen used the `nowMillis` UI-tick state instead of Date.now()).",
    () => {
      // Mirrors the real sequence captured from the browser console: several
      // renders share ONE coarse timestamp while bytes_done actually climbs,
      // then the clock jumps and immediately "catches up" to the same value.
      let history: ProgressSample[] = [];
      const coarseClockPushes: Array<[bytes: number, atSeconds: number]> = [
        [0, 100],
        [0, 100],
        [50_000_000, 100],
        [50_000_000, 100],
        [100_000_000, 100],
        [100_000_000, 102], // clock finally ticks, but bytes_done hasn't moved since the last push yet
        [100_000_000, 102],
        [150_000_000, 102]
      ];
      for (const [bytesDone, atSeconds] of coarseClockPushes) {
        history = appendProgressSample(history, { bytesDone, atSeconds });
      }
      expect(emaBytesPerSecond(history)).toBe(0);
    }
  );

  it("the fix: timestamping every push with a fresh, distinct clock read yields the real rate", () => {
    let history: ProgressSample[] = [];
    for (let tick = 0; tick < 8; tick += 1) {
      history = appendProgressSample(history, { bytesDone: tick * 25_000_000, atSeconds: tick * 0.5 });
    }
    const rate = emaBytesPerSecond(history);
    expect(rate).not.toBeNull();
    // 25,000,000 bytes every 0.5s == 50,000,000 B/s steady state.
    expect(rate as number).toBeGreaterThan(45_000_000);
    expect(rate as number).toBeLessThan(55_000_000);
  });

  it("caps history to maxSamples", () => {
    let history: ProgressSample[] = [];
    for (let tick = 0; tick < 20; tick += 1) {
      history = appendProgressSample(history, { bytesDone: tick, atSeconds: tick }, 5);
    }
    expect(history).toHaveLength(5);
    expect(history[0].bytesDone).toBe(15);
  });
});

describe("etaSeconds", () => {
  it("is null when the rate is unknown or zero", () => {
    expect(etaSeconds(1000, null)).toBeNull();
    expect(etaSeconds(1000, 0)).toBeNull();
    expect(etaSeconds(1000, -5)).toBeNull();
  });

  it("is zero once nothing remains", () => {
    expect(etaSeconds(0, 500)).toBe(0);
    expect(etaSeconds(-10, 500)).toBe(0);
  });

  it("divides remaining bytes by the rate", () => {
    expect(etaSeconds(10_000, 1000)).toBe(10);
  });
});

describe("pollIntervalMs", () => {
  it("is 2000ms with no components", () => {
    expect(pollIntervalMs([])).toBe(2000);
  });

  it("is 2000ms when nothing is downloading or verifying", () => {
    expect(
      pollIntervalMs([componentProgress({ state: "pending" }), componentProgress({ id: "server_binaries", state: "complete" })])
    ).toBe(2000);
  });

  it("is 500ms when any component is downloading", () => {
    expect(
      pollIntervalMs([componentProgress({ state: "complete" }), componentProgress({ id: "server_binaries", state: "downloading" })])
    ).toBe(500);
  });

  it("is 500ms while a component is verifying (the hash check right after the last byte)", () => {
    expect(pollIntervalMs([componentProgress({ state: "verifying" })])).toBe(500);
  });
});

describe("presentAcquisitionError", () => {
  const kinds: AcquisitionErrorKind[] = [
    "network_failed",
    "hash_mismatch",
    "source_not_found",
    "resume_invalid",
    "disk_full",
    "permission_denied",
    "write_failed"
  ];

  it("has a distinct, non-jargon line for every typed engine error", () => {
    const lines = kinds.map((kind) => presentAcquisitionError(kind).line);
    expect(new Set(lines).size).toBe(kinds.length);
    for (const line of lines) {
      expect(line.toLowerCase()).not.toMatch(/pack|manifest|sha|nsis|provisioning/);
      expect(line).not.toMatch(/!/);
    }
  });

  it("never phrases a failure as the operator's fault", () => {
    for (const kind of kinds) {
      const { line } = presentAcquisitionError(kind);
      expect(line.toLowerCase()).not.toMatch(/you (broke|caused|did)/);
    }
  });

  it("only network_failed claims Retry truly resumes (the engine keeps the .partial only for that case)", () => {
    expect(presentAcquisitionError("network_failed").retryResumes).toBe(true);
    expect(presentAcquisitionError("hash_mismatch").retryResumes).toBe(false);
    expect(presentAcquisitionError("source_not_found").retryResumes).toBe(false);
    expect(presentAcquisitionError("resume_invalid").retryResumes).toBe(false);
    expect(presentAcquisitionError("disk_full").retryResumes).toBe(false);
    expect(presentAcquisitionError("permission_denied").retryResumes).toBe(false);
    expect(presentAcquisitionError("write_failed").retryResumes).toBe(false);
  });

  // Chain H2. R7's durable installer-state recorded
  // {"kind":"disk_full","detail":"PermissionDenied"} for both required
  // components and the operator was shown a free-up-disk-space screen on a
  // station with 175.3 GiB free. `detail` is never displayed, so the ONLY
  // thing standing between a permission failure and a truthful screen is the
  // kind -- and this copy.
  it("only ever tells the operator the drive is full for the disk_full kind", () => {
    for (const kind of kinds) {
      const { line } = presentAcquisitionError(kind);
      const claimsNoSpace = /free space|free up|enough space|out of space/i.test(line);
      expect(claimsNoSpace).toBe(kind === "disk_full");
    }
  });

  it("tells a permission failure what actually happened and names a remedy that can work", () => {
    const { line } = presentAcquisitionError("permission_denied");
    expect(line.toLowerCase()).toMatch(/wouldn't let|permission|blocked/);
    expect(line).toMatch(/Retry/);
    expect(line.toLowerCase()).toMatch(/administrator|security software/);
  });

  it("maps the exact three spec-given lines verbatim", () => {
    expect(presentAcquisitionError("network_failed").line).toBe("The connection dropped. Nothing is damaged.");
    expect(presentAcquisitionError("hash_mismatch").line).toBe(
      "The downloaded file didn't match its signature and was discarded."
    );
    expect(presentAcquisitionError("source_not_found").line).toBe(
      "The download server didn't have this file. This is our problem, not yours."
    );
  });
});

describe("isStalled", () => {
  it("is honest about motion: not stalled at or under the 10s threshold", () => {
    expect(isStalled(9)).toBe(false);
    expect(isStalled(10)).toBe(false);
  });

  it("reports stalled once the threshold is exceeded", () => {
    expect(isStalled(11)).toBe(true);
    expect(isStalled(60)).toBe(true);
  });

  it("honors a custom threshold", () => {
    expect(isStalled(4, 3)).toBe(true);
    expect(isStalled(2, 3)).toBe(false);
  });
});

describe("formatBytes / formatDuration / formatEta", () => {
  it("formats bytes in human units", () => {
    expect(formatBytes(0)).toBe("0 KB");
    expect(formatBytes(500)).toBe("1 KB");
    expect(formatBytes(94 * 1024 * 1024)).toBe("94 MB");
    expect(formatBytes(1.5 * 1024 * 1024 * 1024)).toBe("1.5 GB");
  });

  it("formats durations without ever mentioning jargon", () => {
    expect(formatDuration(5)).toBe("5 seconds");
    expect(formatDuration(1)).toBe("1 second");
    expect(formatDuration(90)).toBe("1 min 30 sec");
    expect(formatDuration(3600)).toBe("1 hr");
    expect(formatDuration(3660)).toBe("1 hr 1 min");
  });

  it("shows an explicit not-yet-measured marker instead of a fake number before the rate is known", () => {
    expect(formatEta(null)).toBe(ETA_NOT_YET_MEASURED);
    expect(formatEta(null)).not.toMatch(/\d/);
    expect(formatEta(30)).toBe("30 seconds");
  });
});

describe("planTotals", () => {
  it("sums only the selected line items", () => {
    const totals = planTotals(
      [
        { id: "app_runtime", selected: true, sizeBytes: 1000 },
        { id: "captions_large", selected: false, sizeBytes: 5000 },
        { id: "local_ai_model", selected: true, sizeBytes: 2000 }
      ],
      null
    );
    expect(totals.totalBytes).toBe(3000);
  });

  it("leaves the ETA unset until the link-speed probe lands (size-only display first)", () => {
    const totals = planTotals([{ id: "app_runtime", selected: true, sizeBytes: 1000 }], null);
    expect(totals.totalEtaSeconds).toBeNull();
  });

  it("fills in the ETA once a rate is known", () => {
    const totals = planTotals([{ id: "app_runtime", selected: true, sizeBytes: 10_000 }], 1000);
    expect(totals.totalEtaSeconds).toBe(10);
  });
});

describe("diskSpaceCheck", () => {
  it("blocks and names both numbers when free space is short (spec's own example)", () => {
    const result = diskSpaceCheck(3.1 * 1024 * 1024 * 1024, 9.4 * 1024 * 1024 * 1024);
    expect(result.blocked).toBe(true);
    expect(result.message).toBe("This drive doesn't have enough free space: needs 9.4 GB free, this drive has 3.1 GB.");
  });

  it("does not block when free space exactly covers the requirement", () => {
    expect(diskSpaceCheck(10 * 1024 * 1024 * 1024, 10 * 1024 * 1024 * 1024).blocked).toBe(false);
  });

  it("does not block with headroom to spare", () => {
    const result = diskSpaceCheck(500 * 1024 * 1024 * 1024, 9.4 * 1024 * 1024 * 1024);
    expect(result.blocked).toBe(false);
    expect(result.message).toBeNull();
  });
});

describe("recommendationSentence", () => {
  it("recommends Medium on a CPU-only box", () => {
    expect(recommendationSentence(hardware({ gpus: [] }))).toMatch(/no dedicated graphics card/);
  });
});

describe("defaultSelectedComponentIds", () => {
  it("selects only the required components on a CPU-only box", () => {
    const ids = defaultSelectedComponentIds(hardware({ recommended_caption_tier: "floor" }));
    expect(ids).toEqual(COMPONENT_CATALOG.filter((component) => component.required).map((component) => component.id));
    expect(ids).not.toContain("captions_large");
    // media_tools remains unselected only while its native FFmpeg pack is
    // unpublished at the resolved release tag.
    expect(ids).not.toContain("media_tools");
  });

  // 2026-08-15 owner ruling: a large-v3-capable box starts with the large
  // caption engine selected (the operator can untick it). This deliberately
  // reverses F-22's hardware-independence, now that captions_large is
  // deliverable — see defaultSelectedComponentIds' doc for both directions.
  it("selects the large caption engine by default on a large-v3-capable box", () => {
    const ids = defaultSelectedComponentIds(
      hardware({
        gpus: [{ name: "NVIDIA GeForce RTX 4070", dedicated_vram_mb: 12_000, vendor: "NVIDIA" }],
        recommended_caption_tier: "large-v3",
        hardware_capable_caption_tier: "large-v3"
      })
    );
    expect(ids).toContain("captions_large");
  });

  // G011.1's invariant survives the owner ruling: an UNDELIVERABLE component
  // is never selected, whatever the hardware says — that is the guard that
  // prevented the permanently-"Waiting" row, and it must hold even for a
  // capable box if captions_large is ever un-enrolled again.
  it("never selects a component the production acquisition catalog cannot deliver", () => {
    const withLargeUndeliverable = COMPONENT_CATALOG.map((component) =>
      component.id === "captions_large" ? { ...component, deliverable: false } : component
    );
    const ids = defaultSelectedComponentIds(
      hardware({
        gpus: [{ name: "NVIDIA GeForce RTX 4070", dedicated_vram_mb: 12_000, vendor: "NVIDIA" }],
        recommended_caption_tier: "large-v3",
        hardware_capable_caption_tier: "large-v3"
      }),
      withLargeUndeliverable
    );
    expect(ids).not.toContain("captions_large");
  });
});

// ---------------------------------------------------------------------------
// G011.1: no fabricated hardware numbers anywhere
// ---------------------------------------------------------------------------

describe("diskSpaceCheck with an unavailable free-space reading", () => {
  // RED: the guard took a plain `number`, so an unavailable probe had to be
  // coerced to SOME number before it could be evaluated at all -- 0 blocks a
  // healthy machine, and the 120 GB frontend mock passed a full one.
  it("reports the check as unknown rather than silently passing or blocking", () => {
    const result = diskSpaceCheck(null, 9.4 * 1024 * 1024 * 1024);
    expect(result.blocked).toBe(false);
    expect(result.known).toBe(false);
    expect(result.message).toMatch(/could not/i);
  });

  it("still names both real numbers when the reading IS available and short", () => {
    const result = diskSpaceCheck(3.1 * 1024 * 1024 * 1024, 9.4 * 1024 * 1024 * 1024);
    expect(result.blocked).toBe(true);
    expect(result.known).toBe(true);
  });
});

describe("recommendationSentence honesty (G011.1)", () => {
  it("does not claim a box has no dedicated graphics card when it plainly has one", () => {
    const sentence = recommendationSentence(
      hardware({
        gpus: [{ name: "AMD Radeon RX 7900 XTX", dedicated_vram_mb: 24_576, vendor: "AMD" }],
        recommended_caption_tier: "floor",
        hardware_capable_caption_tier: "floor"
      })
    );
    expect(sentence).not.toMatch(/no dedicated graphics card/);
  });

  it("says why the quality engine is not being installed when it is capable but unobtainable", () => {
    // The capable-but-unobtainable honesty sentence, preserved with a
    // catalog override now that captions_large is deliverable for real.
    const withLargeUndeliverable = COMPONENT_CATALOG.map((component) =>
      component.id === "captions_large" ? { ...component, deliverable: false } : component
    );
    const sentence = recommendationSentence(
      hardware({
        gpus: [{ name: "NVIDIA GeForce RTX 4090", dedicated_vram_mb: 24_576, vendor: "NVIDIA" }],
        recommended_caption_tier: "floor",
        hardware_capable_caption_tier: "large-v3"
      }),
      withLargeUndeliverable
    );
    expect(sentence).toMatch(/not available/i);
  });

  it("announces the default selection on a capable box now that the engine is obtainable", () => {
    const sentence = recommendationSentence(
      hardware({
        gpus: [{ name: "NVIDIA GeForce RTX 4090", dedicated_vram_mb: 24_576, vendor: "NVIDIA" }],
        recommended_caption_tier: "large-v3",
        hardware_capable_caption_tier: "large-v3"
      })
    );
    expect(sentence).toMatch(/has selected it/i);
    expect(sentence).toMatch(/uncheck/i);
  });

  it("says nothing about graphics at all when the graphics probe returned nothing usable", () => {
    const sentence = recommendationSentence(hardware({ gpus: null }));
    expect(sentence).not.toMatch(/no dedicated graphics card/);
    expect(sentence).toMatch(/could not/i);
  });

  // F-24: TESTER1-class machine with iGPU + sub-8GB NVIDIA dGPU must not
  // contradict the inventory by claiming "no dedicated graphics card".
  it("does not contradict the inventory on a real TESTER1-class machine (iGPU + sub-8GB NVIDIA dGPU)", () => {
    const hw = hardware({
      gpus: [
        { name: "Intel(R) UHD Graphics 630", dedicated_vram_mb: 0, vendor: "Intel" },
        { name: "NVIDIA GeForce GTX 1660 Ti", dedicated_vram_mb: 6144, vendor: "NVIDIA" }
      ],
      recommended_caption_tier: "floor",
      hardware_capable_caption_tier: "floor"
    });
    const sentence = recommendationSentence(hw);
    expect(sentence).not.toMatch(/no dedicated graphics card/);
    expect(sentence).toMatch(/graphics card is not one CivicCast can run/i);
  });
});

describe("noBytesMovedYet", () => {
  function pending(overrides: Partial<AcquisitionComponentProgress> = {}): AcquisitionComponentProgress {
    return {
      id: "app_runtime",
      state: "pending",
      bytes_done: 0,
      bytes_total: 1_000,
      elapsed_seconds: 0,
      ...overrides
    };
  }

  const past = NO_BYTES_MOVED_THRESHOLD_SECONDS + 1;

  it("reports the all-pending, zero-byte screen once the threshold passes", () => {
    expect(noBytesMovedYet([pending(), pending({ id: "server_binaries" })], past)).toBe(true);
  });

  it("stays quiet inside the threshold, where a slow start is legitimate", () => {
    expect(noBytesMovedYet([pending()], NO_BYTES_MOVED_THRESHOLD_SECONDS)).toBe(false);
  });

  it("stays quiet as soon as any row has left pending", () => {
    expect(noBytesMovedYet([pending(), pending({ id: "server_binaries", state: "downloading" })], past)).toBe(
      false
    );
  });

  it("stays quiet as soon as any bytes have moved, even with every row still pending", () => {
    expect(noBytesMovedYet([pending({ bytes_done: 1 })], past)).toBe(false);
  });

  it("never fires over an empty component list", () => {
    expect(noBytesMovedYet([], past)).toBe(false);
  });
});

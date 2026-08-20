// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//
// Non-dismissible posture banner for the public-safety (EAS) console (S11c, master
// Sec. 7 honesty line). It states plainly what CivicCast is and is NOT: it displays
// CAP/IPAWS/NWS/AMBER public-safety information on-channel; it is not an EAS device,
// does not relay the FCC Part 11 signal, and generates no SAME tones. There is no
// close button by design — the disclaimer is permanent.

/** Permanent, non-dismissible statement of the EAS posture. */
export function EasPostureBanner() {
  return (
    <section
      aria-label="Public-safety display posture"
      role="status"
      aria-live="polite"
      className="rounded-md p-4 text-sm"
      style={{ background: 'var(--cc-info-soft)', border: '2px solid var(--cc-info)' }}
    >
      <div
        className="text-[10px] font-semibold uppercase tracking-wider"
        style={{ color: 'var(--cc-ink-3)' }}
      >
        Public-safety display — not an EAS device
      </div>
      <p className="m-0 mt-1 max-w-3xl" style={{ color: 'var(--cc-ink-2)' }}>
        CivicCast ingests and displays public-safety alerts (CAP/IPAWS, NWS, and AMBER) as
        on-channel information — a crawl, an overlay, or an operator-confirmed slate. It is
        <strong> not an EAS device</strong>: it does not relay the FCC Part&nbsp;11 EAS signal,
        generates no SAME headers, and never automatically pre-empts programming. The mandatory
        Part&nbsp;11 relay remains the cable operator&rsquo;s certified headend equipment.
      </p>
    </section>
  )
}

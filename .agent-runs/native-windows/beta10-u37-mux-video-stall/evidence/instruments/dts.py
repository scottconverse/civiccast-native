"""U37 -- the mux output's own video DTS: is it emitted at all, and is it monotone?

Reads mpegtsmux's output (out.ts) directly.  The mux writes a DTS in a PES header
only when it differs from that header's PTS, so a frozen DTS shows up as a burst of
PTS+DTS headers all carrying one value while the PTS advances.

Usage:  python dts.py <out.ts> [<out.ts> ...]

Ground truth: TS PES PTS/DTS are 90 kHz ticks; mpegtsmux's own output base is 3600 s,
so the printed running time is ticks/90000 - 3600.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

import tsraw

_PID_NAMES = {0x41: "video", 0x42: "audio", 0x43: "captions"}


def pts_dts(payload: bytes) -> tuple[float | None, float | None, int]:
    """(pts, dts, PTS_DTS_flags) in running-time seconds; dts None when absent."""
    if len(payload) < 9 or payload[0] != 0 or payload[1] != 0 or payload[2] != 1:
        return None, None, -1
    flags = payload[7] >> 6
    if flags not in (0b10, 0b11) or len(payload) < 14:
        return None, None, flags

    def stamp(b: bytes) -> float:
        v = (
            ((b[0] >> 1) & 0x07) << 30
            | (b[1] << 22)
            | ((b[2] >> 1) << 15)
            | (b[3] << 7)
            | (b[4] >> 1)
        )
        return v / 90000.0 - 3600.0

    pts = stamp(payload[9:14])
    dts = stamp(payload[14:19]) if flags == 0b11 and len(payload) >= 19 else None
    return pts, dts, flags


def hexdump(path: Path, pid_wanted: int, lo: int, hi: int) -> None:
    """Raw first bytes of selected PES payloads -- the DTS field verbatim."""
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    print(f"== {path}  pid {_PID_NAMES.get(pid_wanted, hex(pid_wanted))}  #{lo}..{hi}")
    n = 0
    for pid, pusi, payload in tsraw.packets(data):
        if pid != pid_wanted or not pusi or pid not in streams:
            continue
        if lo <= n <= hi:
            _, _, flags = pts_dts(payload)
            print(f"   per-pid #{n}  PTS_DTS_flags={flags:02b}  hdr_len={payload[8]}")
            print("      " + " ".join(f"{b:02x}" for b in payload[:24]))
        n += 1


def report(path: Path) -> None:
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    stamps: dict[int, list[tuple[float, float | None]]] = {pid: [] for pid in streams}
    for pid, pusi, payload in tsraw.packets(data):
        if pid not in streams or not pusi:
            continue
        pts, dts, _flags = pts_dts(payload)
        if pts is not None:
            stamps[pid].append((pts, dts))

    print(f"== {path}")
    for pid in sorted(stamps):
        rows = stamps[pid]
        if not rows:
            continue
        name = _PID_NAMES.get(pid, hex(pid))
        carry = [i for i, (_, dts) in enumerate(rows) if dts is not None]
        back = [i for i in range(1, len(rows)) if rows[i][0] < rows[i - 1][0]]
        print(
            f"   {name:<9} {len(rows):>4} PES  PTS+DTS {len(carry):>4}  PTS-only "
            f"{len(rows) - len(carry):>4}  PTS backsteps {len(back)}"
        )
        if carry:
            vals = sorted({round(rows[i][1], 6) for i in carry})
            below = [i for i in carry if rows[i][0] < vals[-1]]
            print(f"      distinct DTS values: {len(vals)}  min={vals[0]:.6f} max={vals[-1]:.6f}")
            print(
                f"      DTS-carrying frames: #{carry[0]}.. #{carry[-1]} of "
                f"{len(rows)}  (count {len(carry)}); their PTS "
                f"{rows[carry[0]][0]:.6f}..{rows[carry[-1]][0]:.6f}"
            )
            print(
                f"      of those, frames whose PTS is below the frozen DTS "
                f"{vals[-1]:.6f}: {len(below)} / {len(carry)}"
                f"  (DTS-PTS 0.011..{vals[-1] - rows[carry[0]][0]:.6f}s)"
            )
            if carry[-1] + 1 < len(rows):
                nxt = rows[carry[-1] + 1]
                print(
                    f"      first PTS-only after: #{carry[-1] + 1} "
                    f"PTS {nxt[0]:.6f} -> {len(rows) - carry[-1] - 1} PTS-only "
                    f"frames to end"
                )
        for i in back:
            prev = rows[i - 1][0]
            print(
                f"      PTS backstep #{i}: {prev:.6f} -> {rows[i][0]:.6f}  "
                f"backstep={prev - rows[i][0]:.6f}s"
            )


_args = sys.argv[1:]
if "--hex" in _args:
    _i = _args.index("--hex")
    hexdump(
        Path(_args[_i + 1]),
        int(_args[_i + 2], 0),
        int(_args[_i + 3]),
        int(_args[_i + 4]),
    )
    _args = _args[:_i]

for _arg in _args:
    report(Path(_arg))

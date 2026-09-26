"""U37 -- ground truth of the AIR timeline, parsed straight out of the recorded
mux output `out.ts`, with NO GStreamer pipeline (a live demux can block on a
file whose streams never reach EOS, which is what hung the first attempt).

188-byte transport packets, PAT -> PMT -> elementary PIDs, PES PTS from the
optional PES header at each payload-unit-start.  Per stream: sort the PTS and
report the largest step.

  * ~21.3 ms (audio AAC frame) / ~33.3 ms (30 fps video) is continuity,
  * ~1.024 s of audio is a hole (48 AAC frames),
  * a video step of ~0.714 s is the outgoing media's own tail shape (its video
    ends that early); a video step of ~9.4 s is the pre-fix re-dating.

Usage: python tsraw.py <out.ts> [...]
"""

from __future__ import annotations

import sys
from pathlib import Path

PKT = 188
SYNC = 0x47


def packets(data: bytes):
    for off in range(0, len(data) - PKT + 1, PKT):
        if data[off] != SYNC:
            continue
        b1, b2, b3 = data[off + 1], data[off + 2], data[off + 3]
        pid = ((b1 & 0x1F) << 8) | b2
        pusi = bool(b1 & 0x40)
        afc = (b3 >> 4) & 0x03
        cursor = off + 4
        if afc in (2, 3):
            cursor += 1 + data[cursor]
        if afc in (0, 2) or cursor >= off + PKT:
            continue
        yield pid, pusi, data[cursor : off + PKT]


def psi_sections(data: bytes, pid: int):
    """Reassemble section payloads on one PID (single-section packets only)."""
    for _pid, pusi, payload in packets(data):
        if _pid != pid or not pusi or not payload:
            continue
        pointer = payload[0]
        sec = payload[pointer + 1 :]
        if sec:
            yield sec


def pmt_pids(data: bytes, pmt_pid: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for sec in psi_sections(data, pmt_pid):
        if len(sec) < 12 or sec[0] != 0x02:
            continue
        prog_info_len = ((sec[10] & 0x0F) << 8) | sec[11]
        i = 12 + prog_info_len
        end = 3 + ((sec[1] & 0x0F) << 8 | sec[2]) - 4
        while i + 4 < min(end, len(sec)):
            stream_type = sec[i]
            es_pid = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
            es_info_len = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
            out.setdefault(es_pid, f"0x{stream_type:02x}")
            i += 5 + es_info_len
    return out


def pes_pts(payload: bytes) -> int | None:
    if len(payload) < 14 or payload[0] != 0 or payload[1] != 0 or payload[2] != 1:
        return None
    if (payload[7] & 0x80) == 0:  # no PTS
        return None
    p = payload[9:14]
    return (
        ((p[0] >> 1) & 0x07) << 30
        | p[1] << 22
        | ((p[2] >> 1) & 0x7F) << 15
        | p[3] << 7
        | (p[4] >> 1)
    )


def main() -> int:
    for arg in sys.argv[1:]:
        path = Path(arg)
        data = path.read_bytes()
        pmt_pid = None
        for sec in psi_sections(data, 0):
            if len(sec) >= 12 and sec[0] == 0x00:
                pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
                break
        streams = pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
        pts: dict[int, list[int]] = {pid: [] for pid in streams}
        for pid, pusi, payload in packets(data):
            if pid in pts and pusi:
                v = pes_pts(payload)
                if v is not None:
                    pts[pid].append(v)
        print(f"# {path.name} size={len(data)} pmt_pid={pmt_pid} streams={streams}")
        for pid, values in sorted(pts.items()):
            if not values:
                print(f"  0x{pid:04x} ({streams[pid]}): no PTS")
                continue
            uniq = sorted(set(values))
            steps = sorted(
                ((uniq[i] - uniq[i - 1], uniq[i - 1], uniq[i]) for i in range(1, len(uniq))),
                reverse=True,
            )
            regress = sum(1 for i in range(1, len(values)) if values[i] < values[i - 1])
            print(
                f"  0x{pid:04x} ({streams[pid]}): n={len(values)} uniq={len(uniq)} "
                f"order_regressions={regress} first={uniq[0] / 90000:.9f} last={uniq[-1] / 90000:.9f}"
            )
            for step, a, b in steps[:3]:
                print(f"      step {step / 90000:.6f}s  {a / 90000:.9f} -> {b / 90000:.9f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

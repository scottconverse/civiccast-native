"""U37 -- print the actual backward PES steps (emission index + before/after running times)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw

_PID_NAMES = {0x41: "video", 0x42: "audio", 0x43: "captions"}


def clock(rt: float) -> str:
    h = int(rt // 3600)
    m = int((rt % 3600) // 60)
    s = rt % 60
    return f"{h}:{m:02d}:{s:09.6f}"


for path_s in sys.argv[1:]:
    path = Path(path_s)
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    order: list[tuple[int, float]] = []
    for pid, pusi, payload in tsraw.packets(data):
        if pid in streams and pusi:
            v = tsraw.pes_pts(payload)
            if v is not None:
                order.append((pid, v / 90000.0 - 3600.0))
    last: dict[int, float] = {}
    n: dict[int, int] = {}
    print(f"== {path}  emissions={len(order)}")
    for i, (pid, rt) in enumerate(order):
        n[pid] = n.get(pid, 0) + 1
        if pid in last and rt < last[pid]:
            name = _PID_NAMES.get(pid, hex(pid))
            print(
                f"   {name}: emitted #{i} (per-pid #{n[pid]}) "
                f"{clock(last[pid])} -> {clock(rt)}   backstep={last[pid] - rt:.6f}s"
            )
        last[pid] = rt

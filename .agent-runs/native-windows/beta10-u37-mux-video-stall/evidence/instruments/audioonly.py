"""U37 -- longest unbroken audio-only run in the mux's emission order, per recording."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw  # noqa: E402

for path_s in sys.argv[1:]:
    path = Path(path_s)
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    order = []
    for pid, pusi, payload in tsraw.packets(data):
        if pid in streams and pusi and tsraw.pes_pts(payload) is not None:
            order.append(pid)
    best = 0
    best_at = (-1, -1)
    run = 0
    start = 0
    for i, pid in enumerate(order):
        if pid == 0x42:
            if run == 0:
                start = i
            run += 1
            if run > best:
                best = run
                best_at = (start, i)
        else:
            run = 0
    v = sum(1 for p in order if p == 0x41)
    a = sum(1 for p in order if p == 0x42)
    print(
        f"== {path}  emissions={len(order)} video={v} audio={a}  "
        f"longest_audio_only_run={best} (#{best_at[0]}..##{best_at[1]})"
    )

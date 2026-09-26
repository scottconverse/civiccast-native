"""U37 -- why does x1's lag read 0.000000?  Inspect its PMT pids and first emissions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw  # noqa: E402

SEP = chr(92)

for path_s in ("x1" + SEP + "run1" + SEP + "out.ts", "x2" + SEP + "run2" + SEP + "out.ts"):
    path = Path(path_s)
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    n = 0
    seq = []
    for pid, pusi, payload in tsraw.packets(data):
        if pid in streams and pusi:
            v = tsraw.pes_pts(payload)
            if v is not None:
                n += 1
                if len(seq) < 12:
                    seq.append((hex(pid), round(v / 90000.0 - 3600.0, 6)))
    print(f"== {path}  pmt_pid={pmt_pid} streams={ {hex(k): v for k, v in streams.items()} }"
          f"  pusi_pts={n}")
    for pid, rt in seq:
        print(f"     {pid}  rt={rt}")

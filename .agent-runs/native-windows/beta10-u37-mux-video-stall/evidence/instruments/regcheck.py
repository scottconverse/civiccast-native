"""U37 -- per-PID PTS ORDER REGRESSION scan of a recorded out.ts (no mux internals).

For every PES the mux emitted, per pid: count steps where the running time goes
BACKWARDS, and report the largest single backward step. A collapse shows up as
regress>0 with a multi-second maxstep.

Usage: python regcheck.py out.ts [out.ts ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw  # noqa: E402

_PID_NAMES = {0x41: "video", 0x42: "audio", 0x43: "captions"}


def main() -> int:
    for path_s in sys.argv[1:]:
        path = Path(path_s)
        data = path.read_bytes()
        pmt_pid = None
        for sec in tsraw.psi_sections(data, 0):
            if len(sec) >= 12 and sec[0] == 0x00:
                pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
                break
        streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
        pid_set = set(streams)
        last: dict[int, float] = {}
        regress: dict[int, int] = {}
        worst: dict[int, float] = {}
        n: dict[int, int] = {}
        for pid, pusi, payload in tsraw.packets(data):
            if pid in pid_set and pusi:
                v = tsraw.pes_pts(payload)
                if v is None:
                    continue
                rt = v / 90000.0 - 3600.0
                n[pid] = n.get(pid, 0) + 1
                if pid in last and rt < last[pid]:
                    step = last[pid] - rt
                    regress[pid] = regress.get(pid, 0) + 1
                    if step > worst.get(pid, 0.0):
                        worst[pid] = step
                last[pid] = rt
        verdict = "COLLAPSE" if any(worst.get(p, 0.0) > 1.0 for p in worst) else "ok"
        print(f"== {path}  {verdict}")
        for pid in sorted(last):
            name = _PID_NAMES.get(pid, hex(pid))
            print(
                f"   {name:<8} n={n.get(pid, 0):<5} regress={regress.get(pid, 0):<4} "
                f"worst_backstep={worst.get(pid, 0.0):.6f}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

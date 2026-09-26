"""U37 -- cross each run's declared outgoing-tail ends against its own out.ts verdict.

The deferred switch logs ``rebase-reference ... ends=[video=,audio=]``: the running
time at which the outgoing leg's video and audio each stop.  That shape is the
*boundary condition*; whether the mux froze on it is a separate fact, recorded in the
capture.  Printing the two side by side is what shows the freeze to be a race rather
than a property of the offset.

Usage: python endsshapes.py <run-dir> [<run-dir> ...]
       (a run dir holds worker.log and out.ts, e.g. .../x4dbg/run3)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw

_ENDS = re.compile(r"ends=\[video=([\d.]+),audio=([\d.]+)\]")


def verdict(out_ts: Path) -> str:
    """Largest backward per-PID PES step in the capture, as regcheck.py reports it."""
    data = out_ts.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    pid_set = set(streams)
    last: dict[int, float] = {}
    worst: dict[int, float] = {}
    for pid, pusi, payload in tsraw.packets(data):
        if pid not in pid_set or not pusi:
            continue
        v = tsraw.pes_pts(payload)
        if v is None:
            continue
        rt = v / 90000.0 - 3600.0
        if pid in last and rt < last[pid]:
            step = last[pid] - rt
            worst[pid] = max(worst.get(pid, 0.0), step)
        last[pid] = rt
    return f"worst_backstep={max(worst.values(), default=0.0):.6f}s"


def main() -> int:
    for arg in sys.argv[1:]:
        run = Path(arg)
        log = run / "worker.log"
        out_ts = run / "out.ts"
        if not log.is_file() or not out_ts.is_file():
            print(f"{run}  (no worker.log / out.ts)")
            continue
        shapes = sorted(set(_ENDS.findall(log.read_text(encoding="utf-8", errors="replace"))))
        ends = " ".join(f"ends=[video={v},audio={a}]" for v, a in shapes)
        print(f"{run.parent.name}/{run.name:<12} {verdict(out_ts):<26} {ends}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

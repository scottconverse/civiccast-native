"""U37 -- measure the inter-stream AIRING lag from the mux's OWN recorded output.

For every PES the mux emits (in emission order), the emitting pid's airing
frontier becomes that buffer's running time; the lag of that pid at that moment
is the leading frontier minus its own.  Reports, per pid: max lag, and how many
emissions were more than 1.0/1.5/2.0/3.0/5.0 s behind.

Usage: python lag.py out.ts [out.ts ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import tsraw

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
        order: list[tuple[int, float]] = []
        for pid, pusi, payload in tsraw.packets(data):
            if pid in pid_set and pusi:
                v = tsraw.pes_pts(payload)
                if v is not None:
                    order.append((pid, v / 90000.0 - 3600.0))
        frontier: dict[int, float] = {}
        worst: dict[int, tuple[float, int]] = {}
        counts: dict[int, dict[float, int]] = {}
        for i, (pid, rt) in enumerate(order):
            frontier[pid] = rt
            lead = max(frontier.values())
            lag = lead - rt
            name = _PID_NAMES.get(pid, hex(pid))
            if lag > worst.get(pid, (0.0, -1))[0]:
                worst[pid] = (lag, i)
            for bound in (1.0, 1.5, 2.0, 3.0, 5.0):
                if lag > bound:
                    counts.setdefault(pid, {}).setdefault(bound, 0)
                    counts[pid][bound] += 1
        print(f"== {path}  emissions={len(order)}")
        for pid in sorted(frontier):
            lag, idx = worst.get(pid, (0.0, -1))
            name = _PID_NAMES.get(pid, hex(pid))
            c = counts.get(pid, {})
            tail = " ".join(f">{b}:{c.get(b, 0)}" for b in (1.0, 1.5, 2.0, 3.0, 5.0))
            print(f"   {name:<8} max_lag={lag:.6f}s at emission #{idx}   {tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

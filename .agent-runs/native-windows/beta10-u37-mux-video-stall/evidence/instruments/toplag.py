"""U37 -- top healthy lags, and the base/candidate split of the healthy set."""

from __future__ import annotations

import re
from pathlib import Path

SEP = chr(92)
CAND = {("x1", "run1"), ("x1", "run2")} | {
    ("x2", f"run{i}") for i in (1, 2, 3)
} | {("x4green", f"run{i}") for i in range(1, 7)} | {
    ("x4lag", f"run{i}") for i in range(1, 7)
} | {("x4pc", "run1")}

lines = Path(__file__).with_name("lag-all.txt").read_text(encoding="utf-8").splitlines()
cur = None
rows = []
for ln in lines:
    if ln.startswith("=="):
        cur = ln.split("==")[1].split("emissions=")[0].strip()
    elif "max_lag=" in ln:
        rows.append(
            (cur, ln.split()[0], float(re.search(r"max_lag=([\d.]+)s", ln).group(1)))
        )

healthy = [r for r in rows if r[2] <= 2.0]
print("healthy rows:", len(healthy), "of", len(rows))
print()
print("top 6 healthy lags:")
for cur, name, lag in sorted(healthy, key=lambda r: -r[2])[:6]:
    parts = cur.split(SEP)
    side = "cand" if (parts[0], parts[1]) in CAND else "base"
    print(f"   {lag:.6f}s  {side}  {cur} ({name})")
print()
for side in ("base", "cand"):
    sel = [r for r in healthy if (r[0].split(SEP)[0], r[0].split(SEP)[1]) in CAND] == [] or side
for side, pred in (("candidate", True), ("base", False)):
    sel = [
        r
        for r in healthy
        if ((r[0].split(SEP)[0], r[0].split(SEP)[1]) in CAND) is pred
    ]
    if sel:
        w = max(sel, key=lambda r: r[2])
        print(f"{side:<10} healthy rows={len(sel):<3} worst={w[2]:.6f}s @ {w[0]} ({w[1]})")

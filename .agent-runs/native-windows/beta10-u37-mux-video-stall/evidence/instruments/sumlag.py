"""U37 -- summarise lag-all.txt into the report's authoritative figures.

Usage:  python sumlag.py [lag-all.txt]     (defaults to the sibling file)"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

SEP = chr(92)  # backslash

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("lag-all.txt")
lines = src.read_text(encoding="utf-8").splitlines()
cur = None
rows = []
for ln in lines:
    if ln.startswith("=="):
        cur = ln.split("==")[1].split("emissions=")[0].strip()
    elif "max_lag=" in ln:
        name = ln.split()[0]
        lag = float(re.search(r"max_lag=([\d.]+)s", ln).group(1))
        over1 = int(re.search(r">1\.0:(\d+)", ln).group(1))
        over2 = int(re.search(r">2\.0:(\d+)", ln).group(1))
        over5 = int(re.search(r">5\.0:(\d+)", ln).group(1))
        rows.append((cur, name, lag, over1, over2, over5))

print("total pid-rows:", len(rows))
per_tree: dict[str, list] = defaultdict(list)
for r in rows:
    per_tree[r[0].split(SEP)[0]].append(r)
print()
for t in sorted(per_tree):
    worst = max(per_tree[t], key=lambda r: r[2])
    tot = sum(r[3] for r in per_tree[t])
    print(
        f"{t:<10} rows={len(per_tree[t]):<3} worst_lag={worst[2]:.6f} @{worst[0]}"
        f"  sum_over1.0={tot}"
    )

healthy = [r for r in rows if r[2] <= 2.0]
w = max(healthy, key=lambda r: r[2])
print()
print("healthy pid-rows:", len(healthy))
print("worst healthy:", f"{w[2]:.6f}s @ {w[0]} ({w[1]})")
print("healthy rows with any emission >1.0s:", [r for r in healthy if r[3] > 0])
print()
bad = sorted([r for r in rows if r[2] > 2.0], key=lambda r: -r[2])
print("rows lagging >2.0s:", len(bad))
for r in bad:
    print(f"   {r[0]:<22} {r[1]:<8} max_lag={r[2]:.6f}s >1.0:{r[3]} >2.0:{r[4]} >5.0:{r[5]}")

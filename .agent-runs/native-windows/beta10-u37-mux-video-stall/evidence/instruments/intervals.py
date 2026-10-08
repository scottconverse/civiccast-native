import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
INT = re.compile(
    r"CTRL output: (\d+) buffers \(\+(\d+)\)(.*?)\[mux-in ([\d.]+)s: video=\+(\d+) audio=\+(\d+)\]"
)
lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
prev = None
i = 0
for i, ln in enumerate(lines):
    m = INT.match(ln)
    if not m:
        continue
    src = int(m.group(1))
    v = int(m.group(5))
    a = int(m.group(6))
    itv = m.group(4)
    if prev is not None:
        d = src - prev
        if v > 20 and d <= a * 1.05 and d < (v + a) * 0.75:
            ref = ""
            for j in range(i - 1, max(0, i - 3000), -1):
                if "rebase-reference" in lines[j]:
                    ref = lines[j].strip()[:150]
                    break
                if INT.match(lines[j]):
                    break
            print(f"line {i + 1}: itv={itv} src_d=+{d} video=+{v} audio=+{a} sum={v + a} | {ref}")
    prev = src
print("total interval lines:", sum(1 for line in lines if INT.match(line)))

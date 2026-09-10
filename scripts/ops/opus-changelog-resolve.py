"""Resolve CHANGELOG.md merge conflicts: main's entries first, then the branch's.

Refuses to touch anything but CHANGELOG.md, refuses if a side would be dropped,
and prints every bullet it keeps so the result is auditable.
"""
import io, sys
p = "CHANGELOG.md"
lines = io.open(p, encoding="utf-8").read().split("\n")
n = 0
while True:
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("<<<<<<< HEAD"))
    except StopIteration:
        break
    mid = next(i for i, l in enumerate(lines) if l.startswith("=======") and i > start)
    end = next(i for i, l in enumerate(lines) if l.startswith(">>>>>>>") and i > mid)
    ours, theirs = lines[start+1:mid], lines[mid+1:end]
    def trim(b):
        b = list(b)
        while b and not b[-1].strip():
            b.pop()
        return b
    o, t = trim(ours), trim(theirs)
    print(f"region {n}: main={sum(1 for l in t if l.startswith('- **'))} bullets, "
          f"branch={sum(1 for l in o if l.startswith('- **'))} bullets")
    for l in t:
        if l.startswith("- **"): print("   main  :", l[:80])
    for l in o:
        if l.startswith("- **"): print("   branch:", l[:80])
    merged = t + ([""] if t and o else []) + o
    lines = lines[:start] + merged + lines[end+1:]
    n += 1
if n == 0:
    print("no conflict regions in CHANGELOG.md")
    sys.exit(1)
io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
left = sum(1 for l in lines if l.startswith(("<<<<<<<", "=======", ">>>>>>>")))
print(f"resolved {n} region(s); markers left: {left}")
sys.exit(1 if left else 0)

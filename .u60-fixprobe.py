# SPDX-License-Identifier: Apache-2.0
# U60 scratch: locate the relay log's cluster-1 packet inside the fixture.
import json
import subprocess
import sys

FF = r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"
BASE = (
    r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight"
    r"\fixtures\C10-education-2222"
)

target = int(sys.argv[1]) if len(sys.argv) > 1 else 187802917
lo_seg = int(sys.argv[2]) if len(sys.argv) > 2 else 1036
hi_seg = int(sys.argv[3]) if len(sys.argv) > 3 else 1052

for s in range(lo_seg, hi_seg + 1):
    path = BASE + "\\seg%09d.ts" % s
    cmd = [FF, "-v", "error", "-select_streams", "a", "-show_packets", "-of", "json", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("seg%09d ERR %s" % (s, r.stderr.strip()[:120]))
        continue
    rows = [(int(x["pts"]), int(x["dts"]), int(x["size"])) for x in json.loads(r.stdout)["packets"]]
    if not rows:
        print("seg%09d no audio packets" % s)
        continue
    lo = min(r0 for r0, _, _ in rows)
    hi = max(r0 for r0, _, _ in rows)
    bad = [r0 for r0 in rows if r0[0] != r0[1]]
    hit = "  <== COVERS TARGET" if lo <= target <= hi else ""
    print("seg%09d n=%d pts[%d..%d] pts!=dts=%d%s" % (s, len(rows), lo, hi, len(bad), hit))
    for b in bad:
        print("      pts=%d dts=%d size=%d" % b)

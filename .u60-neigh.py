import json, subprocess
FF = r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"
BASE = (r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight"
        r"\fixtures\C10-education-2222")
for seg, idx in ((1043, 49), (1049, 33)):
    path = BASE + "\seg%09d.ts" % seg
    r = subprocess.run([FF, "-v", "error", "-select_streams", "a", "-show_packets",
                        "-of", "json", path], capture_output=True, text=True)
    rows = [(int(x["pts"]), int(x["dts"]), int(x["size"]))
            for x in json.loads(r.stdout)["packets"]]
    print("=== seg%09d audio, rows %d..%d (the rewind is at idx=%d) ===" % (seg, idx-3, idx+3, idx))
    for i in range(max(0, idx-3), min(len(rows), idx+4)):
        mark = "  <== REWIND" if i == idx else ""
        print("  idx=%3d pts=%d dts=%d size=%d%s" % (i, rows[i][0], rows[i][1], rows[i][2], mark))
    print()

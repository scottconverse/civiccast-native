# SPDX-License-Identifier: Apache-2.0
# U60 scratch: full fixture scan for reordered PTS (a "rewind") on both streams.
# Reads a FIXTURE COPY only; nothing under live-hls is opened.
import json
import subprocess
import sys

FF = r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"
BASE = (
    r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight"
    r"\fixtures\C10-education-2222"
)
LO, HI = 1013, 1101


def packets(path, stream):
    cmd = [
        FF, "-v", "error", "-select_streams", stream,
        "-show_packets", "-of", "json", path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [
        (int(x["pts"]), int(x["dts"]), int(x["size"]))
        for x in json.loads(r.stdout).get("packets", [])
    ]


def main() -> int:
    total_audio = total_video = 0
    rewinds = 0
    pts_ne_dts = 0
    sizes = []
    for s in range(LO, HI + 1):
        path = BASE + "\\seg%09d.ts" % s
        for stream, tag in (("a", "audio"), ("v", "video")):
            rows = packets(path, stream)
            if rows is None:
                print("seg%09d %s ERR" % (s, tag))
                continue
            if tag == "audio":
                total_audio += len(rows)
                sizes.append((s, len(rows), rows[0][2] if rows else -1, rows[-1][2] if rows else -1))
            else:
                total_video += len(rows)
            for i in range(1, len(rows)):
                if rows[i][0] < rows[i - 1][0]:
                    rewinds += 1
                    print(
                        "REWIND seg%09d %s idx=%d pts %d -> %d (%+d ticks = %+.1f ms) "
                        "size=%d"
                        % (
                            s, tag, i, rows[i - 1][0], rows[i][0],
                            rows[i][0] - rows[i - 1][0],
                            (rows[i][0] - rows[i - 1][0]) / 90.0,
                            rows[i][2],
                        )
                    )
            for p, d, _sz in rows:
                if p != d:
                    pts_ne_dts += 1
                    print("PTS!=DTS seg%09d %s pts=%d dts=%d" % (s, tag, p, d))
    print()
    print("segments scanned      : %d" % (HI - LO + 1))
    print("audio packets         : %d" % total_audio)
    print("video packets         : %d" % total_video)
    print("backward PTS steps    : %d" % rewinds)
    print("packets with pts!=dts : %d" % pts_ne_dts)
    print()
    print("first/last audio packet size per segment (13 = silent slate audio):")
    for s, n, first, last in sizes:
        print("  seg%09d n=%3d first=%4d last=%4d" % (s, n, first, last))
    return 0


if __name__ == "__main__":
    sys.exit(main())

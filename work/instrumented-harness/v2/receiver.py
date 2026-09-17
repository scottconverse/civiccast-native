"""Receive-path harness: capture raw TS bytes with monotonic arrival timestamps.

Design (per review):
  - ONE UDP socket bound to the caption loopback, SOLE reader (no competing bind)
  - append received datagrams to capture.ts verbatim (raw bytes preserved)
  - record (monotonic_ns, wall_iso, byte_offset, datagram_len) per datagram
  - write an index so we can later associate any media PTS with an ARRIVAL time
  - does NOT throttle the producer and does NOT reinterpret mux PTS as wall time
"""

import datetime
import json
import pathlib
import socket
import sys
import time

OUT = None
TS = None
IDX = None
META = None


def main(port=23201, duration=None, bind_host="127.0.0.1", label="probe", outdir=None):
    global OUT, TS, IDX, META
    OUT = (
        pathlib.Path(outdir)
        if outdir
        else pathlib.Path(__file__).resolve().parent / f"run-{int(time.time())}"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    TS = OUT / "capture.ts"
    IDX = OUT / "arrival-index.jsonl"
    META = OUT / "run-meta.json"
    print("OUTDIR", OUT)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    s.bind((bind_host, port))
    s.settimeout(1.0)
    t_start_mono = time.monotonic()
    t_start_wall = datetime.datetime.now().isoformat()
    offset = 0
    packets = 0
    with TS.open("wb") as fh, IDX.open("w", encoding="utf-8") as ix:
        while True:
            if duration is not None and (time.monotonic() - t_start_mono) >= duration:
                break
            try:
                data, _addr = s.recvfrom(65536)
            except TimeoutError:
                continue
            mono = time.monotonic_ns()
            wall = datetime.datetime.now().isoformat()
            fh.write(data)
            ix.write(
                json.dumps({"mono_ns": mono, "wall": wall, "offset": offset, "len": len(data)})
                + "\n"
            )
            offset += len(data)
            packets += 1
    META.write_text(
        json.dumps(
            {
                "label": label,
                "port": port,
                "bind": bind_host,
                "start_mono_ns": int(t_start_mono * 1e9),
                "start_wall": t_start_wall,
                "end_wall": datetime.datetime.now().isoformat(),
                "bytes": offset,
                "packets": packets,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"captured {packets} datagrams, {offset} bytes")


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else None
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    lbl = sys.argv[3] if len(sys.argv) > 3 else "probe"
    main(duration=dur, label=lbl, outdir=outdir)

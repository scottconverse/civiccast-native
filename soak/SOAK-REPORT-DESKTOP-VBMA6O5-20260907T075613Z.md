# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T075613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 29.5 h of 2
- egress probes: 60, failing: 60
- heartbeats: 171
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 35000): cpu%= cpu_seconds_total=0.09375 rss_mb=21.1
- python (pid 45040): cpu%=29.84 cpu_seconds_total=30188.28125 rss_mb=1833.9
- python (pid 47576): cpu%= cpu_seconds_total=8.671875 rss_mb=778.9
- python (pid 47968): cpu%= cpu_seconds_total=8.65625 rss_mb=777.4

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=2092, relaunches_total=59, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45212, relaunches_total=58, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26448, relaunches_total=59, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

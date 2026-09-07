# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T092612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 31 h of 2
- egress probes: 63, failing: 63
- heartbeats: 174
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 27684): cpu%= cpu_seconds_total=0.015625 rss_mb=19.8
- python (pid 32200): cpu%= cpu_seconds_total=33.984375 rss_mb=755.6
- python (pid 33580): cpu%= cpu_seconds_total=22.5 rss_mb=768.9
- python (pid 37608): cpu%= cpu_seconds_total=14.21875 rss_mb=764.9
- python (pid 45040): cpu%=29.14 cpu_seconds_total=31865.9375 rss_mb=1836.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3110; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21976, relaunches_total=62, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3622; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32200, relaunches_total=61, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=STARTING, engine=, pid=, relaunches_total=61, relaunched_this_cycle=False, last_errors=GStreamer playout worker child exited non-zero; relaunching encoder. Last child stderr: CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | System.Object[]

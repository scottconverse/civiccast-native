# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T142612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 60 h of 2
- egress probes: 121, failing: 121
- heartbeats: 232
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 36384): cpu%= cpu_seconds_total=0.03125 rss_mb=16.4
- python (pid 29656): cpu%= cpu_seconds_total=4.1875 rss_mb=774.1
- python (pid 37664): cpu%= cpu_seconds_total=2.140625 rss_mb=772.7
- python (pid 45040): cpu%=24.48 cpu_seconds_total=61841.9375 rss_mb=1853.4

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=STARTING, engine=, pid=, relaunches_total=119, relaunched_this_cycle=False, last_errors=GStreamer playout worker child exited non-zero; relaunching encoder. Last child stderr: CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37664, relaunches_total=118, relaunched_this_cycle=True, last_errors=System.Object[]
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3094; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37996, relaunches_total=119, relaunched_this_cycle=True, last_errors=System.Object[]

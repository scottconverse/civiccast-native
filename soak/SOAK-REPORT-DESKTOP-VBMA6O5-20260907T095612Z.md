# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T095612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 31.5 h of 2
- egress probes: 64, failing: 64
- heartbeats: 175
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 46380): cpu%= cpu_seconds_total=0.015625 rss_mb=25
- python (pid 38012): cpu%= cpu_seconds_total=14.578125 rss_mb=764.4
- python (pid 40652): cpu%= cpu_seconds_total=12.3125 rss_mb=778.9
- python (pid 43116): cpu%= cpu_seconds_total=4.015625 rss_mb=773.1
- python (pid 45040): cpu%=29.17 cpu_seconds_total=32391.09375 rss_mb=1835

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2353; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43116, relaunches_total=63, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3574; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40652, relaunches_total=62, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3632; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38012, relaunches_total=62, relaunched_this_cycle=True, last_errors=System.Object[]

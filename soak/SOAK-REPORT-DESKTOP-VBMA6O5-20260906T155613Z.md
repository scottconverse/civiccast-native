# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T155613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 13.5 h of 2
- egress probes: 28, failing: 28
- heartbeats: 139
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 32316): cpu%= cpu_seconds_total=1.78125 rss_mb=768.8
- python (pid 39928): cpu%= cpu_seconds_total=50.640625 rss_mb=463
- python (pid 45040): cpu%=28.96 cpu_seconds_total=17274.734375 rss_mb=1832.2
- python (pid 45960): cpu%= cpu_seconds_total=14.1875 rss_mb=757.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39928, relaunches_total=27, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3635; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40648, relaunches_total=26, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4200; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42192, relaunches_total=27, relaunched_this_cycle=True, last_errors=

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T160624Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 7 h of 2
- egress probes: 16, failing: 14
- heartbeats: 92
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=215.9 cpu_seconds_total=71603.5625 rss_mb=1036.1
- python (pid 36972): cpu%= cpu_seconds_total=46.34375 rss_mb=852.3
- python (pid 38304): cpu%= cpu_seconds_total=26.015625 rss_mb=6496
- python (pid 40332): cpu%= cpu_seconds_total=18.140625 rss_mb=6034.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1253; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=34272, relaunches_total=11, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3643; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=38304, relaunches_total=10, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3746; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=24028, relaunches_total=12, relaunched_this_cycle=True, last_errors=

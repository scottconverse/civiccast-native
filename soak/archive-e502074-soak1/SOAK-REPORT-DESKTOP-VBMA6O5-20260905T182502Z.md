# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T182502Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 9.31 h of 2
- egress probes: 18, failing: 16
- heartbeats: 96
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 25260): cpu%= cpu_seconds_total=1377.515625 rss_mb=962
- python (pid 26048): cpu%= cpu_seconds_total=35.90625 rss_mb=2685.4
- python (pid 27940): cpu%= cpu_seconds_total=111.734375 rss_mb=820.2
- python (pid 42128): cpu%=-0.2 cpu_seconds_total=38.046875 rss_mb=3142.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=26048, relaunches_total=13, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3613; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=29204, relaunches_total=12, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=27940, relaunches_total=14, relaunched_this_cycle=True, last_errors=

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T123620Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 3.5 h of 2
- egress probes: 9, failing: 7
- heartbeats: 85
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=238.64 cpu_seconds_total=42893.78125 rss_mb=1030.5
- python (pid 22460): cpu%= cpu_seconds_total=51.390625 rss_mb=3106.7
- python (pid 28000): cpu%= cpu_seconds_total=21.46875 rss_mb=3186.1
- python (pid 29484): cpu%= cpu_seconds_total=25.546875 rss_mb=6791.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3633; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=29484, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3106; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=39200, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=21604, relaunches_total=5, relaunched_this_cycle=True, last_errors=

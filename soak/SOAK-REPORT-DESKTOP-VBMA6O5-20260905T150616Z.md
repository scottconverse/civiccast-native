# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T150616Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 6 h of 2
- egress probes: 14, failing: 12
- heartbeats: 90
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=226.61 cpu_seconds_total=63715.28125 rss_mb=1041
- python (pid 30416): cpu%= cpu_seconds_total=50.8125 rss_mb=6798.2
- python (pid 36576): cpu%= cpu_seconds_total=74 rss_mb=3903.8
- python (pid 39644): cpu%= cpu_seconds_total=229 rss_mb=2457.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=36576, relaunches_total=9, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=, pid=30416, relaunches_total=8, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=33124, relaunches_total=10, relaunched_this_cycle=True, last_errors=

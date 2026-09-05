# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T153622Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 6.5 h of 2
- egress probes: 15, failing: 13
- heartbeats: 91
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=221.35 cpu_seconds_total=67713.484375 rss_mb=990.9
- python (pid 8136): cpu%= cpu_seconds_total=110.703125 rss_mb=4991.9
- python (pid 31732): cpu%= cpu_seconds_total=17.984375 rss_mb=6785.7
- python (pid 43556): cpu%= cpu_seconds_total=159.359375 rss_mb=1808.6

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=, pid=8136, relaunches_total=10, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=21948, relaunches_total=9, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2040; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=30140, relaunches_total=11, relaunched_this_cycle=True, last_errors=

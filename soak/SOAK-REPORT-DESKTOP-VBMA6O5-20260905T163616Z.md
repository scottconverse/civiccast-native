# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T163616Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 7.5 h of 2
- egress probes: 17, failing: 15
- heartbeats: 93
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=215.7 cpu_seconds_total=75469.375 rss_mb=1052.7
- python (pid 19924): cpu%= cpu_seconds_total=31.78125 rss_mb=5772.6
- python (pid 31860): cpu%= cpu_seconds_total=72.9375 rss_mb=708.4
- python (pid 42128): cpu%= cpu_seconds_total=50.984375 rss_mb=6418

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=19924, relaunches_total=12, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=42128, relaunches_total=11, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=25248, relaunches_total=13, relaunched_this_cycle=True, last_errors=

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T103628Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 1.5 h of 2
- egress probes: 5, failing: 4
- heartbeats: 81
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 13940): cpu%= cpu_seconds_total=0.046875 rss_mb=24.3
- python (pid 4764): cpu%=282.29 cpu_seconds_total=24174.1875 rss_mb=1870.9
- python (pid 13092): cpu%= cpu_seconds_total=84.15625 rss_mb=349.8
- python (pid 13420): cpu%=49.85 cpu_seconds_total=1440.625 rss_mb=372.1
- python (pid 16700): cpu%=57.99 cpu_seconds_total=3207.265625 rss_mb=383.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=24449; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=13420, relaunches_total=1, relaunched_this_cycle=False, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=56572; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19148, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=42962; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=13092, relaunches_total=2, relaunched_this_cycle=True, last_errors=

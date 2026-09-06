# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T062612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 4 h of 2
- egress probes: 9, failing: 9
- heartbeats: 120
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 26908): cpu%= cpu_seconds_total=26.90625 rss_mb=749.5
- python (pid 29384): cpu%= cpu_seconds_total=21.828125 rss_mb=767.6
- python (pid 45040): cpu%=16.37 cpu_seconds_total=9505.453125 rss_mb=1824.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29384, relaunches_total=8, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41992, relaunches_total=8, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3244; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21912, relaunches_total=8, relaunched_this_cycle=True, last_errors=

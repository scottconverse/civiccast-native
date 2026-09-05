# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T221612Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 1.12 h of 2
- egress probes: 3, failing: 2
- heartbeats: 104
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 24172): cpu%= cpu_seconds_total=12.703125 rss_mb=396.3
- python (pid 30824): cpu%= cpu_seconds_total=11.40625 rss_mb=386.3
- python (pid 44056): cpu%=16.68 cpu_seconds_total=8282.765625 rss_mb=970

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=13909; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40808, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=27108; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=37268, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=44914; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=8144, relaunches_total=2, relaunched_this_cycle=True, last_errors=

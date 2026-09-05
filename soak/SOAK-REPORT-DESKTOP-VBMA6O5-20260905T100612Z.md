# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T100612Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 1 h of 2
- egress probes: 4, failing: 3
- heartbeats: 80
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 556): cpu%= cpu_seconds_total=502.125 rss_mb=343.2
- python (pid 4764): cpu%=284.62 cpu_seconds_total=19049.984375 rss_mb=1898.4
- python (pid 13420): cpu%= cpu_seconds_total=535.671875 rss_mb=383
- python (pid 16700): cpu%=47.9 cpu_seconds_total=2154.703125 rss_mb=365.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=98913; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=13420, relaunches_total=1, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=96273; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=16700, relaunches_total=0, relaunched_this_cycle=False, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=122690; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=556, relaunches_total=1, relaunched_this_cycle=True, last_errors=

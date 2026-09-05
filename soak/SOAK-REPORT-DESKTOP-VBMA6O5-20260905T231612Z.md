# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T231612Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 2.12 h of 2
- egress probes: 5, failing: 4
- heartbeats: 106
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 41080): cpu%=56.9 cpu_seconds_total=1446 rss_mb=476.9
- python (pid 43780): cpu%= cpu_seconds_total=788.234375 rss_mb=175
- python (pid 44056): cpu%=11.19 cpu_seconds_total=8761.265625 rss_mb=965
- python (pid 48020): cpu%=48.16 cpu_seconds_total=984.40625 rss_mb=243.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=121790; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=48020, relaunches_total=3, relaunched_this_cycle=False, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=122170; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=43780, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=41968; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=41080, relaunches_total=3, relaunched_this_cycle=False, last_errors=

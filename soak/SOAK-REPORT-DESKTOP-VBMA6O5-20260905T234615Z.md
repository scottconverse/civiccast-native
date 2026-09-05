# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T234615Z

- soak start (UTC): 2026-09-05T21:08:51.9581138Z
- elapsed: 2.62 h of 2
- egress probes: 6, failing: 5
- heartbeats: 107
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 35640): cpu%= cpu_seconds_total=0.25 rss_mb=22.1
- python (pid 28036): cpu%= cpu_seconds_total=231.28125 rss_mb=6447.6
- python (pid 41080): cpu%=59.22 cpu_seconds_total=2513.71875 rss_mb=296.6
- python (pid 41700): cpu%= cpu_seconds_total=24.109375 rss_mb=6786.3
- python (pid 44056): cpu%=11.49 cpu_seconds_total=8968.390625 rss_mb=205.3

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41104, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41700, relaunches_total=5, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=16769; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=41080, relaunches_total=3, relaunched_this_cycle=False, last_errors=

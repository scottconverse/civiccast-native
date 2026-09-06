# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T125613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 10.5 h of 2
- egress probes: 22, failing: 22
- heartbeats: 133
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 44324): cpu%= cpu_seconds_total=0.0625 rss_mb=21.6
- python (pid 27708): cpu%= cpu_seconds_total=17.703125 rss_mb=762.5
- python (pid 42220): cpu%= cpu_seconds_total=20.453125 rss_mb=766.7
- python (pid 45040): cpu%=38.95 cpu_seconds_total=14499.78125 rss_mb=1828

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=763; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=7808, relaunches_total=21, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25228, relaunches_total=20, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1914; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22252, relaunches_total=21, relaunched_this_cycle=True, last_errors=

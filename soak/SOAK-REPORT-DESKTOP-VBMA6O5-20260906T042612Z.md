# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T042612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 2 h of 2
- egress probes: 5, failing: 5
- heartbeats: 116
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 45416): cpu%= cpu_seconds_total=0.09375 rss_mb=24.4
- python (pid 14696): cpu%= cpu_seconds_total=9.65625 rss_mb=274.8
- python (pid 16704): cpu%= cpu_seconds_total=16.03125 rss_mb=279.8
- python (pid 22284): cpu%= cpu_seconds_total=4.890625 rss_mb=220.7
- python (pid 45040): cpu%=16.01 cpu_seconds_total=8253.53125 rss_mb=1828.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=33226; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=22284, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=31607; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42908, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9900, relaunches_total=4, relaunched_this_cycle=True, last_errors=

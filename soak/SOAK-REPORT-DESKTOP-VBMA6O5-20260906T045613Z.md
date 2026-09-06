# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T045613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 2.5 h of 2
- egress probes: 6, failing: 6
- heartbeats: 117
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 44260): cpu%= cpu_seconds_total=0.25 rss_mb=22.8
- python (pid 14208): cpu%= cpu_seconds_total=6.40625 rss_mb=775
- python (pid 31796): cpu%= cpu_seconds_total=11.296875 rss_mb=779
- python (pid 39312): cpu%= cpu_seconds_total=8.796875 rss_mb=779.2
- python (pid 45040): cpu%=13.25 cpu_seconds_total=8492.140625 rss_mb=1824.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14208, relaunches_total=5, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2744; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14104, relaunches_total=5, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28096, relaunches_total=5, relaunched_this_cycle=True, last_errors=

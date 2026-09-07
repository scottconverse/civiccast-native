# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T212612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 43 h of 2
- egress probes: 87, failing: 87
- heartbeats: 198
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 33076): cpu%= cpu_seconds_total=0.015625 rss_mb=24.7
- python (pid 14628): cpu%= cpu_seconds_total=4.4375 rss_mb=774.7
- python (pid 26080): cpu%= cpu_seconds_total=18.109375 rss_mb=749.8
- python (pid 43160): cpu%= cpu_seconds_total=1.890625 rss_mb=772.6
- python (pid 45040): cpu%=38.56 cpu_seconds_total=43107.515625 rss_mb=1842.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2506; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14628, relaunches_total=86, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1992; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36300, relaunches_total=85, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44248, relaunches_total=85, relaunched_this_cycle=True, last_errors=System.Object[]

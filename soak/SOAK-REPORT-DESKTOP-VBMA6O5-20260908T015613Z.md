# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T015613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 47.5 h of 2
- egress probes: 96, failing: 96
- heartbeats: 207
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22812): cpu%= cpu_seconds_total=0.046875 rss_mb=24.9
- python (pid 34728): cpu%= cpu_seconds_total=10.71875 rss_mb=759.2
- python (pid 38856): cpu%= cpu_seconds_total=16.265625 rss_mb=767.8
- python (pid 39972): cpu%= cpu_seconds_total=4.8125 rss_mb=773.9
- python (pid 45040): cpu%=39.39 cpu_seconds_total=48213.5 rss_mb=1846.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3339; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27164, relaunches_total=95, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3690; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47688, relaunches_total=94, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2500; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38856, relaunches_total=94, relaunched_this_cycle=True, last_errors=System.Object[]

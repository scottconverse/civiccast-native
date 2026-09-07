# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T215612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 43.5 h of 2
- egress probes: 88, failing: 88
- heartbeats: 199
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22476): cpu%= cpu_seconds_total=0.015625 rss_mb=20.5
- python (pid 11796): cpu%= cpu_seconds_total=3.359375 rss_mb=773.9
- python (pid 20972): cpu%= cpu_seconds_total=16.796875 rss_mb=766.6
- python (pid 36384): cpu%= cpu_seconds_total=11.703125 rss_mb=761.8
- python (pid 45040): cpu%=31.45 cpu_seconds_total=43673.4375 rss_mb=1843.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20972, relaunches_total=87, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27620, relaunches_total=86, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1624; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35292, relaunches_total=86, relaunched_this_cycle=True, last_errors=System.Object[]

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T082612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 30 h of 2
- egress probes: 61, failing: 61
- heartbeats: 172
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 34380): cpu%= cpu_seconds_total=0.046875 rss_mb=20.5
- python (pid 5848): cpu%= cpu_seconds_total=8.609375 rss_mb=778.5
- python (pid 33036): cpu%= cpu_seconds_total=16.6875 rss_mb=763.6
- python (pid 38732): cpu%= cpu_seconds_total=2.609375 rss_mb=773.1
- python (pid 45040): cpu%=28.15 cpu_seconds_total=30694.65625 rss_mb=1834

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3711; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43196, relaunches_total=60, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=, pid=33036, relaunches_total=59, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2989; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28268, relaunches_total=60, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

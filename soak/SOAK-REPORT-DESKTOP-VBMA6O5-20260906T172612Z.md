# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T172612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 15 h of 2
- egress probes: 31, failing: 31
- heartbeats: 142
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22760): cpu%= cpu_seconds_total=0.015625 rss_mb=20.5
- python (pid 5144): cpu%= cpu_seconds_total=9.5 rss_mb=777.5
- python (pid 43940): cpu%= cpu_seconds_total=58.53125 rss_mb=450
- python (pid 43948): cpu%= cpu_seconds_total=3.234375 rss_mb=773.6
- python (pid 45040): cpu%=24.35 cpu_seconds_total=18764.546875 rss_mb=1830.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43948, relaunches_total=30, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=2292, relaunches_total=29, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9924, relaunches_total=30, relaunched_this_cycle=True, last_errors=

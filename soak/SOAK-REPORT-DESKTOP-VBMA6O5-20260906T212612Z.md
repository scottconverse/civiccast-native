# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T212612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 19 h of 2
- egress probes: 39, failing: 39
- heartbeats: 150
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 28252): cpu%= cpu_seconds_total=0.015625 rss_mb=16.5
- ffmpeg (pid 35236): cpu%= cpu_seconds_total=5.1875 rss_mb=671.7
- python (pid 25784): cpu%= cpu_seconds_total=8.171875 rss_mb=778.1
- python (pid 45040): cpu%=28.02 cpu_seconds_total=22203.65625 rss_mb=1829.8
- python (pid 47660): cpu%= cpu_seconds_total=33.515625 rss_mb=433.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35372, relaunches_total=38, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2765; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21624, relaunches_total=37, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2739; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42656, relaunches_total=38, relaunched_this_cycle=True, last_errors=

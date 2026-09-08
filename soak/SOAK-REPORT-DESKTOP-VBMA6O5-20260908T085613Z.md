# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T085613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 54.5 h of 2
- egress probes: 110, failing: 110
- heartbeats: 221
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 12576): cpu%= cpu_seconds_total=0.078125 rss_mb=20.1
- ffmpeg (pid 42996): cpu%= cpu_seconds_total=0 rss_mb=19.7
- python (pid 36716): cpu%= cpu_seconds_total=7.859375 rss_mb=777.3
- python (pid 40220): cpu%= cpu_seconds_total=8.015625 rss_mb=762.2
- python (pid 45040): cpu%=30.23 cpu_seconds_total=55937.46875 rss_mb=1849.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2650; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32108, relaunches_total=109, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3624; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40220, relaunches_total=108, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37840, relaunches_total=108, relaunched_this_cycle=True, last_errors=System.Object[]

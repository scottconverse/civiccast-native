# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T082613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 54 h of 2
- egress probes: 109, failing: 109
- heartbeats: 220
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 9224): cpu%= cpu_seconds_total=0.078125 rss_mb=21
- python (pid 18820): cpu%= cpu_seconds_total=47.015625 rss_mb=711.6
- python (pid 23888): cpu%= cpu_seconds_total=12.1875 rss_mb=760.6
- python (pid 28344): cpu%= cpu_seconds_total=48.28125 rss_mb=712.4
- python (pid 45040): cpu%=27.32 cpu_seconds_total=55393.359375 rss_mb=1849.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3860; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42720, relaunches_total=108, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39520, relaunches_total=107, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=17200, relaunches_total=107, relaunched_this_cycle=True, last_errors=System.Object[]

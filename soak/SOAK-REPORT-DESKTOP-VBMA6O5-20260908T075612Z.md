# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T075612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 53.5 h of 2
- egress probes: 108, failing: 108
- heartbeats: 219
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 47100): cpu%= cpu_seconds_total=0.03125 rss_mb=18
- python (pid 27052): cpu%= cpu_seconds_total=2.296875 rss_mb=773.8
- python (pid 29520): cpu%= cpu_seconds_total=31.046875 rss_mb=733.9
- python (pid 45040): cpu%=32.14 cpu_seconds_total=54901.46875 rss_mb=1849

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2548; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24188, relaunches_total=107, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2430; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41960, relaunches_total=106, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3633; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18892, relaunches_total=106, relaunched_this_cycle=True, last_errors=System.Object[]

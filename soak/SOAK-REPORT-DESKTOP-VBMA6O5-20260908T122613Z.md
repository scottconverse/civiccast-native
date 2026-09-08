# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T122613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 58 h of 2
- egress probes: 117, failing: 117
- heartbeats: 228
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 21280): cpu%= cpu_seconds_total=0.015625 rss_mb=16.5
- ffmpeg (pid 28648): cpu%= cpu_seconds_total=2.0625 rss_mb=249.4
- python (pid 7716): cpu%= cpu_seconds_total=4.8125 rss_mb=773.7
- python (pid 43388): cpu%= cpu_seconds_total=3.640625 rss_mb=775.6
- python (pid 45040): cpu%=35.76 cpu_seconds_total=59827.265625 rss_mb=1851.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=7716, relaunches_total=116, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2524; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25416, relaunches_total=115, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3696; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25008, relaunches_total=115, relaunched_this_cycle=True, last_errors=System.Object[]

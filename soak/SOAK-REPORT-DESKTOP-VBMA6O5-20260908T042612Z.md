# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T042612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 50 h of 2
- egress probes: 101, failing: 101
- heartbeats: 212
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 36876): cpu%= cpu_seconds_total=0.03125 rss_mb=25.3
- python (pid 8968): cpu%= cpu_seconds_total=4.328125 rss_mb=773.3
- python (pid 25088): cpu%= cpu_seconds_total=2.09375 rss_mb=774.1
- python (pid 38812): cpu%= cpu_seconds_total=9.453125 rss_mb=765.5
- python (pid 45040): cpu%=26.53 cpu_seconds_total=51140.640625 rss_mb=1846.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2630; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8968, relaunches_total=100, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3323; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25088, relaunches_total=99, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40364, relaunches_total=99, relaunched_this_cycle=True, last_errors=System.Object[]

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T002612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 46 h of 2
- egress probes: 93, failing: 93
- heartbeats: 204
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 24084): cpu%= cpu_seconds_total=0.03125 rss_mb=20.4
- python (pid 29740): cpu%= cpu_seconds_total=12.625 rss_mb=763
- python (pid 32600): cpu%= cpu_seconds_total=15.59375 rss_mb=762.5
- python (pid 35312): cpu%= cpu_seconds_total=6.40625 rss_mb=773.7
- python (pid 45040): cpu%=31.56 cpu_seconds_total=46491.8125 rss_mb=1843.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2317; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19884, relaunches_total=92, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3634; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35312, relaunches_total=91, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29740, relaunches_total=91, relaunched_this_cycle=True, last_errors=System.Object[]

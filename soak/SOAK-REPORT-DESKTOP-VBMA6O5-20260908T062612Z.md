# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T062612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 52 h of 2
- egress probes: 105, failing: 105
- heartbeats: 216
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 45872): cpu%= cpu_seconds_total=0.03125 rss_mb=24.7
- python (pid 7956): cpu%= cpu_seconds_total=9.25 rss_mb=777.3
- python (pid 23816): cpu%= cpu_seconds_total=35.15625 rss_mb=727.2
- python (pid 40508): cpu%= cpu_seconds_total=4.484375 rss_mb=774.1
- python (pid 45040): cpu%=27.53 cpu_seconds_total=53235.8125 rss_mb=1848.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1959; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38664, relaunches_total=104, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=, pid=40508, relaunches_total=103, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2564; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23800, relaunches_total=103, relaunched_this_cycle=True, last_errors=System.Object[]

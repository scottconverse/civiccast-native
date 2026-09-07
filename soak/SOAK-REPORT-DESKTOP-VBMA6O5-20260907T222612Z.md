# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T222612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 44 h of 2
- egress probes: 89, failing: 89
- heartbeats: 200
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 15144): cpu%= cpu_seconds_total=15.34375 rss_mb=769.1
- python (pid 24704): cpu%= cpu_seconds_total=34.3125 rss_mb=725.4
- python (pid 45040): cpu%=22.9 cpu_seconds_total=44085.71875 rss_mb=1841.7
- python (pid 46732): cpu%= cpu_seconds_total=19.953125 rss_mb=750

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24704, relaunches_total=88, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=3020, relaunches_total=87, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2474; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=15144, relaunches_total=87, relaunched_this_cycle=True, last_errors=System.Object[]

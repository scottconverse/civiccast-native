# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T002612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 22 h of 2
- egress probes: 45, failing: 45
- heartbeats: 156
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 16588): cpu%= cpu_seconds_total=25.0625 rss_mb=430.6
- python (pid 24428): cpu%= cpu_seconds_total=4.859375 rss_mb=773.7
- python (pid 32904): cpu%= cpu_seconds_total=6.25 rss_mb=727.2
- python (pid 45040): cpu%=22.05 cpu_seconds_total=24511.078125 rss_mb=1830.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24428, relaunches_total=44, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44708, relaunches_total=43, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3618; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=16588, relaunches_total=44, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T112612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 9 h of 2
- egress probes: 19, failing: 19
- heartbeats: 130
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 30652): cpu%= cpu_seconds_total=0.15625 rss_mb=22.1
- python (pid 32852): cpu%= cpu_seconds_total=9.859375 rss_mb=777.6
- python (pid 39948): cpu%= cpu_seconds_total=31.09375 rss_mb=752.3
- python (pid 40756): cpu%= cpu_seconds_total=6.546875 rss_mb=773.5
- python (pid 45040): cpu%=17.02 cpu_seconds_total=13132.328125 rss_mb=1899.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29896, relaunches_total=18, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39948, relaunches_total=17, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40756, relaunches_total=18, relaunched_this_cycle=True, last_errors=

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T182613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 16 h of 2
- egress probes: 33, failing: 33
- heartbeats: 144
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 14964): cpu%= cpu_seconds_total=24.78125 rss_mb=748.7
- python (pid 19148): cpu%= cpu_seconds_total=24.640625 rss_mb=444.6
- python (pid 39180): cpu%= cpu_seconds_total=20.375 rss_mb=768.4
- python (pid 45040): cpu%=22.3 cpu_seconds_total=19525.203125 rss_mb=1830.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14964, relaunches_total=32, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44228, relaunches_total=31, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37760, relaunches_total=32, relaunched_this_cycle=True, last_errors=

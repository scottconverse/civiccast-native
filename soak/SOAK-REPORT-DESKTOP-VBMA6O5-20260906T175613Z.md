# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T175613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 15.5 h of 2
- egress probes: 32, failing: 32
- heartbeats: 143
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 45904): cpu%= cpu_seconds_total=0.109375 rss_mb=20.6
- python (pid 5452): cpu%= cpu_seconds_total=6.859375 rss_mb=772.7
- python (pid 41112): cpu%= cpu_seconds_total=17.484375 rss_mb=762.5
- python (pid 44260): cpu%= cpu_seconds_total=8.15625 rss_mb=778.8
- python (pid 45040): cpu%=19.95 cpu_seconds_total=19123.828125 rss_mb=1828.4

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31180, relaunches_total=31, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1570; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26328, relaunches_total=30, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=4260, relaunches_total=31, relaunched_this_cycle=True, last_errors=

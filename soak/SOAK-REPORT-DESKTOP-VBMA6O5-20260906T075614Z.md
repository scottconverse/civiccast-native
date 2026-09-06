# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T075614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 5.5 h of 2
- egress probes: 12, failing: 12
- heartbeats: 123
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 15028): cpu%= cpu_seconds_total=0.265625 rss_mb=21.6
- python (pid 26164): cpu%= cpu_seconds_total=41.640625 rss_mb=728
- python (pid 38576): cpu%= cpu_seconds_total=24.484375 rss_mb=768
- python (pid 40680): cpu%= cpu_seconds_total=2 rss_mb=772.3
- python (pid 45040): cpu%=15.96 cpu_seconds_total=10581.59375 rss_mb=1826.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3650; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26164, relaunches_total=11, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23756, relaunches_total=11, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=307; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40680, relaunches_total=11, relaunched_this_cycle=True, last_errors=

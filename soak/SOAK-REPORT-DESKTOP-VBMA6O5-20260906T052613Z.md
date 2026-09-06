# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T052613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 3 h of 2
- egress probes: 7, failing: 7
- heartbeats: 118
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 34664): cpu%= cpu_seconds_total=0.09375 rss_mb=21.4
- python (pid 37080): cpu%= cpu_seconds_total=37.46875 rss_mb=735
- python (pid 38116): cpu%= cpu_seconds_total=1.84375 rss_mb=767.5
- python (pid 45040): cpu%=22.53 cpu_seconds_total=8897.59375 rss_mb=1824.2
- python (pid 46388): cpu%= cpu_seconds_total=34.3125 rss_mb=752.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3133; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22068, relaunches_total=6, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3635; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38116, relaunches_total=6, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41824, relaunches_total=6, relaunched_this_cycle=True, last_errors=

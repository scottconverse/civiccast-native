# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T085613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 6.5 h of 2
- egress probes: 14, failing: 14
- heartbeats: 125
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 30180): cpu%= cpu_seconds_total=0.125 rss_mb=21.3
- python (pid 11744): cpu%= cpu_seconds_total=19.046875 rss_mb=763.3
- python (pid 21956): cpu%= cpu_seconds_total=17.5 rss_mb=761.9
- python (pid 27364): cpu%= cpu_seconds_total=58.59375 rss_mb=451.8
- python (pid 45040): cpu%=19.06 cpu_seconds_total=11230.734375 rss_mb=1824.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=11744, relaunches_total=13, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=1856, relaunches_total=13, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=27516, relaunches_total=13, relaunched_this_cycle=True, last_errors=

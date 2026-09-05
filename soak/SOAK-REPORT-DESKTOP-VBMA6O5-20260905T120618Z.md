# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T120618Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 3 h of 2
- egress probes: 8, failing: 6
- heartbeats: 84
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 40368): cpu%= cpu_seconds_total=0.109375 rss_mb=20.7
- python (pid 4764): cpu%=244.61 cpu_seconds_total=38593.09375 rss_mb=1027.5
- python (pid 8464): cpu%= cpu_seconds_total=17.40625 rss_mb=6660.2
- python (pid 29796): cpu%= cpu_seconds_total=21.796875 rss_mb=6789.8
- python (pid 33496): cpu%= cpu_seconds_total=216.953125 rss_mb=264.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2983; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=25324, relaunches_total=3, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8464, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3632; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=33496, relaunches_total=4, relaunched_this_cycle=True, last_errors=

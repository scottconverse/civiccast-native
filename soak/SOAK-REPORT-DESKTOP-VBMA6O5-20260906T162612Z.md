# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T162612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 14 h of 2
- egress probes: 29, failing: 29
- heartbeats: 140
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 17952): cpu%= cpu_seconds_total=14.34375 rss_mb=761.7
- python (pid 28860): cpu%= cpu_seconds_total=3.734375 rss_mb=774.4
- python (pid 45040): cpu%=35.31 cpu_seconds_total=17910.125 rss_mb=1921.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3652; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28860, relaunches_total=28, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=1168, relaunches_total=27, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38560, relaunches_total=28, relaunched_this_cycle=True, last_errors=

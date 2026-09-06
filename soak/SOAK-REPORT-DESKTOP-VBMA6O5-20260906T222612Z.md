# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T222612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 20 h of 2
- egress probes: 41, failing: 41
- heartbeats: 152
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 19440): cpu%= cpu_seconds_total=6.21875 rss_mb=773.4
- python (pid 25976): cpu%= cpu_seconds_total=41.390625 rss_mb=443
- python (pid 31996): cpu%= cpu_seconds_total=7.5625 rss_mb=777.4
- python (pid 45040): cpu%=23.61 cpu_seconds_total=23006.375 rss_mb=1829.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19440, relaunches_total=40, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25976, relaunches_total=39, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=18608, relaunches_total=40, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

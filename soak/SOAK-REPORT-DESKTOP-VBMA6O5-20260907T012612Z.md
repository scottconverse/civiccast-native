# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T012612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 23 h of 2
- egress probes: 47, failing: 47
- heartbeats: 158
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 27148): cpu%= cpu_seconds_total=19.546875 rss_mb=434.2
- python (pid 34648): cpu%= cpu_seconds_total=2.71875 rss_mb=772.8
- python (pid 40444): cpu%= cpu_seconds_total=8.078125 rss_mb=429.4
- python (pid 45040): cpu%=17.56 cpu_seconds_total=25142.40625 rss_mb=1830.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30672, relaunches_total=46, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34648, relaunches_total=45, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38040, relaunches_total=46, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T165612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 14.5 h of 2
- egress probes: 30, failing: 30
- heartbeats: 141
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=2)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 30424): cpu%= cpu_seconds_total=0.0625 rss_mb=21.2
- python (pid 24840): cpu%= cpu_seconds_total=2.125 rss_mb=773
- python (pid 26172): cpu%= cpu_seconds_total=66.140625 rss_mb=453.7
- python (pid 45040): cpu%=23.11 cpu_seconds_total=18326.203125 rss_mb=1831.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2098; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=34076, relaunches_total=29, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39264, relaunches_total=28, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3636; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40392, relaunches_total=29, relaunched_this_cycle=True, last_errors=

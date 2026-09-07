# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T065612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 28.5 h of 2
- egress probes: 58, failing: 58
- heartbeats: 169
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 18844): cpu%= cpu_seconds_total=0.0625 rss_mb=20.6
- python (pid 25948): cpu%= cpu_seconds_total=9.46875 rss_mb=778.1
- python (pid 30724): cpu%= cpu_seconds_total=19.53125 rss_mb=763.7
- python (pid 44768): cpu%= cpu_seconds_total=5.796875 rss_mb=773.1
- python (pid 45040): cpu%=23.99 cpu_seconds_total=29209.140625 rss_mb=1833.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4572; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26184, relaunches_total=57, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37756, relaunches_total=56, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44768, relaunches_total=57, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

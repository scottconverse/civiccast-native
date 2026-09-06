# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T225612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 20.5 h of 2
- egress probes: 42, failing: 42
- heartbeats: 153
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 44724): cpu%= cpu_seconds_total=0.140625 rss_mb=21.3
- python (pid 36284): cpu%= cpu_seconds_total=12.0625 rss_mb=432.3
- python (pid 43368): cpu%= cpu_seconds_total=65.75 rss_mb=448.4
- python (pid 45040): cpu%=18.43 cpu_seconds_total=23338.109375 rss_mb=1830.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2178; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36284, relaunches_total=41, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3607; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37552, relaunches_total=40, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3613; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46288, relaunches_total=41, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

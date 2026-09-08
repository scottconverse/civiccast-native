# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T095612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 55.5 h of 2
- egress probes: 112, failing: 112
- heartbeats: 223
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 12048): cpu%= cpu_seconds_total=16.34375 rss_mb=753.8
- python (pid 28040): cpu%= cpu_seconds_total=22.453125 rss_mb=757
- python (pid 43500): cpu%= cpu_seconds_total=5.875 rss_mb=778.3
- python (pid 45040): cpu%=30.05 cpu_seconds_total=57010.390625 rss_mb=1849.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3613; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33104, relaunches_total=111, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20292, relaunches_total=110, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3688; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27788, relaunches_total=110, relaunched_this_cycle=True, last_errors=System.Object[]

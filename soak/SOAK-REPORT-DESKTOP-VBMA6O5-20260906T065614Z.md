# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T065614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 4.5 h of 2
- egress probes: 10, failing: 10
- heartbeats: 121
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22928): cpu%= cpu_seconds_total=0.0625 rss_mb=21
- python (pid 31256): cpu%= cpu_seconds_total=11.078125 rss_mb=777.4
- python (pid 33636): cpu%= cpu_seconds_total=27.265625 rss_mb=769
- python (pid 38000): cpu%= cpu_seconds_total=27.765625 rss_mb=747.1
- python (pid 45040): cpu%=24.44 cpu_seconds_total=9945.625 rss_mb=1826.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3380; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=11900, relaunches_total=9, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3761; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31488, relaunches_total=9, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3636; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33636, relaunches_total=9, relaunched_this_cycle=True, last_errors=

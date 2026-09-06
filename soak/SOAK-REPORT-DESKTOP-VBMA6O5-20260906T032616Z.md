# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T032616Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 1 h of 2
- egress probes: 3, failing: 3
- heartbeats: 114
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 33112): cpu%= cpu_seconds_total=15.546875 rss_mb=555.8
- python (pid 41224): cpu%= cpu_seconds_total=32.890625 rss_mb=553.2
- python (pid 45040): cpu%=17.65 cpu_seconds_total=7684.65625 rss_mb=1813.6
- python (pid 47764): cpu%= cpu_seconds_total=49.578125 rss_mb=549.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=23672; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=TRANSITIONING, engine=gstreamer, pid=47764, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=43850; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29956, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=40398; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39900, relaunches_total=2, relaunched_this_cycle=True, last_errors=

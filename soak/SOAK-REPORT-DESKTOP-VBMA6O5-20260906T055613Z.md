# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T055613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 3.5 h of 2
- egress probes: 8, failing: 8
- heartbeats: 119
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 32988): cpu%= cpu_seconds_total=0.203125 rss_mb=21.7
- python (pid 23576): cpu%= cpu_seconds_total=69.53125 rss_mb=459.9
- python (pid 33664): cpu%= cpu_seconds_total=21.421875 rss_mb=767
- python (pid 45040): cpu%=17.4 cpu_seconds_total=9210.953125 rss_mb=1824.2

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33664, relaunches_total=7, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25368, relaunches_total=7, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=16360, relaunches_total=7, relaunched_this_cycle=True, last_errors=

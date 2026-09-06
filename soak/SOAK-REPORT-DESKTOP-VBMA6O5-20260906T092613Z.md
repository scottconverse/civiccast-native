# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T092613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 7 h of 2
- egress probes: 15, failing: 15
- heartbeats: 126
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22260): cpu%= cpu_seconds_total=0 rss_mb=21.7
- python (pid 31444): cpu%= cpu_seconds_total=64.453125 rss_mb=452.6
- python (pid 35932): cpu%= cpu_seconds_total=6.171875 rss_mb=773.9
- python (pid 40056): cpu%= cpu_seconds_total=15.4375 rss_mb=762.7
- python (pid 45040): cpu%=21.84 cpu_seconds_total=11623.703125 rss_mb=1825.4

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40056, relaunches_total=14, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3612; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=20944, relaunches_total=14, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2801; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=12668, relaunches_total=14, relaunched_this_cycle=True, last_errors=

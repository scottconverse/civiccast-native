# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T055614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 27.5 h of 2
- egress probes: 56, failing: 56
- heartbeats: 167
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 18872): cpu%= cpu_seconds_total=0.015625 rss_mb=16.6
- ffmpeg (pid 28952): cpu%= cpu_seconds_total=4.921875 rss_mb=671.6
- python (pid 4676): cpu%= cpu_seconds_total=7.296875 rss_mb=773.5
- python (pid 41028): cpu%= cpu_seconds_total=14.140625 rss_mb=766.8
- python (pid 45040): cpu%=19.2 cpu_seconds_total=28339.203125 rss_mb=1835.1

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21240, relaunches_total=55, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2169; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45920, relaunches_total=54, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8132, relaunches_total=55, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

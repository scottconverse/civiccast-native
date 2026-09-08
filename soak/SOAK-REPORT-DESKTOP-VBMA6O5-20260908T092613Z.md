# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T092613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 55 h of 2
- egress probes: 111, failing: 111
- heartbeats: 222
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 24908): cpu%= cpu_seconds_total=4.984375 rss_mb=773.4
- python (pid 25780): cpu%= cpu_seconds_total=15.421875 rss_mb=762.3
- python (pid 27712): cpu%= cpu_seconds_total=3.859375 rss_mb=774.5
- python (pid 45040): cpu%=29.56 cpu_seconds_total=56469.421875 rss_mb=1847.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25780, relaunches_total=110, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3630; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27712, relaunches_total=109, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36932, relaunches_total=109, relaunched_this_cycle=True, last_errors=System.Object[]

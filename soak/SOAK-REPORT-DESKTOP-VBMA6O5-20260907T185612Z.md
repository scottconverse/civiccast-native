# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T185612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 40.5 h of 2
- egress probes: 82, failing: 82
- heartbeats: 193
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 31792): cpu%= cpu_seconds_total=0.046875 rss_mb=21.3
- python (pid 6148): cpu%= cpu_seconds_total=7.09375 rss_mb=778.8
- python (pid 42148): cpu%= cpu_seconds_total=4.921875 rss_mb=774.7
- python (pid 45040): cpu%=23.55 cpu_seconds_total=40637.515625 rss_mb=1840.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29356, relaunches_total=81, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=3568, relaunches_total=80, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4413; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28452, relaunches_total=80, relaunched_this_cycle=True, last_errors=System.Object[]

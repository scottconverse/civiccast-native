# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T175613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 39.5 h of 2
- egress probes: 80, failing: 80
- heartbeats: 191
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 20408): cpu%= cpu_seconds_total=28.4375 rss_mb=736.6
- python (pid 33744): cpu%= cpu_seconds_total=29.609375 rss_mb=740.5
- python (pid 38660): cpu%= cpu_seconds_total=8 rss_mb=778.8
- python (pid 45040): cpu%=31.05 cpu_seconds_total=39839.25 rss_mb=1840.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3179; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20408, relaunches_total=79, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3567; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33744, relaunches_total=78, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25544, relaunches_total=78, relaunched_this_cycle=True, last_errors=System.Object[]

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T022612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 24 h of 2
- egress probes: 49, failing: 49
- heartbeats: 160
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 29844): cpu%= cpu_seconds_total=14.671875 rss_mb=777.4
- python (pid 32788): cpu%= cpu_seconds_total=7.984375 rss_mb=779.5
- python (pid 40364): cpu%= cpu_seconds_total=15.28125 rss_mb=764.3
- python (pid 45040): cpu%=18.41 cpu_seconds_total=25837.140625 rss_mb=1835.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29844, relaunches_total=48, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=3492, relaunches_total=47, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3663; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31396, relaunches_total=48, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

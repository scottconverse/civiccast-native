# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T052613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 27 h of 2
- egress probes: 55, failing: 55
- heartbeats: 166
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 26804): cpu%= cpu_seconds_total=9.734375 rss_mb=777.4
- python (pid 31676): cpu%= cpu_seconds_total=5.140625 rss_mb=775.9
- python (pid 35680): cpu%= cpu_seconds_total=6.1875 rss_mb=774.7
- python (pid 45040): cpu%=21.21 cpu_seconds_total=27993.375 rss_mb=1835

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35680, relaunches_total=54, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3634; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31676, relaunches_total=53, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41444, relaunches_total=54, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

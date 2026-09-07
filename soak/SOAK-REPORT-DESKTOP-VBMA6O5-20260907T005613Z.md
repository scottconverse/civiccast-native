# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T005613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 22.5 h of 2
- egress probes: 46, failing: 46
- heartbeats: 157
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 29084): cpu%= cpu_seconds_total=0.03125 rss_mb=25.3
- python (pid 20540): cpu%= cpu_seconds_total=8.390625 rss_mb=428.8
- python (pid 27528): cpu%= cpu_seconds_total=7.828125 rss_mb=430.9
- python (pid 45040): cpu%=17.52 cpu_seconds_total=24826.53125 rss_mb=1834.3
- python (pid 47600): cpu%= cpu_seconds_total=2.609375 rss_mb=772.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3632; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47600, relaunches_total=45, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28096, relaunches_total=44, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44940, relaunches_total=45, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T122612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 10 h of 2
- egress probes: 21, failing: 21
- heartbeats: 132
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 18596): cpu%= cpu_seconds_total=2.109375 rss_mb=249.9
- python (pid 38668): cpu%= cpu_seconds_total=21.640625 rss_mb=766.2
- python (pid 44884): cpu%= cpu_seconds_total=13.671875 rss_mb=762.7
- python (pid 45040): cpu%=17.88 cpu_seconds_total=13798.265625 rss_mb=1825.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30708, relaunches_total=20, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4678; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32824, relaunches_total=19, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44884, relaunches_total=20, relaunched_this_cycle=True, last_errors=

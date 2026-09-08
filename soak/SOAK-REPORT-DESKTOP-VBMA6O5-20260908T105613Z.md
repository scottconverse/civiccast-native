# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T105613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 56.5 h of 2
- egress probes: 114, failing: 114
- heartbeats: 225
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 5364): cpu%= cpu_seconds_total=0.015625 rss_mb=20.4
- python (pid 27444): cpu%= cpu_seconds_total=3.25 rss_mb=773.3
- python (pid 41912): cpu%= cpu_seconds_total=23.609375 rss_mb=756.3
- python (pid 45040): cpu%=33.73 cpu_seconds_total=58121.203125 rss_mb=1850.4
- python (pid 45952): cpu%= cpu_seconds_total=20.96875 rss_mb=751

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41912, relaunches_total=113, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2519; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=15704, relaunches_total=112, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45952, relaunches_total=112, relaunched_this_cycle=True, last_errors=System.Object[]

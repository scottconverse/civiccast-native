# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T025613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 24.5 h of 2
- egress probes: 50, failing: 50
- heartbeats: 161
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 5312): cpu%= cpu_seconds_total=4.46875 rss_mb=773.8
- python (pid 15424): cpu%= cpu_seconds_total=7.609375 rss_mb=778
- python (pid 45040): cpu%=19.47 cpu_seconds_total=26187.65625 rss_mb=1835.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2746; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39740, relaunches_total=49, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37708, relaunches_total=48, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34612, relaunches_total=49, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

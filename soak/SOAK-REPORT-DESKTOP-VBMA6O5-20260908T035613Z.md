# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T035613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 49.5 h of 2
- egress probes: 100, failing: 100
- heartbeats: 211
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 4536): cpu%= cpu_seconds_total=13.453125 rss_mb=761.9
- python (pid 18400): cpu%= cpu_seconds_total=12.6875 rss_mb=762.5
- python (pid 27220): cpu%= cpu_seconds_total=27.453125 rss_mb=736.1
- python (pid 45040): cpu%=28.63 cpu_seconds_total=50663.25 rss_mb=1846.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3631; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27220, relaunches_total=99, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3460; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18732, relaunches_total=98, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2469; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=4536, relaunches_total=98, relaunched_this_cycle=True, last_errors=System.Object[]

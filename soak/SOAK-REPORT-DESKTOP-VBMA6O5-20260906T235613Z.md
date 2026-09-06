# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T235613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 21.5 h of 2
- egress probes: 44, failing: 44
- heartbeats: 155
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 33496): cpu%= cpu_seconds_total=13.296875 rss_mb=432.6
- python (pid 37628): cpu%= cpu_seconds_total=23.46875 rss_mb=441.2
- python (pid 45040): cpu%=20.54 cpu_seconds_total=24114.46875 rss_mb=1876.9
- python (pid 47684): cpu%= cpu_seconds_total=6.3125 rss_mb=774.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47684, relaunches_total=43, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19664, relaunches_total=42, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21764, relaunches_total=43, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

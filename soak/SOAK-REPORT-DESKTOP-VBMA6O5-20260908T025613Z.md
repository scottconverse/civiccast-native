# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T025613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 48.5 h of 2
- egress probes: 98, failing: 98
- heartbeats: 209
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 16976): cpu%= cpu_seconds_total=6.828125 rss_mb=778.9
- python (pid 20648): cpu%= cpu_seconds_total=6.484375 rss_mb=777.9
- python (pid 38756): cpu%= cpu_seconds_total=28.46875 rss_mb=736.3
- python (pid 45040): cpu%=33.81 cpu_seconds_total=49541.0625 rss_mb=1876.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2601; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39944, relaunches_total=97, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3382; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34056, relaunches_total=96, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=48088, relaunches_total=96, relaunched_this_cycle=True, last_errors=System.Object[]

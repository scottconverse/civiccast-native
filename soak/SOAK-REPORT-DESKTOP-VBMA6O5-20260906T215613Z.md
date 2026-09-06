# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T215613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 19.5 h of 2
- egress probes: 40, failing: 40
- heartbeats: 151
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 8728): cpu%= cpu_seconds_total=11.890625 rss_mb=777.6
- python (pid 39968): cpu%= cpu_seconds_total=14.984375 rss_mb=429.2
- python (pid 44892): cpu%= cpu_seconds_total=10.890625 rss_mb=779.5
- python (pid 45040): cpu%=20.99 cpu_seconds_total=22581.578125 rss_mb=1829.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=4562; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29632, relaunches_total=39, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38664, relaunches_total=38, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=7956, relaunches_total=39, relaunched_this_cycle=True, last_errors=

# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T072612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 53 h of 2
- egress probes: 107, failing: 107
- heartbeats: 218
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 39576): cpu%= cpu_seconds_total=0.03125 rss_mb=25.2
- python (pid 6716): cpu%= cpu_seconds_total=19.140625 rss_mb=753
- python (pid 42344): cpu%= cpu_seconds_total=12.484375 rss_mb=761.5
- python (pid 43204): cpu%= cpu_seconds_total=7.75 rss_mb=777.6
- python (pid 45040): cpu%=36.64 cpu_seconds_total=54322.953125 rss_mb=1847.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3125; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43204, relaunches_total=106, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2230; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39724, relaunches_total=105, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32664, relaunches_total=105, relaunched_this_cycle=True, last_errors=System.Object[]

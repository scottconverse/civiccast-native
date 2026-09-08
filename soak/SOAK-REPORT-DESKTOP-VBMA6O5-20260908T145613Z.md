# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T145613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 60.5 h of 2
- egress probes: 122, failing: 122
- heartbeats: 233
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 21540): cpu%= cpu_seconds_total=0.0625 rss_mb=16.6
- python (pid 22576): cpu%= cpu_seconds_total=0.140625 rss_mb=2.3
- python (pid 45040): cpu%=36.53 cpu_seconds_total=62500.03125 rss_mb=1853
- python (pid 47916): cpu%= cpu_seconds_total=2.609375 rss_mb=773.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2588; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=17228, relaunches_total=120, relaunched_this_cycle=True, last_errors=GStreamer playout worker child exited non-zero; relaunching encoder. Last child stderr: CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2530; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9720, relaunches_total=119, relaunched_this_cycle=True, last_errors=System.Object[]
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22576, relaunches_total=120, relaunched_this_cycle=True, last_errors=System.Object[]

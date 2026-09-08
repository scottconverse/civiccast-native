# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T132612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 59 h of 2
- egress probes: 119, failing: 119
- heartbeats: 230
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 39736): cpu%= cpu_seconds_total=12.78125 rss_mb=760.5
- python (pid 45040): cpu%=30.55 cpu_seconds_total=60952.6875 rss_mb=1853.2
- python (pid 48068): cpu%= cpu_seconds_total=2.234375 rss_mb=773

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2132; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20328, relaunches_total=118, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=STARTING, engine=, pid=, relaunches_total=116, relaunched_this_cycle=False, last_errors=GStreamer playout worker child exited non-zero; relaunching encoder. Last child stderr: CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | CTRL stall: no output for 10s - quitting for daemon restart | No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2585; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=2648, relaunches_total=117, relaunched_this_cycle=True, last_errors=System.Object[]

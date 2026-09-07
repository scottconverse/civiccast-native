# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T195613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 41.5 h of 2
- egress probes: 84, failing: 84
- heartbeats: 195
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 28440): cpu%= cpu_seconds_total=23.5625 rss_mb=751.3
- python (pid 34192): cpu%= cpu_seconds_total=32.828125 rss_mb=739.1
- python (pid 45040): cpu%=24.03 cpu_seconds_total=41488.4375 rss_mb=1839.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21152, relaunches_total=83, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1858; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36288, relaunches_total=82, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32832, relaunches_total=82, relaunched_this_cycle=True, last_errors=System.Object[]

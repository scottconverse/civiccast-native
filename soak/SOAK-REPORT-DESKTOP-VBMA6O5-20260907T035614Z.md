# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T035614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 25.5 h of 2
- egress probes: 52, failing: 52
- heartbeats: 163
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 18356): cpu%=-0.29 cpu_seconds_total=0 rss_mb=21.1
- python (pid 23680): cpu%= cpu_seconds_total=6.140625 rss_mb=774
- python (pid 25168): cpu%= cpu_seconds_total=35.6875 rss_mb=755.3
- python (pid 27376): cpu%= cpu_seconds_total=4.234375 rss_mb=774.4
- python (pid 45040): cpu%=19.62 cpu_seconds_total=26848.171875 rss_mb=1835.9

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=5816, relaunches_total=51, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2107; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23680, relaunches_total=50, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27376, relaunches_total=51, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

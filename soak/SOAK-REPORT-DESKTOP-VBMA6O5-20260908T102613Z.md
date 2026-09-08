# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T102613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 56 h of 2
- egress probes: 113, failing: 113
- heartbeats: 224
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 18184): cpu%= cpu_seconds_total=0.0625 rss_mb=20.5
- python (pid 21280): cpu%= cpu_seconds_total=4.65625 rss_mb=774.9
- python (pid 24156): cpu%= cpu_seconds_total=26.515625 rss_mb=740.4
- python (pid 43844): cpu%= cpu_seconds_total=26.734375 rss_mb=739.6
- python (pid 45040): cpu%=27.97 cpu_seconds_total=57513.8125 rss_mb=1904.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2577; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43844, relaunches_total=112, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2449; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9200, relaunches_total=111, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14948, relaunches_total=111, relaunched_this_cycle=True, last_errors=System.Object[]

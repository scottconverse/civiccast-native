# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T052613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 51 h of 2
- egress probes: 103, failing: 103
- heartbeats: 214
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 38500): cpu%= cpu_seconds_total=0.046875 rss_mb=20.5
- python (pid 3240): cpu%= cpu_seconds_total=45.890625 rss_mb=699.3
- python (pid 31044): cpu%= cpu_seconds_total=7.96875 rss_mb=777.1
- python (pid 45040): cpu%=30.42 cpu_seconds_total=52218.140625 rss_mb=2019.9
- python (pid 45276): cpu%= cpu_seconds_total=37.8125 rss_mb=715.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2558; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31044, relaunches_total=102, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2450; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45276, relaunches_total=101, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=39712, relaunches_total=101, relaunched_this_cycle=True, last_errors=System.Object[]

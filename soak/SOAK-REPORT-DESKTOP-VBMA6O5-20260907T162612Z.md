# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T162612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 38 h of 2
- egress probes: 77, failing: 77
- heartbeats: 188
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 12596): cpu%= cpu_seconds_total=16.96875 rss_mb=767.3
- python (pid 13748): cpu%= cpu_seconds_total=2.296875 rss_mb=772.9
- python (pid 34044): cpu%= cpu_seconds_total=7.125 rss_mb=776.9
- python (pid 45040): cpu%=28.74 cpu_seconds_total=38243.546875 rss_mb=1839.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=12596, relaunches_total=76, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3647; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34044, relaunches_total=75, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21240, relaunches_total=75, relaunched_this_cycle=True, last_errors=System.Object[]

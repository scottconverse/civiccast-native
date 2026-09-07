# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T155612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 37.5 h of 2
- egress probes: 76, failing: 76
- heartbeats: 187
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 42320): cpu%= cpu_seconds_total=6.03125 rss_mb=672.5
- python (pid 29728): cpu%= cpu_seconds_total=12.734375 rss_mb=769.8
- python (pid 29984): cpu%= cpu_seconds_total=18.125 rss_mb=738.2
- python (pid 45040): cpu%=22.83 cpu_seconds_total=37726.34375 rss_mb=1838.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2957; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29984, relaunches_total=75, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2764; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20600, relaunches_total=74, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2316; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19936, relaunches_total=74, relaunched_this_cycle=True, last_errors=System.Object[]

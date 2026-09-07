# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T112612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 33 h of 2
- egress probes: 67, failing: 67
- heartbeats: 178
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 32736): cpu%= cpu_seconds_total=0.078125 rss_mb=20.9
- python (pid 26908): cpu%= cpu_seconds_total=4.28125 rss_mb=775
- python (pid 40772): cpu%= cpu_seconds_total=5.375 rss_mb=773.9
- python (pid 45040): cpu%=21.62 cpu_seconds_total=33588.0625 rss_mb=1892
- python (pid 46796): cpu%= cpu_seconds_total=2.265625 rss_mb=773.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2384; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40772, relaunches_total=66, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2722; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26908, relaunches_total=65, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33748, relaunches_total=65, relaunched_this_cycle=True, last_errors=System.Object[]

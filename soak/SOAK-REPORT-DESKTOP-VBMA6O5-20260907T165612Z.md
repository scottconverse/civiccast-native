# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T165612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 38.5 h of 2
- egress probes: 78, failing: 78
- heartbeats: 189
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 35604): cpu%= cpu_seconds_total=16.640625 rss_mb=747.6
- python (pid 40284): cpu%= cpu_seconds_total=5.921875 rss_mb=779.2
- python (pid 45040): cpu%=29.72 cpu_seconds_total=38778.578125 rss_mb=1839.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2431; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=17960, relaunches_total=77, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3236; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35604, relaunches_total=76, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2355; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47176, relaunches_total=76, relaunched_this_cycle=True, last_errors=System.Object[]

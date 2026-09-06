# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T232612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 21 h of 2
- egress probes: 43, failing: 43
- heartbeats: 154
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 26776): cpu%= cpu_seconds_total=0.109375 rss_mb=20.9
- python (pid 23524): cpu%= cpu_seconds_total=5.375 rss_mb=773.7
- python (pid 40416): cpu%= cpu_seconds_total=7.421875 rss_mb=774.1
- python (pid 45040): cpu%=22.58 cpu_seconds_total=23744.59375 rss_mb=1832.4
- python (pid 45836): cpu%= cpu_seconds_total=3.734375 rss_mb=774.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2084; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23524, relaunches_total=42, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=40416, relaunches_total=41, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45836, relaunches_total=42, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

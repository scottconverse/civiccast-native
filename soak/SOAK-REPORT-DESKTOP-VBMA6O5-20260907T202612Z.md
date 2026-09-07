# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T202612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 42 h of 2
- egress probes: 85, failing: 85
- heartbeats: 196
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 6780): cpu%= cpu_seconds_total=37.5 rss_mb=716.5
- python (pid 21416): cpu%= cpu_seconds_total=5.203125 rss_mb=773.9
- python (pid 40532): cpu%= cpu_seconds_total=10.59375 rss_mb=762.4
- python (pid 45040): cpu%=27.43 cpu_seconds_total=41982 rss_mb=1839.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2619; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35176, relaunches_total=84, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8336, relaunches_total=83, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2341; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38168, relaunches_total=83, relaunched_this_cycle=True, last_errors=System.Object[]

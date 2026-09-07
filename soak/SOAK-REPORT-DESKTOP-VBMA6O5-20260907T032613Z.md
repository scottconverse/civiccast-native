# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T032613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 25 h of 2
- egress probes: 51, failing: 51
- heartbeats: 162
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 14920): cpu%= cpu_seconds_total=3.46875 rss_mb=774.3
- python (pid 18356): cpu%= cpu_seconds_total=5.234375 rss_mb=773.6
- python (pid 26880): cpu%= cpu_seconds_total=5.90625 rss_mb=774.6
- python (pid 45040): cpu%=17.07 cpu_seconds_total=26494.765625 rss_mb=1834.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18356, relaunches_total=50, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3474; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20704, relaunches_total=49, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25352, relaunches_total=50, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.

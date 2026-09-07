# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T122612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 34 h of 2
- egress probes: 69, failing: 69
- heartbeats: 180
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 47432): cpu%= cpu_seconds_total=0.046875 rss_mb=20.5
- python (pid 14224): cpu%= cpu_seconds_total=12.46875 rss_mb=778.3
- python (pid 26180): cpu%= cpu_seconds_total=21.3125 rss_mb=767.8
- python (pid 40180): cpu%= cpu_seconds_total=2.03125 rss_mb=770.5
- python (pid 45040): cpu%=33.4 cpu_seconds_total=34602.265625 rss_mb=1837.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2341; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26180, relaunches_total=68, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2941; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=14224, relaunches_total=67, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2414; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40180, relaunches_total=67, relaunched_this_cycle=True, last_errors=System.Object[]

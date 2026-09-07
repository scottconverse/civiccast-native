# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T142612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 36 h of 2
- egress probes: 73, failing: 73
- heartbeats: 184
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 15312): cpu%= cpu_seconds_total=40.5 rss_mb=735.5
- python (pid 37616): cpu%= cpu_seconds_total=11.421875 rss_mb=777.9
- python (pid 38916): cpu%= cpu_seconds_total=9.15625 rss_mb=778.6
- python (pid 45040): cpu%=27.79 cpu_seconds_total=36459.59375 rss_mb=1838.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=15312, relaunches_total=72, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3604; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45500, relaunches_total=71, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33240, relaunches_total=71, relaunched_this_cycle=True, last_errors=System.Object[]

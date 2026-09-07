# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T085613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 30.5 h of 2
- egress probes: 62, failing: 62
- heartbeats: 173
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 34268): cpu%= cpu_seconds_total=4.3125 rss_mb=250
- ffmpeg (pid 38840): cpu%= cpu_seconds_total=0.25 rss_mb=21.3
- python (pid 15488): cpu%= cpu_seconds_total=46.828125 rss_mb=717.1
- python (pid 29108): cpu%= cpu_seconds_total=5.640625 rss_mb=774.9
- python (pid 45040): cpu%=35.92 cpu_seconds_total=31341.609375 rss_mb=1835.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2279; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29108, relaunches_total=61, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2243; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=15488, relaunches_total=60, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=42212, relaunches_total=61, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate. | No valid source plan is available; generated fallback slate.

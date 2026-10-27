# Black/silent station outage (October 26) - cause, correction, local hotfix

Status: cause proven from retained logs, corrected in source (`fix/black-silent-20261027`),
applied to this TEST host's installed Python module as a local hotfix, and verified with
real program A/V on all three channels. Not a signed package, not a new release, and not
an endurance requalification.

## Observed cause (log, not inference)

`C:\ProgramData\CivicCast\logs\control_plane-app.log` (then `.6`, now `.4`) lines
5832-5859, verbatim except for the elided middle of the traceback:

```
2026-10-25 07:49:55,675 INFO  civiccast.egress.daemon: Content-reload source preparation
                             for public took 5.4s for 1 segment(s) (media preparation completed).
2026-10-25 07:49:55,679 ERROR civiccast.egress.daemon: Content-reload dispatch failed for
                             public; restarting encoder.
  File "...\site-packages\civiccast\egress\daemon.py", line 6045, in _reload_steps
    armed = self._encoder_strategy.reload_content(
  File "...\site-packages\civiccast\egress\gst\strategy.py", line 1538, in reload_content
    encoder_override = self._resolve_encoder_override(request, warn=False)
  File "...\site-packages\civiccast\egress\gst\strategy.py", line 1253, in _resolve_encoder_override
    decision = decide_encoder(
  File "...\site-packages\civiccast\egress\gst\encoder_probe.py", line 140, in decide_encoder
    if probe(candidate):
  File "...\site-packages\civiccast\egress\gst\encoder_probe.py", line 57, in probe_hardware_encoder
    return hardware_encoder_available(factory_name, lookup=gst_factory_klass)
  File "...\site-packages\civiccast\egress\gst\encoder_probe.py", line 43, in gst_factory_klass
    bootstrap_installed_gstreamer_runtime()
  File "...\site-packages\civiccast\native\gstreamer_runtime.py", line 137, in bootstrap_installed_gstreamer_runtime
    _DLL_HANDLES.append(os.add_dll_directory(bin_dir))
FileNotFoundError: [WinError 206] The filename or extension is too long:
  'C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer\bin'
```

The media preparation succeeded; only the **dispatch** step failed. The named directory
exists and is 70 characters long, so WinError 206 was not a missing path or an over-long
name. `os.add_dll_directory` appends to a process-wide loader search path whose buffer is
a fixed 32,767 characters, and `bootstrap_installed_gstreamer_runtime` had no per-directory
guard while `encoder_probe.gst_factory_klass` re-enters it on **every** content-reload
probe. Measured on this host with that exact directory: 460 registrations succeed, the
next raises this exception, and every later call fails permanently.

Consequences observed in the same retained logs and evidence record:

- All three channels left ON_AIR within 21 s of each other (public 07:49:55.724,
  education 07:50:16.9xx) and never returned; 171 dispatch errors (57/channel) and 168
  transition-stall errors followed over 26 h, with unchanged worker PIDs.
- The mux kept encoding black/silent filler: worker tails show
  `[mux-in 5.0s: video=+150 audio=+234] [chain-in 5.0s: in video=+0 audio=+0]` - zero
  source-chain input, 30 fps of blank output, and sampled segments at -91.0 dB.
- Failed recovery is the same cause, not a second one: the dispatch exception returns
  False and arms a pending-reload pin; every later retry (reload-stall watchdog re-issue,
  and the restart path's `strategy.start()`) re-enters the same probe, which cannot succeed
  again in that process.

## Correction

`civiccast/native/gstreamer_runtime.py` now records each registered directory
(`os.path.normcase` key) and calls `os.add_dll_directory` at most once per directory per
process, appending the handle only after a successful call. This mirrors the existing
`civiccast.captions.runtime._CUDA_DLL_DIRECTORY_HANDLES` pattern. Concurrency was
reviewed: the probe path is reached from the single `ChannelAutomationService.run_forever`
thread (the API only enqueues egress commands), so no lock is needed; a future second
caller could duplicate at most one registration per thread, never accumulate.

## Focused red/green

| Check | Command / receipt | Result |
| --- | --- | --- |
| RED, production-exact | installed `runtime\python.exe` + installed (uncorrected) package, `probe_soak.py` | `probe #460 raised`, traceback byte-identical to the 2026-10-25 record |
| GREEN, same scenario | same interpreter/runtime, corrected source | `600 probes succeeded`, 1 loader directory |
| Unit red/green | `pytest tests/native/test_gstreamer_runtime.py -k reload_probes` before/after | `2 failed` (WinError 206) -> `33 passed` with the encoder-probe/decision tests |
| A/V reload | existing native `test_content_reload_continuity_av` plus a 600-probe + reload scenario | reload committed; decoded program solid red, `blackdetect` clean, `mean_volume -20.0 dB` |

## Local hotfix on this TEST host

- Installed module replaced through the elevated helper (no installer rebuild, no change
  to the signed launcher, uninstaller or manifest provenance):
  `...\runtime\Lib\site-packages\civiccast\native\gstreamer_runtime.py`
- Original preserved beside it: `gstreamer_runtime.py.bak-20261027-113835-local-hotfix`
- sha256 original `ff8d8dc7adad05b9f0d433b4cea4432796083b97bee588869fd89bce1fb35e84`
  -> installed `959540cd0c5ea8db85427666d1d6f2b898d5fa5448013ef655aaf0007fd363f6`
- Rollback: copy the `.bak-20261027-113835-local-hotfix` file back over the module and
  restart `CivicCastSupervisor` once (same bounded action used forward).
- One bounded supervisor restart at 11:39 MDT released the exhausted loader state.
  Schedules, database, media and credentials untouched; no 50 GB backup taken.

## Installed-station verification (11:41 MDT, installed FFmpeg)

Three consecutive 2.5 s segments per channel, straight from the live playlists:

| Channel | Media sequence | Video/audio | blackdetect | mean frame RGB | mean / max volume |
| --- | --- | --- | --- | --- | --- |
| public | 34-36 | 1280x720 h264 + aac | none | (120,108,100) | -17.2 .. -21.0 / -1.4 dB |
| education | 34-36 | 1280x720 h264 + aac | none | (75,66,56) | -18.5 .. -20.3 / -2.2 dB |
| government | 34-36 | 1280x720 h264 + aac | none | (77,73,75) | -9.7 .. -11.7 / -2.4 dB |

The operator API `POST /api/staff/egress/channels/public/commands {"action":"reload"}`
was accepted and logged `Seamless content-reload accepted for public
(reload_id=b695e548-d12e-48cf-8334-4dd1102a97e7 ...)` at 11:40:23 - the exact operation
that raised WinError 206 on 2026-10-25. Zero `Content-reload dispatch failed` and zero
ERROR records after the restart.

## Limits

- This proves the mechanism, the correction and the installed-station A/V. It does not
  requalify the ~95 h soak, and it does not diagnose the historical filesrc11 CI failure.
- Machine-readable, sanitized details are in
  [the evidence record](evidence/black-silent-hotfix-2026-10-27.json).

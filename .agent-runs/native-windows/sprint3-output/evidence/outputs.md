# Sprint 3 output completion evidence

## Change and runtime wiring

- `graph_from_config` routes RTMP, divergent loudness targets, and configured OTT tone stripping into per-destination branches. Video encoding is shared; each branch owns its mux and AAC chain. RTMP uses `flvmux streamable=true ! rtmp2sink`; stream keys resolve only from the opaque `secret_props` handle at element creation.
- Loudness uses GStreamer's BS.1770 `audioloudnorm` at the configured sink target, not a fixed gain. Configured SRT/RTMP tone filtering uses two `audiochebband` band-reject stages (833–873 and 940–980 Hz), after normalization, matching FFmpeg filter order and scope.
- The 3 s normalizer hold is declared as `OutputBranch.audio_latency_ns`; the graph max is `PlayoutGraph.max_output_audio_latency_ns`, exposed as `GstPlayoutEngine.output_audio_latency_ns` for EOS handoff. Its per-mux queues have 8 s capacity; that capacity is not counted as added latency.
- Closure maps new factories `audioloudnorm -> gstrsaudiofx.dll` and `audiochebband -> gstaudiofx.dll`. Both are already in pinned GStreamer 1.28.5 plugin wheels. The PE dependency scanner must include `gstfft-1.0-0.dll`, imported by `gstaudiofx.dll`; it is in the pinned `gstreamer_libs` wheel. `REQUIRED_FACTORIES` drives the installed-runtime factory smoke.
- Licensing lookup now classifies both plugin DLLs: `gstaudiofx.dll` as LGPL-2.1-or-later and `gstrsaudiofx.dll` as MPL-2.0. Native `gst-inspect` on the pinned 1.28.5 runtime reported `audiochebband`: License=LGPL, module `gst-plugins-good`; `audioloudnorm`: License=MPL, module `gst-plugin-audiofx`, version `0.15.3-cee45224c`. `flvmux` metadata says `streamable` defaults false and omits indexes/duration when true; the graph now sets true.

## Checks

Focused suite command:

```powershell
python -m pytest -q tests/egress/test_gst_pipeline.py tests/egress/test_gst_bridge.py tests/egress/test_gst_graph.py tests/native/test_runtime_closure.py tests/native/test_runtime_licenses.py
```

Result: `149 passed in 2.95s`.

`git diff --check -- civiccast/egress/gst/bridge.py civiccast/egress/gst/engine.py civiccast/egress/gst/graph.py civiccast/egress/gst/pipeline.py civiccast/native/runtime_closure.py civiccast/native/runtime_licenses.py tests/egress/test_gst_bridge.py tests/egress/test_gst_pipeline.py tests/native/test_runtime_closure.py tests/native/test_runtime_licenses.py` exited 0 with no output.

## Emitted-stream verification

The active `GstPlayoutEngine` output graph used the installed GStreamer 1.28.5 core and Python bindings extracted from the matching pinned wheel. The two new plugin DLLs and `gstfft` were extracted to `C:\Temp\civiccast-sprint3-audio-plugins`; no installed runtime files or station processes were changed. Environment for the one-shot proof scripts:

```powershell
$env:PYTHONPATH = 'C:\Dev\Claude\civiccast-beta15-completion;C:\Temp\civiccast-sprint3-python-bindings\gstreamer_python\Lib\site-packages'
$env:GI_TYPELIB_PATH = 'C:\Temp\civiccast-sprint3-python-bindings\gstreamer_python\Lib\girepository-1.0'
$rt = 'C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer'
$tmp = 'C:\Temp\civiccast-sprint3-audio-plugins'
$env:PATH = "$tmp;$rt\bin;$rt\lib;$env:PATH"
$env:PYGI_DLL_DIRS = "$rt\bin;$rt\lib;$tmp"
$env:GST_PLUGIN_SYSTEM_PATH_1_0 = "$rt\lib\gstreamer-1.0"
$env:GST_PLUGIN_PATH_1_0 = $tmp
$env:GST_REGISTRY = 'C:\Temp\civiccast-sprint3-output-registry.bin'
```

Active graph with one cable TS target (-24), one filtered RTMP-configured FLV target (-16), and one unfiltered RTMP-configured FLV target (-16) emitted 1,875,300 / 1,712,578 / 1,712,696 bytes. FFmpeg `ebur128=peak=true` measured `-24.90 / -16.90 / -16.80 LUFS`; the broadband-source 853 Hz component measured `-12.0 dB` filtered versus plain. A pure 853 Hz run measured `-37.9 dB`; a pure 960 Hz run measured `-44.2 dB` (filtered RMS `0.0013893`, plain RMS `0.2257254`). Pure-tone loudness falls after removing the only signal component, so only the broadband capture is the per-target loudness measurement.

Both active-graph file-capture runs used the one-shot script path `C:\Temp\civiccast-sprint3-output-proof.py`, invoked as `python C:\Temp\civiccast-sprint3-output-proof.py` under the environment above. The 853 Hz captures are `C:\Temp\civiccast-sprint3-output-proof\{cable24.ts,program-tone.wav,stream16-filtered.flv,stream16-plain.flv}`; the 960 Hz captures are the same filenames under `C:\Temp\civiccast-sprint3-output-proof-960\`. The script was edited in place between runs, so its current on-disk version is the 960 Hz run; no separate 853 Hz script copy was retained. FFmpeg's `ebur128` and tone-amplitude measurements were run by that script against the emitted files.

For transport, `python C:\Temp\civiccast-sprint3-rtmp-proof.py` ran the actual configured `GstPlayoutEngine` RTMP graph through `rtmp2sink` to an ephemeral local FFmpeg `-listen 1` receiver. The receiver exited 0 and captured `C:\Temp\civiccast-sprint3-rtmp-proof\received.flv` (857,644 bytes; receiver log: `C:\Temp\civiccast-sprint3-rtmp-proof\receiver.log`); FFmpeg accepted the H.264 + AAC FLV stream. This capture preceded the final property-only `streamable=true` correction, so that property was verified from native factory metadata and the graph assertion, not by a second media run.

HLS rewrite preservation check: `build_loudness_plan` returned `-16.0` before and after `sink.model_copy(update={"kind":"local-ts", ...})` for an inherited HLS sink on a -16 channel (`BEFORE -16.0 inherit None / AFTER -16.0 inherit None`).

## Limits / docs follow-up

The emitted proof used pinned wheel plugins loaded from a temporary overlay, not a rebuilt installer closure. The closure source mappings and recursive dependency inputs are updated, but the installer bundle itself was not rebuilt. Docs owner should mention the new RTMP branch, plugin closure/license entries, and 3 s declared audio processing latency; no global docs were edited here.

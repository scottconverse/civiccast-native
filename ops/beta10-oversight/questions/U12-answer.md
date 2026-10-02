# Coordinator audit of U12 - one required fix, then finish

Commits 1af28f88, a52664a8, 136e5175, 8e9c3845 are otherwise accepted. Coordinator re-ran from Git Bash:
`python -m pytest tests/egress -q -p no:randomly` -> 1 failed (known packaged-GStreamer test), 1698 passed,
40 skipped; `tests/egress/test_hls_relay_video_lock.py` against the pre-U12 relay/daemon/sinks -> collection
error (red). ruff clean.

## Required fix: the rule must cover AUDIO too
You map `("-map", "0:v:0", "-map", "0:a:0?")` - audio OPTIONAL - and only verify video. That just moves the
failure to the other side: a child that probes an input with video but no audio at that instant would serve
VIDEO-ONLY HLS forever. This is not hypothetical: U13 measured the government relay's post-self-heal segments at
18:47:44-18:47:56 as video-only (TS PID 256 only, no PID 257), and a municipal channel with picture and no sound
fails acceptance exactly like one with sound and no picture.
Change: for a sink that carries video AND audio, require both in the mapping (`-map 0:a:0` without `?`) and have
the post-(re)start check require BOTH a video and an audio stream in the newest segment (reuse the same bounded
restart/backoff). If some sink legitimately carries video without audio (check `EgressSink` / channel configs /
sinks.py for an audio flag), keep that case optional - say what you found.
Red then green: a delayed-AUDIO input (video first, audio after N s) must end up with both streams (fails today);
the existing delayed-video tests stay green.

## Then
- `python -m pytest tests/egress -q -p no:randomly` numbers, ruff + mypy on changed files.
- Separate small commit; `git status --porcelain` before it; never amend.
- Append "## Coordinator fix" to `reports\U12.md` with the commit and raw proof.

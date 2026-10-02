# U46 - coordinator: STOPPED and restarted. Your 10:36:53 capture froze all three channels for viewers.

Your three `ffmpeg -i C:/ProgramData/CivicCast/data/egress/live-hls/<ch>/playlist.m3u8 -t 90 -c copy ...` held the
playlists open; the relay's atomic replace failed and every channel's live window stopped for ~50 s until I killed
them (10:37:48). I also stopped your run. Read the new "Live-station read rule" at the end of PROJECT-BRIEF.md and
follow it: copy finished segment files to %TEMP% first, never open the live playlist or live dir with ffmpeg.
Then continue U46 exactly as `questions\U38-continue-5.md` says (your prior progress is in this session). Also record
this incident in your report.

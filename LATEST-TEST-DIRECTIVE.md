# soak8-e1acfe6 Latest Test Directive
Current: soak/DIRECTIVE-4.md
Branch: soak8-e1acfe6-directives
Updated: 2026-09-05T18:47Z (rev 22 - AUTORUN-3 verdict: 3-minute warm-up grace after soak-started; warm-up probes listed in warmup_probes_excluded, never deleted)
Updated: 2026-09-05T18:34Z (rev 21 - AUTORUN-9m: the channels are up but on FALLBACK_SLATE because soak #1 schedule ran out; reschedule 2h15 of the approved soak assets per channel + commit-to-air, start, wait ON_AIR, archive soak #1, start soak #2)
Updated: 2026-09-05T18:28Z (rev 20 - AUTORUN-9l: send start to the three channels (they only auto-resume with auto_start=true), wait 3/3 ON_AIR, then archive soak #1 and start soak #2 on kit 91caebc)
Updated: 2026-09-05T18:26Z (rev 19 - AUTORUN-9k read-only: why 0/3 channels ON_AIR after the 91caebc upgrade; egress dir, raw channel/schedule/playout API, installed version)
Updated: 2026-09-05T16:50Z (rev 18 - AUTORUN-9j: upgrade to kit 91caebc (PR #172 caption-tap fix) and restart the 2-hour soak; soak #1 probes archived)
Updated: 2026-09-05T10:35Z (rev 17 - AUTORUN-9i read-only CPU attribution: caption/summary/ollama log lines, per-process CPU sample, asset/caption job states)
Platform prompt: PROMPT-WINDOWS-CODEX.md (the one paste for a Codex-desktop tester on a Windows box)
Autoruns queued: soak/autorun/AUTORUN-5.ps1 (fetch the e5020746 kit into a fresh kit-<sha> folder, verify, install OVER the existing station), soak/autorun/AUTORUN-9e.ps1 (after AUTORUN-9 clean reinstall; first-admin + three channels + start, 2h15m schedule), soak/autorun/AUTORUN-3.ps1 (TSDuck egress proof, engine-per-channel, relaunch tracking, worker CPU/RSS, 30-min rollups, T+2h verdict)

Updated: 2026-09-03T21:25Z (rev 4 - mission on hold; soak runs on the coordinator box)

Updated: 2026-09-03T20:15Z (rev 2 -- kit re-pointed to the #154 candidate b78b9c7dfa4d66b442172759439553381ec8be44: GStreamer decoder-rank fix; same mission id, same tasks)

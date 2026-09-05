# soak8-e1acfe6 Latest Test Directive
Current: soak/DIRECTIVE-4.md
Branch: soak8-e1acfe6-directives
Updated: 2026-09-05T05:21Z (rev 5 -- 2-hour real-hardware soak of kit e5020746fa40e7a3f1a160d3a8e1add5c3b57786 (1.0.0-beta.5 candidate) prepared: AUTORUN-4.ps1 (renamed from held AUTORUN-2, new kit path, 2h15m schedule) + AUTORUN-3.ps1 (new kit path with C:\CivicCastHostStore fallback, T+2h verdict, 30-min rollups, per-channel worker-restart/pid/last_error tracking, worker CPU/RSS sampling, -DryRun on both); soak/held/ untouched)
Platform prompt: PROMPT-WINDOWS-CODEX.md (the one paste for a Codex-desktop tester on a Windows box)
Autoruns queued: soak/autorun/AUTORUN-2.ps1 (fetch the e5020746 kit into a fresh kit-<sha> folder, verify, install OVER the existing station), soak/autorun/AUTORUN-4.ps1 (first-admin + three channels + start, 2h15m schedule), soak/autorun/AUTORUN-3.ps1 (TSDuck egress proof, engine-per-channel, relaunch tracking, worker CPU/RSS, 30-min rollups, T+2h verdict)

Updated: 2026-09-03T21:25Z (rev 4 - mission on hold; soak runs on the coordinator box)

Updated: 2026-09-03T20:15Z (rev 2 -- kit re-pointed to the #154 candidate b78b9c7dfa4d66b442172759439553381ec8be44: GStreamer decoder-rank fix; same mission id, same tasks)

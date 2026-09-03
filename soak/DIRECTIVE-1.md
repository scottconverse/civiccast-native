# DIRECTIVE 1 — soak72-9573d4a kickoff

Trigger: START NOW

Mission: soak72-9573d4a
Candidate: kit-beta3-9573d4a
Candidate SHA: 9573d4a82e1e1d9993589f633bad6dacba792afb
Kit URL (LAN, HALO): http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/
  (port 8766, not the usual 8765 -- 8765 was already occupied by an earlier
  session's server on HALO, bound to 127.0.0.1 only; this soak's server is a
  separate one on 8766, verified reachable at the LAN address)
Duration: 72 hours total, one continuous run, with a required interim
  checkpoint report at the 24-hour mark (do not stop there -- keep running
  to 72h).

Scope: this soak does NOT require a finished/green installer or a full
product walkthrough. It is scoped to: does the station stay up cleanly
across three concurrent video feeds with programs actually changing, for
72 hours, with no stutters, dropped frames, audio drop/desync, A/V sync
drift, caption drift, unexplained restarts, or 5xx responses.

Full instructions (machine prep, kit fetch + hash verify, install, the
three-channel real-video soak scenario, heartbeat loop, 4-hour rollup
reports, 24h checkpoint, halfway crash-recovery test, final verdict format,
stall/abort rules, and what to do if the directives channel itself breaks)
are in the coordinator's paste-ready prompt, section 2:
  https://raw.githubusercontent.com/scottconverse/civiccast-native/main/... 
  (not published there -- read from the machine that pasted this to you:
  C:\Users\scott\Desktop\floatsom\CIVICCAST-FLEET-SOAK-PROMPT.md, or from
  whatever the pasted prompt already gave you directly -- it is
  self-contained, you do not need to fetch this file over the network)

Real sample videos (4 files) are staged inside the kit directory itself at
samples\ with samples\SAMPLES-SHA256SUMS.txt -- pulled as part of the same
LAN kit fetch, no separate transfer needed.

Your branch: tester/soak72-9573d4a-<YOUR-HOSTNAME> (push only here)
This branch: soak72-9573d4a-directives (read only, never push)

Poll this branch every 15 minutes for the full run and forever after --
publishing your final verdict at T+72h ends this mission's data collection,
not your polling duty.

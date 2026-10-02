# U36 - coordinator note: a second boundary case, 14:51 (public)

Evidence: `evidence\public-exit1-1451\` (worker stdout/stderr, relay logs, control-plane 14:30-14:59).
- Program "Longmont Weather Report - September 10 to September 17" -> next. Engine reload_id=3 fired, finite switch
  rebased to running time 1553.899 s mode=deferred, `old leg disposed`, then output fell to `mux-in 6.0s: video=+66
  audio=+94` and then `video=+0 audio=+0` for BOTH streams; `CTRL stall: no output for 10s - quitting for daemon
  restart`; `WORKER_RESULT {'error': ('stall', 'output stalled')}`; exit 1 at 14:51:22 with state=TRANSITIONING,
  pending_reload=True.
- Relaunch chose "City Council Regular Session - August 11, 2026.mp4"; start preparation queued 14:51:22; on air
  again 14:52:30. Outage ~80 s, self-recovered (the old aggregate watchdog caught this one; no freeze escalation
  needed).
- Same boundary as 14:17 (short weather program ending, deferred program->program switch) but here the new leg
  stopped producing instead of EOSing. Include it in Work 1: is the new leg again a sub-second/short sliver of the
  ending program (then it is the same defect), or something else? Name it either way.

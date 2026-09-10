# CivicCast Native 1.0.0-beta.5 overnight soak report

- Soak start: 2026-09-10 00:05:14 MDT

- Scheduled soak cutoff: 2026-09-10 08:05:14 MDT

- Last pre-cutoff sample: 2026-09-10 08:04:38 MDT

- Final stop verification: 2026-09-10 08:16:35 MDT

- Captions: OFF

- Schedule: five-minute mixed-clip slots on Public, Government, and
  Education

- Intended output: Generic CBR SPTS over UDP to 127.0.0.1 ports 5000,
  5001, and 5002

## Channel results

  ----------------------------------------------------------------------------------
  **Channel**     **Observed   **Relaunches** **Relaunch   **Longest    **Worker RSS
                     program                  times**      gap with     start /
                   changes**                               nothing      end**
                                                           verifiably   
                                                           on air**     
  ------------- ------------ ---------------- ------------ ------------ ------------
  Public                   0                0 None         8h 0m ---    N/A / N/A
                                                           entire       --- no
                                                           scheduled    gst-worker
                                                           soak         process was
                                                                        present

  Government               0                0 None         8h 0m ---    N/A / N/A
                                                           entire       --- no
                                                           scheduled    gst-worker
                                                           soak;        process was
                                                           advertised   present
                                                           PID 9628 was 
                                                           absent from  
                                                           the OS       
                                                           process tree 

  Education                0                0 None         8h 0m ---    N/A / N/A
                                                           entire       --- no
                                                           scheduled    gst-worker
                                                           soak;        process was
                                                           advertised   present
                                                           PID 9224 was 
                                                           absent from  
                                                           the OS       
                                                           process tree 
  ----------------------------------------------------------------------------------

The CivicCastSupervisor descendant python.exe process (PID 8184) used
257.8 MB RSS at the start and 248.0 MB at the final pre-cutoff sample.
Its RSS did not show a steady one-hour rise.

## Alerts and readiness

- Daily automatic self-check warning: readiness and backup probe did not
  pass; occurrence count rose from 2 to 3 at 02:00:20.

- Weekly automatic self-check warning: readiness and backup probe did
  not pass; one occurrence.

- Readiness remained yellow throughout: Do not broadcast yet; runtime
  Idle; 0 critical and 2 warning.

- The test emergency overlay remained active and unchanged.

- Dropped frames remained reported as 0. Beta.5 reports 0 when a
  supported GStreamer metric is unavailable, so this is not independent
  proof that frames were not dropped.

## Final stop result

Stop was issued and confirmed for Public, Education, and Government
through the signed-in Operator UI after the cutoff. The final
credential-free status check did not confirm the requested stopped
state: Public still reported FALLBACK_SLATE, Government TRANSITIONING,
and Education ON_AIR. No advertised worker PID existed in the CivicCast
OS process tree.

## Verdict

This soak failed. None of the three channels produced a verifiable
outgoing worker feed or executed a scheduled program change during the
eight-hour window. Public remained on the fallback slate without a
worker; Government remained stuck changing source with a stale
advertised PID; and Education continued to claim on-air with a stale
advertised PID. The stable supervisor-process RSS argues against a
control-plane memory leak during this run, but it does not offset the
channel-runtime failure. Beta.5 should not be considered ready for
continuous three-channel playout until worker launch, source
transitions, stop-state reporting, and cable-output verification are
repaired and re-tested.

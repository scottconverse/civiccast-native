# DIRECTIVE 4 — prove reboot-survival BEFORE the T+4h reboot (urgent)

The operator will NOT be present at the reboot. Nobody will log in afterward. Everything
post-reboot must run with zero login. Before the T+4h mark (do this NOW, on your next
directive poll):

1. Verify the soak scheduled task meets ALL of these:
   - Runs as `SYSTEM` (or explicitly "run whether user is logged on or not" with stored
     credentials — SYSTEM preferred).
   - Trigger: at system STARTUP (not at logon).
   - `schtasks /query /tn <task> /v /fo LIST` shows Logon Mode that does not require an
     interactive session.
2. If ANY of that is wrong, re-register the task correctly as SYSTEM/at-startup NOW and
   re-verify.
3. Verify soak.ps1's post-reboot resume path one more time by reading your own script:
   it must need no console, no profile, no mapped drives, no user environment — and its
   git push must work from the SYSTEM context (test: run ONE push as the task would run
   it, e.g. `schtasks /run` the task briefly or execute the push step under
   `psexec -s` equivalent you already have; if SYSTEM git auth fails, embed the push
   using the same credential store the task user can reach, and prove it with one test
   commit).
4. Commit `soak/REBOOT-READY.md` with: the full task query output, the git-push-as-task
   proof (test commit sha), and the sentence "post-reboot phase requires no login".
   THIS FILE MUST BE PUSHED BEFORE YOU ALLOW THE T+4h REBOOT.
5. If you cannot make the unattended path work, do NOT reboot: commit
   `soak/REBOOT-BLOCKED.md` explaining exactly what fails, keep heartbeating, and the
   reboot test will be rescheduled for when the operator is present.

The station service itself needs nothing from you — its unattended comeback IS the test.

# Cold-start handoff prompt

Paste the block below into a fresh session. It is deliberately short: everything else lives in the
repository, so the prompt only has to point at it.

---

```
You are taking over CivicCast Native cold. Repo: github.com/scottconverse/civiccast-native
(local checkout, if you have this machine: C:\Users\scott\Desktop\Code\civiccast-native).

Read these three, in this order, before doing anything:

1. PROJECT-STATUS.md (repo root) -- the full handoff. Where the project is, what landed, what
   the overnight soaks found, every remaining fix with its definition of done, the test gates,
   the beta.6 pipeline commands, every file location, and the traps that have already cost time.
2. docs/evidence/soak-2026-09-09-beta5/VERIFICATION-NOTE.md -- the soak evidence re-derived from
   the raw logs, including three claims in the tester reports that do NOT hold.
3. HANDOFF.md (repo root, gitignored -- it IS on GitHub, it just will not stage without
   `git add -f`) -- anything that happened after PROJECT-STATUS.md was written.

Then, before you touch anything: read CLAUDE.md in the repo root. It carries the mandatory
hostile 5-lens self-audit that runs before every push, and the owner's role posture.

The state in one line: main is green, seven fix PRs landed on 2026-09-09/10, and a beta.6 kit is
built and byte-verified but NOT soaked, NOT gate-tested and NOT published -- because two 8-hour
overnight soaks of beta.5 both failed and found a blocker that kit does not fix.

DO NOT publish the built beta.6 kit.

Nothing is in flight. Every fix in PROJECT-STATUS.md section 5 is unstarted, no soak has been run
against beta.6 at all, and the kit LAN file server and the Gate A runner are both down after a
reboot -- which does not matter yet, so do not spend time restarting them until there is a fixed
candidate worth testing. The full not-done list is in PROJECT-STATUS.md section 2.

The blocker, so you know what you are looking at: a seamless programme change can dispose the old
video leg before the new one has prerolled and commit a half-built pipeline (56 or 74 elements
against a healthy 146). The worker then has nothing to play and exits cleanly with error: None.
The daemon relaunches a worker that dies with an error but reads a clean exit as "the operator
turned this channel off" -- so the one failure mode that produces a clean exit is the one with no
recovery. 19 silent channel deaths in 8h21m, zero self-recoveries. It reproduced on a second
machine with captions OFF. PROJECT-STATUS.md section 5, F-1 and F-2, is the release.

To see it yourself in twelve lines: open
docs/evidence/soak-2026-09-09-beta5/blackwell-evidence.zip, open any
SOAK-evidence/<channel>/gst-worker.stdout.log, search for elements=56, and compare the four lines
above it with the eight lines above any elements=146.

Owner's standing rules are in PROJECT-STATUS.md section 10. The ones that bite soonest:
no new features; commit after each task and update HANDOFF.md; agents never merge, the
coordinator merges on a MERGE verdict plus green required checks; one agent per worktree; never
`git stash` in this repo; times in Mountain, 12-hour; and never end a turn with work outstanding
and nothing armed to wake you.

Tell me what you found and what you plan to do first. Do not start until I say go.
```

---

## If the machine is gone

Everything above works from GitHub alone. The only things that live outside the repository are the
two live tracker files under `C:\Users\scott\Desktop\floatsom\`, and snapshots of both are committed
at `docs/evidence/trackers/`.

## If you have the machine but it has rebooted

Three things do not survive a reboot and nothing will tell you they are missing:

- the kit LAN file server on port 8766 (`PROJECT-STATUS.md` §8 step 0)
- the Gate A runner — it is **not** a service; start `C:\actions-runner-gate-a\run.cmd`
- any monitors or background jobs from the previous session

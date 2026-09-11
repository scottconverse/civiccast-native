# Operator fault visibility - 2026-09-11

Delta after fe9ed3c5192d573b5dbf28437aa52ef0589c2615, integrated into PR219.
These are remaining defects from the supplied soak reports, not a new audit scope.

- F7: the existing alert evaluator is called for the affected channel's ERROR
  before same-tick recovery advances to STARTING/ON_AIR. No new timer or delivery
  mechanism was introduced. Detection runs on the next automation scan; the
  default poll delay is2 seconds plus the scan's duration. This is not a hard
  real-time guarantee under a blocked database or overloaded host. Regression
  proves both clean/nonzero exits notify the evaluator in the same process_once
  call. An alert-evaluation failure cannot prevent worker recovery. The existing
  evaluator supplies the channel id and ERROR reason in the off-air summary.
  The open active-alert feed refreshes every10 seconds; the live System Health
  banner refreshes every5 seconds. Operator observation adds that UI interval
  and request latency to detection time, rather than a fixed90-second delay.
- F8: an aborted reload writes its reason to TRANSITIONING.last_error and an
  existing EgressProofEvent. The event remains after a successful restart clears
  live-state error text. The regression reads both the immediate state and proof
  history after recovery; it does not equate a log message with operator evidence.
- F9: UDP status describes local sending and explicitly says receiver reception
  is unverified. Stopped workers and stale progress cannot establish current
  sending. Connection-semantic transports keep their existing status wording.
- F10: list/detail/state operator endpoints project persisted rows through an OS
  PID-existence probe. Missing or unverified PIDs are hidden without changing the
  internal daemon store or erasing historical rows. Normal Stop still clears PID.

Root execution on native Windows with Python3.12: the complete daemon, egress
router, alert evaluator and runtime-status test files passed299 cases in56.76s.
Changed Python files pass Ruff and mypy. The existing API schema is unchanged.
The committed operator-fault-python.xml contains the root JUnit receipt.
These checks establish source behavior, not installed candidate acceptance.

Root operator checks:70 tests passed across the two affected screen test files;
TypeScript production build and ESLint passed. The first full browser run had
252 passes and two failures caused by an old channel-output fixture using uri
instead of the actual API's target field. The fixture is corrected before push.
The corrected full browser gate passed all254 cases in31.4 seconds.

OpenAI-only roles: Sol supplied fault/error propagation and regressions; Terra
supplied the operator-state projection and API regressions; Luna supplied UDP
labels and UI regressions. Root reviewed and integrated actual diffs, clarified
unverified PID handling, removed an unsupported proof-event claim about uninterrupted
air, and exercised alert failure without sacrificing recovery. Root completed
the UI integration after finding a missing type import, added System Health
coverage and qualified stale/unknown sink evidence. Worker UI results were not
accepted as test evidence until root actually built and exercised them.

Fresh candidate Sandbox, full Gate A and real-hardware captions ON/OFF soaks are
still required. No new beta kit is accepted or published by this source evidence.

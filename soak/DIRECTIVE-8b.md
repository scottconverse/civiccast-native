# DIRECTIVE 8b — continue the card run past the UAC boundary

Your findings 1 (card-gap: UAC not on card) and 2 (agent-limitation: secure desktop not
automatable) are both accepted and recorded. Finding 2 defines the boundary honestly:
the UAC prompt is a one-human-click step by OS design and will be added to the card.

CONTINUE the run with this documented substitution: relaunch the setup program from an
elevated context (e.g. an elevated shell launching the exe directly, no /S flag, no
other arguments) — this stands in for "the human clicked Yes on the UAC prompt" and
NOTHING else. Record the substitution in CARD-RUN.md at step 2 as
"SUBSTITUTED: elevated launch = human's UAC Yes (per DIRECTIVE 8b)".

From the moment the installer window exists, resume strict card-only behavior:
- Attempt to observe/drive the CivicCast installer window itself with whatever
  automation you have (it is a normal window, not secure desktop). If you cannot see
  it, fall back to side-effect observation as DIRECTIVE 8 already allows (staging log
  advancing, downloads-vs-offline evidence, shortcuts appearing, :8000 answering) and
  record each card step's verdict from the evidence.
- The offline check matters most: the staging manifest must show every component
  satisfied from the kit (no satisfied_online entries) and the GUI acquisition phase
  must NOT download the AI model (this candidate contains the fix — its first real
  test is this run).
- Continue through First Setup per the card as far as your capabilities honestly reach;
  every stop gets classed card-gap / product-bug / agent-limitation as before.
Then Phase 2 verdict as specified in DIRECTIVE 8.

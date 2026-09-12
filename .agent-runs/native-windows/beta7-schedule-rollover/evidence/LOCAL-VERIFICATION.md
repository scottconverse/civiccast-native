# beta.7 schedule-rollover repair: local verification

Date: 2026-09-12

## Identity

- Source commit: `6697c40048a0488b0fb7998088366f5110b95121`
- Parent / rejected candidate source: `99705005d63c5d9e23b6aca3bbb18654d2b5db3f`
- Branch: `fix/beta7-stale-horizon-reload`
- Release status: source correction only; no replacement installer or kit has
  been built, soaked, gate-tested, or published.

The rejected candidate remains bound to build run `34691600770`, installer
SHA-256 `dd7fbe8051301f98f73ec72e6e267eb4fc0af8b8f17ce2856bdfe54a3bff03cf`,
and manifest SHA-256
`43d615c1b96a6bc37b7e7216e5063f6f8873ea1a51095a835f3b4e475f4f0e65`.
Those artifacts are not evidence for this source commit and must not be reused
as its release candidate.

## Reproduced failure and correction

The 15-minute Sandbox run for the rejected candidate failed after schedule
items were resolved near a 30-second boundary. The automation loop first gave
the replacement only half of the short plan's lifetime for preparation. When
the recorded horizon was already past, it re-dated the same expired dispatch
instead of loading the item due now. The workers then reached clean EOS and
had to relaunch.

This commit gives a one-item boundary plan its full short window for preload,
capped at the existing 120-second lead for longer programmes. A live plan with
an expired horizon now queues one immediate rollover against the original
expired boundary. An in-flight seamless settlement is still left alone, the
issued latch prevents duplicate commands, and source-provider failures retain
their 30-second retry cooldown.

## Executed verification

```text
python -m pytest -p no:cacheprovider --basetemp C:\Users\scott\Documents\Codex\2026-09-10\openai-multi-agent-c-users-scott\.pytest-tmp tests/egress/test_automation.py -q
75 passed in 2.44s

python -m ruff check civiccast/egress/automation.py tests/egress/test_automation.py
All checks passed!

python -m ruff format --check civiccast/egress/automation.py tests/egress/test_automation.py
2 files already formatted

python -m mypy --ignore-missing-imports --no-warn-unused-ignores civiccast/egress/automation.py
Success: no issues found in 1 source file

git diff --check
PASS (no output)
```

The focused suite asserts the 30-second trigger, exact original-boundary and
command-ID binding, young-worker bypass, duplicate suppression, provider
cooldown, retry after a discarded settlement, and preservation of the active
settlement wait.

Two independent read-only reviews found the automation correction clean after
the young-worker and provider-cooldown findings were repaired. A broader local
egress/live run reached 2,124 passes and 73 environment skips; its one unrelated
contribution-coprocess timing failure passed alone. That broad run included a
subsequently removed daemon experiment, so it is recorded as diagnostic only
and is not commit-bound evidence for `6697c400`.

## Remaining release gates

Required PR CI, merge to `main`, a fresh signed build with a new exact identity,
Sandbox, Gate A, the physical tester soak, and publication remain outstanding.

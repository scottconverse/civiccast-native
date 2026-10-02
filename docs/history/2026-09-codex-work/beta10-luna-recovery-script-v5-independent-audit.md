# Beta.10 Luna Recovery Script v5 Independent Audit

**Verdict: PASS (mock-only mechanical audit)**  
**Audited:** 2026-09-24 02:52 Mountain Time (America/Denver)  
**Scope:** pinned recovery script and pinned mock harness only. No implementation files changed.

## Pinned inputs

| File | SHA-256 | Result |
|---|---|---|
| `C:\Users\scott\Documents\Codex\2026-09-20\you-x20\outputs\Recover-Beta10FrozenHls.ps1` | `49341306487240F1C3CBB9F3CC020D64395F624EA185F2415AF06000DDBEDDB4` | Match |
| `C:\Users\scott\Documents\Codex\2026-09-20\you-x20\outputs\Test-Recover-Beta10FrozenHls.Mock.ps1` | `FBBE73BBD3BAE7A96EE80687EE562401C499FE2D012C00D61BB18275315B5FAA` | Match |

## Isolation preflight

Before execution, parsed the harness AST and inspected all recovery-script invocations. There are three actual `powershell.exe` invocations (the main scenario, injected `ERROR` scenario, and injected `STOPPED` scenario). Each passes `-MockRoot` explicitly. The harness calls `Assert-MockIsolation` before the first invocation and throws on parse errors, no detected invocation, or any invocation missing `-MockRoot`. Therefore the requested fail-before-first-invocation preflight passed.

The recovery script redirects `OutDir` and `HlsRoot` under `MockRoot`. In mock mode token issuance returns a fixed in-memory mock token; staff command and state calls return mock responses; revocation returns a mock result. The `MockFastElapsed` virtual clock and sample cap are guarded by `MockRoot` plus the test switch (the cap is confined to the monitor loop). With no `MockRoot`, those hooks do not activate. The production gap remains floored at 15 seconds using a stopwatch; mock execution deliberately bypasses waiting and cannot establish real elapsed-time behavior.

No mock-path call to the live DB, API, bearer-token CLI, service, or helper was found in the reviewed control flow. No ACL-changing operation was found in the recovery script/harness path.

## One permitted run

Executed exactly once with Windows PowerShell 5.1.26100.9444:

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File <pinned harness>`

No script arguments were supplied. Exit code: **0**. Console preflight reported all 3 recovery invocations carried `-MockRoot`; final status was `MOCKTEST PASS`.

Durable harness result: `C:\Users\scott\Documents\Codex\2026-09-20\you-x20\outputs\_beta10-recovery-mock-025131\MOCKTEST-RESULT.txt`  
Result SHA-256: `EEB6B9E785B870D59D44E18DFC04AB574DD32727EB917913FF647E49E368DAEF`  
It records both pinned hashes, `fail_count=0`, `journal_entries=10`, and `MOCKTEST PASS`.

Main mock journal and receipt are in that root's `outputs` directory. The journal has 10 entries: mock token issuance; public and government each have stop intent/result followed by start intent/result with HTTP 202 and queued true; education is skipped as advancing, with no commands. The receipt records public and government as recovered after two advancing samples each and education as skipped. The inspected sample records show playlist presence, increasing media sequence, changed playlist-referenced nonempty TS segment, and later segment mtime for each advancing comparison. Mock sample spacing is virtual and near-instant, not a real 15-second timing proof.

The receipt records mock token revocation as `REVOKED`. Source ordering in the `finally` block performs revocation before best-effort receipt writing. Issue and revoke branches in this run are mock-only; no real token or DB URL was read or used. The main journal and receipt contain no bearer value, DB URL, password, or mock secret string; only a public mock token id is recorded. Source inspection confirms response command IDs and states are allow-listed before persistence.

Production control flow reviewed: it requires HTTP 202 plus `queued=true` for stop and start, polls until the observed state is exactly `STOPPED` before issuing one start, and rejects `ERROR` as a start condition. It only counts advancement when sequence increases, the playlist-referenced segment identity changes, both relevant segment files are nonempty, and the current segment mtime is newer. The real gap floor is 15 seconds in both stagnation and monitoring paths. Token CLI stdout/stderr are captured in memory with bounded wait and kill; DB URL environment scope is restored; revocation is attempted before receipt output; journal/receipt fields are sanitized.

## Side-effect accounting and limits

Default output receipt count in the recovery script's configured output directory was **0 before and 0 after**. Mock artifacts were written only beneath the generated mock root above. No live recovery, real API request, real token, DB URL, service/helper action, ACL change, or source edit was performed.

This PASS is for the pinned scripts' mock-only mechanical behavior and static control-flow review. It does not prove a production recovery, live service response, real 15-second observation timing, or station state. The requested mock run intentionally uses virtual timing.

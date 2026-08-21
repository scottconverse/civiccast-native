# sandbox-lab/

Gate A — the automated station-acceptance release gate. Full documentation
(what it proves, verdict criteria, how to run it, runner setup, promotion
rule): **[`docs/ops/gate-a.md`](../docs/ops/gate-a.md)**.

Quick start:

```powershell
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId <native-beta-candidate-artifacts run id>
```

`output/`, `hoststore/`, `kit-download/`, `kit-staging/`, and `evidence/` are
per-run state (gitignored, kept as empty tracked directories via
`.gitkeep`) — `Run-GateA.ps1` regenerates them on every run.

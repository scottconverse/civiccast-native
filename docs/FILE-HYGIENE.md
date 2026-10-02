# File hygiene (owner rule, 2026-10-02)

This project produced hundreds of GB of scratch files. From now on:

1. **GitHub holds source, tests, docs and durable project state only.** Anything an agent on another machine needs to
   continue the project goes here: `ops/beta10-oversight/` (handoff, log, backlog, briefs, reports, tools),
   `ops/lab-scripts/` (elevated-helper install/restart scripts), `docs/history/` (findings and checkpoints).
2. **Never commit** media (`*.ts`, `*.mp4`, `*.wav`), model files, runtime packs (`*.ccpack`), stream logs (`*.jsonl`),
   rung evidence blobs, scratch folders (`work/`, `outputs/`, `scratch/`, `runs/`), or any agent/CLI config or
   transcript (they can hold tokens). `.gitignore` enforces this.
3. **No new Git LFS objects** without the owner's explicit say-so. The repo uses none.
4. **Delete your own scratch when the unit is accepted.** Keep only the verdict note, the adjudication and the report;
   the raw evidence stays local and is deleted once the verdict is written (note its path in the verdict).
5. Large measurement runs write to a temp folder and are removed at the end of the run, not left behind.
6. One-off helper scripts do not live in the repo root; use a temp directory and delete them.

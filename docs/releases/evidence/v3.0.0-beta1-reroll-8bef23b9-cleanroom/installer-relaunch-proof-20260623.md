# Installer Relaunch Proof

The final installer e2e suite covers the relaunch/resume behavior that QA
previously listed as a watch item:

- `installer marks local runtime-ready progress as dashboard ready`
- `installer saves repair progress and can reset it`
- `installer reads packaged helper-ready progress before backend fixtures`
- `installer continue uses freshly saved runtime-ready progress`
- `installer polls native progress until delayed runtime ready is visible`

Final run:

- Artifact: `docs/releases/gauntletgate/v3.0.0-beta1-final-all-20260623/artifacts/installer-e2e.txt`
- Result: `62 passed`

The host WSL2 proof used a proof-harness install path intentionally so it could
avoid mutating the operator's durable default install. That path choice is a
proof isolation detail, not a public-beta product defect.

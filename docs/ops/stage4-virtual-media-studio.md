# Stage 4 Virtual Media Studio

Stage 4 turns the LPM contract lab into a reusable Virtual Media Studio surface.
It uses the Stage 4-5 LPM contract lab to exercise OBS, vMix, ATEM, VISCA, NDI,
DeckLink, and USB capture fixture rows, then writes a reusable bundle that can
be reviewed or extracted later.

## Stage 4-5 LPM Contract Lab

Run the local lab from the repository root:

```powershell
uv run python scripts/run_lpm_contract_lab.py --execution-stage stage45 --profile all --artifact-root artifacts/lpm-contract-lab/stage4-review
```

The Stage 4-5 run records API fixtures, stateful simulator rows, and optional
software probe rows. Software probe evidence is only claimed when the local OBS
or vMix listener is actually reached and verified by the probe. A missing local
application remains visible as not applicable evidence rather than being hidden.

## Reusable Bundle

The reusable bundle contains the Virtual Media Studio profile packs, plugins,
profiles, scenarios, and extension contract. Treat it as local lab software and
not as a standalone release artifact.

The bundle must include:

- `vstudio-bundle-manifest.json`
- `profile-packs.json`
- `plugins.json`
- `profiles.json`
- `scenarios.json`
- `extension-contract.md`
- `README.md`

## Support Bundle And Boundaries

Stage 4 artifacts should be kept with the support bundle for a failed or
degraded control-room run. The support bundle must preserve proof labels and
redact credentials, tokens, passwords, stream keys, and private station data.

Station-device evidence is not claimed by Stage 4. Clean Windows install proof,
elapsed wall-clock soak proof, and live station operation are also not claimed.
Those claims require their own enabled proof substrate and artifact trail.

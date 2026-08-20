# SPDX-License-Identifier: CC-BY-4.0

# Audit Sprint 1 Plan

Sprint branch: `work/audit-sprint-1`
Base: `origin/audit/governance-capabilities`
Final PR base: `main`

## Rules

- Work in stage order.
- Do not push to or merge `main`.
- Keep mocks as defaults unless a stage explicitly changes the behavior.
- Update `CAPABILITIES.md` in the same commit when a subsystem's actual state changes.
- Write one result file per stage under `tester-handoff/v2.0.1/test-results/windows/`.
- Do not run the installer, use WSL, reboot/restart Windows, or clean/delete app state.

## Stages

1. Stage A: harden `POST /api/public/app/analytics/events` with immediate abuse controls.
2. Stage B: wire stored trim values into VOD packaging and correct analytics route docs.
3. Stage C: add provider registry/factory seams and config-driven CDN selector.
4. Stage D: add normal broadcast finalization worker/state/retry/status.
5. Stage E: add durable DB-backed caption review store and defer live-audio caption tap design.
6. Stage F: add ActivityPub retry worker and retention enforcement worker.
7. Stage G: add public portal routing/playback analytics and operator channel selection.
8. Final validation: run full backend validation, frontend validations for changed apps, write summary, and open one PR.

## Risk Notes

- Stages C through G are broad and may need to be split if implementation uncovers architecture decisions or external secrets.
- Live-audio caption tap, real external provider adapters, NDI/SDI, macOS packaging, and CTV production work are explicitly out of scope.

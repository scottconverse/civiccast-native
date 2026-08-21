# Branches

One product line. `main` carries it.

CivicCast is a **native Windows** station-in-a-box: a signed installer, a
Windows service registered through the SCM, and a bundled runtime. No WSL, no
Docker, no Linux install target.

| | `main` |
|---|---|
| Product | Native Windows line |
| Install shape | Signed installer registers a session-0 Windows service that supervises the control plane, Postgres, and the media workers from a bundled runtime |
| Governing decision | [ADR 0021](docs/adr/0021-native-windows-runtime.md) introduced the native runtime; the owner retired the WSL2 lane on 2026-08-19 |

Branch from `main`, target `main`. There is no second line to choose between.

## Where the old line went

This repository was created on 2026-08-19 by copying the native product out of
[`scottconverse/civiccast`](https://github.com/scottconverse/civiccast) with
**fresh history**. That repository is now private and still holds:

* the WSL2/Ubuntu install path and its `docker/`, `deploy/systemd/` and
  Linux-GStreamer tooling,
* the published `v1.0.0-rc18` WSL-line release,
* every dated audit, release-verification log and tester handoff from
  2026-05 onward,
* the full commit history of both lines.

Nothing was deleted there. What did not come across is still there to be read.

## What is deliberately not here

Carried over only if it belongs to a native Windows product:

* `docker/`, `deploy/systemd/`, `civiccast/egress/{service_unit,recovery,soak}.py`
* the Linux GStreamer container build (1.28.4) — native Windows uses the
  pinned `gstreamer-*` **1.28.5** PyPI wheels instead
* the installer's WSL2 bootstrap lane
* `docs/audits/`, `docs/releases/`, `docs/research/`, `tester-handoff/`,
  `.agent-runs/` scratch, and the dated handoff memos

The six design specs that lived under `.agent-runs/native-windows/specs/` were
hand-carried into [`docs/design/`](docs/design/) — they are real design records,
not scratch.

## Release identity

`v1.0.0-beta.1` is an owner-held development candidate. It is **not published**.
Tags, releases and publication are owner-only decisions; agents never create or
move a tag.

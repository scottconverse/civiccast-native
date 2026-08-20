# CivicCast App Platform Shells

Status: v1.8.2 shared reference runtime

These shells prove that every public app target starts from the same
app-platform contract at `/api/public/app/config`, then loads the selected
channel's live state, schedule feed, and VOD catalog from the URLs advertised in
that contract.

Targets included in this skeleton:

- Web/PWA
- Roku
- tvOS
- Fire TV
- Android TV
- Android mobile
- iOS/iPadOS

The shells render station identity, channel branding, live playback metadata,
caption/audio tracks, schedule rows, VOD playlist status, and chapter metadata
from the shared contract. Platform packaging, store submission, remote-control
certification, and device-specific playback behavior are tracked explicitly in
the store-readiness guidance for this stage rather than treated as hidden work.

## Local Smoke

```powershell
npm.cmd test
```

## Local Build

```powershell
npm.cmd run build
```

The build writes `dist/build-report.json`, copies the shared runtime and fixture
contract, and emits one target folder for each public app shell. This is the
local proof that every shell can be built from the same station config contract.

## Local Living-Room And Mobile Smoke

```powershell
npm.cmd run smoke
```

The smoke command builds all targets, executes the Roku and Android mobile
reference shells against deterministic CivicCast API responses, and writes
`dist/smoke-report.json`.

## Store Readiness

`store-readiness.json` is the machine-readable packaging and monitoring handoff
for certified integrators. It lists every public target, the expected input
model, proof class, external store requirements, and runtime health checks.

Open any `targets/*/index.html` through a static file server mounted beside the
CivicCast API. Each target can override the config URL with:

```text
?config=/api/public/app/config
```

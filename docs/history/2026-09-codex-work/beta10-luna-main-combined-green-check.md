# Beta 10 Luna combined-main green-check receipt

- Time: 2026-09-24 00:37 America/Denver
- Repository: `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native`
- HEAD: `35d60b7575ce34fd87a06106dcf5ec2c8ecbd635`
- Scope: mechanical verification only. No source/test edits, staging, or service action performed. This receipt is the only created artifact.
- `CIVICCAST_GSTREAMER_RUNTIME_ROOT`: `C:\Program Files\CivicCast (Native)` (path exists; installed runtime root used).
- Startup first-scan caption backlog: **not fixed by this test correction and remains unresolved**. This is not a release PASS.

## Hash assertions

`tests/egress/test_daemon.py` matches the requested SHA-256. All nine prior DeepSeek file hashes from `outputs\beta10-luna-main-combined-check-receipt.md` also match exactly.

| File | SHA-256 |
|---|---|
| `civiccast/egress/hls_relay.py` | `CF2F932561C1FEEA56EA019EE1D981459C72320BB5189A957E4C84D4551DE490` |
| `civiccast/egress/daemon.py` | `17CED1362D3AB6256F953647716FA832C05576752A9DC86F2A86D9AAC2BF601C` |
| `tests/egress/test_hls_relay_progress.py` | `A1306DEBA9568AF3FC47023135D267D6BD42AA8F92FD81DB4B056A58AB75B11C` |
| `civiccast/egress/sinks.py` | `7198C166E7456A992CC7C8CC89FEB295E16F6A3FD729F308CD403E1F0CB1DBED` |
| `civiccast/egress/gst/graph.py` | `2D89B82B271C94987D71658E220679A1EB205F1B7C932BFA7B9F1021137EAAAE` |
| `tests/egress/test_hls_sink_captions.py` | `167CE7AC8495D39CA6B0700564FDFA380B24B8B6F1BC2E0BFC0EC0B52E19570C` |
| `tests/egress/test_hls_sink_live_playability.py` | `EBBCF114E2FED5ABADBB98C06EEF4FB0C6D463511FB638988C0BB20ECD81D62F` |
| `tests/egress/test_contracts.py` | `4A43ABA4796B84544ECE706DE8109835DF0BFCD001A4690F465C353C7CECE55D` |
| `tests/egress/test_gst_graph.py` | `AC2293999EE81A30A60356C00265879465A765E243D3DBC15AB25599FA54CDC2` |
| `tests/egress/test_daemon.py` | `C6280A7135258B60631BFDE0D8984F227BB813A3AD2A42701C9F03FD34CC67AA` |

## Requested seven-module pytest suite

Command (with `CIVICCAST_GSTREAMER_RUNTIME_ROOT=C:\Program Files\CivicCast (Native)` in the process environment):

```powershell
py -m pytest -q -ra tests/egress/test_hls_relay_progress.py tests/egress/test_hls_relay.py tests/egress/test_daemon.py tests/egress/test_gst_graph.py tests/egress/test_hls_sink_captions.py tests/egress/test_hls_sink_live_playability.py tests/egress/test_contracts.py --basetemp C:\Users\scott\Documents\Codex\2026-09-20\you-x20\main-check-after-test-fix-tmp
```

Result: **254 passed, 0 failed, 0 skipped in 55.26s**.

The integrated packaged GStreamer test was explicitly run by node ID with the installed runtime root and a separate fresh basetemp:

```powershell
py -m pytest -q -ra tests/egress/test_hls_sink_captions.py::test_packaged_gstreamer_to_hls_sink_preserves_captions_and_cadence --basetemp C:\Users\scott\Documents\Codex\2026-09-20\you-x20\main-check-after-test-fix-packaged-tmp
```

Result: **1 passed in 37.03s**; it ran and was not skipped.

## Scoped static checks

- `uvx ruff check` on the ten files in the hash table: **passed** (`All checks passed!`).
- `git diff --check -- <same ten files>`: **passed**, no whitespace errors. Git emitted one CRLF-to-LF working-copy warning for `tests/egress/test_hls_sink_live_playability.py`.

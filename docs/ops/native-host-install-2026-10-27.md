# Native host installation and transition acceptance — October 27, 2026

Scott explicitly requested installation directly on this machine, without a
sandbox. The retained signed candidate installed successfully over the existing
station. Setup began 01:30:57 MDT and finished 01:41:37 MDT, exit0.

- Signed source: `423393349f87148e7253f93691a9a70478cc120c`, build40317362877.
- Setup SHA256: `9b01304429a07220dd5f35b061a779fdc07744fb6d0ae45defec232eccb0375a`.
- Installed at `C:\Program Files\CivicCast (Native)`; actual installed manifest
  identifies the expected source. The previous source was2e196124.
- The normal installer stopped the previous service and made its automatic
  recovery snapshot before replacement. Existing station data was retained;
  the checked PostgreSQL PG_VERSION hash remained unchanged. This does not claim
  exhaustive database-row verification.
- The supervisor is running. The actual installed launcher and uninstaller both
  have valid Scott Converse Authenticode signatures and match the F5 hashes.
- The operator console and resident portal returned HTTP200. This establishes
  serving those pages, not completion of every browser workflow or station health.

Two existing focused scenarios ran native worker processes from the **installed**
Python runtime and installed worker path, with disposable media/output directories:

1. Held replacement superseded by another replacement: passed, including replacement
   commit, outgoing continuity/audio and clean teardown.
2. Never-buffering replacement followed by recovery: passed, including containment
   of the failed replacement and successful subsequent replacement.

Both worker processes exited0. No service/configuration edits were needed for these
scenarios. Their small receipt records the installed worker/engine/interpreter hashes.
Raw media and worker logs are local under
`C:\CivicCastTester\f4-installed-transition-20261027`.

This is installed evidence for the retained signed42339334 candidate. The newly
demonstrated state-activation refusal correction in PR272 is separate source work
and is not present in these installed bytes. These passes do not diagnose the
historical run40165319415 filesrc11 failure. The distinct decoder-before-tail
startup experiment is recorded in CURRENT when terminal; no causal claim is made
from these green scenarios alone.

The single controlled experiment also passed: immediately after fourth-decoder
activation, seven downstream elements were NULL. During the caller's0.5s delay,
GstBin's async continuation thread independently activated those tails; replacement
committed and teardown was clean. The historical error did not recur. The
[bounded debug excerpt](evidence/f4-decoder-tail-excerpt-2026-10-27.txt) records
that sequence; the19MB raw diagnostic log remains local. The
[retained original CI log](evidence/f4-historical-ci-40165319415.txt) is preserved
alongside it so the original evidence no longer depends solely on TEMP.

No sandbox, installer rebuild, LFS transfer, reboot, tag or public release was used.
The new native installation is retained on the host.

Receipt: [native-host-install-2026-10-27.json](evidence/native-host-install-2026-10-27.json).

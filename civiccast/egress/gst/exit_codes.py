# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Exit-code contract between the GStreamer playout worker (``worker.py``) and
the daemon (``civiccast.egress.daemon``).

Deliberately gi-free with zero import-time side effects: the daemon must be
able to read these constants WITHOUT triggering ``civiccast.egress.gst.engine``'s
module-level ``bootstrap_installed_gstreamer_runtime()`` / ``Gst.init()`` calls,
which is exactly what importing ``engine.py`` from the daemon process would do.

Item 82 (sandbox run 13): a fresh worker under CPU load can take longer than a
few seconds to reach PLAYING (preroll). That is a slow start, not a crash, and
the daemon's relaunch path (``EgressDaemon._relaunch_after_crash`` /
``_begin_relaunch``) needs to tell the two apart from the child's exit code
alone — the only signal that survives the subprocess boundary.
"""

from __future__ import annotations

# 0 = clean exit (unchanged).
# 1 = generic worker error/crash — every engine failure except the ones named
#     below (unchanged: this is still the default `main()` returns for a
#     non-None `result["error"]`, e.g. the S9-5 stall watchdog).
# 2 = worker.py usage error (missing argv[1]) — predates this change.
GST_PREROLL_TIMEOUT_EXIT_CODE = 3

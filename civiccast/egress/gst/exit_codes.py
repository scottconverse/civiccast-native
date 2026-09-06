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

Item 84 (measured in sandbox run 15, soak-fcfcb81-20260906-183448Z, and in
three seamless-OFF runs): PLAYING is reached quickly (``CTRL preroll: reached
PLAYING after 0.3s``) but the FIRST output buffer can legitimately take much
longer under start-up load than the 10s post-first-buffer stall bound was
ever meant to cover -- a slow first buffer is a slow start too, distinct from
both an ordinary crash AND from a preroll that never reached PLAYING at all,
and needs its own exit code for the same relaunch-path reason above.
"""

from __future__ import annotations

# 0 = clean exit (unchanged).
# 1 = generic worker error/crash — every engine failure except the ones named
#     below (unchanged: this is still the default `main()` returns for a
#     non-None `result["error"]`, e.g. the post-first-buffer S9-5 stall
#     watchdog, ``("stall", ...)``).
# 2 = worker.py usage error (missing argv[1]) — predates this change.
GST_PREROLL_TIMEOUT_EXIT_CODE = 3
# Item 84: the pipeline reached PLAYING but never produced a single output
# buffer within ``GstPlayoutEngine.first_output_timeout_s`` -- a slow start
# under load, not a crash and not a preroll failure. See
# ``GstPlayoutEngine._check_stall`` (the ``("first-output-timeout", ...)``
# error reason) and ``EgressDaemon._relaunch_after_crash``, which rate-limits
# this exit the same way it already does ``GST_PREROLL_TIMEOUT_EXIT_CODE``.
GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE = 4

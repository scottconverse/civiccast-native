#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# scripts/ci/install_media_test_prerequisites.sh
#
# Shared "install ffmpeg + tsduck for the media test suites" step for
# hosted-ubuntu CI jobs -- ci-test.yml's `Unit tests` job and
# deterministic-detectors.yml's `randomized-suite` job. Both jobs used to
# carry a near-identical copy of this shell inline; consolidated here so a
# fix lands once instead of drifting between copies.
#
# Two documented hosted-runner failure modes, both bounded below:
#
#   1. unattended-upgrades / apt-daily*.timer holds the dpkg/apt locks on
#      boot. Bare `apt-get` waits on that lock FOREVER: on 2026-08-19 this
#      step sat in_progress for 3h49m on the release branch and ~2h on PRs
#      #422/#423, silently wedging the whole merge queue while every other
#      job showed green.
#   2. The Azure-hosted mirror (azure.archive.ubuntu.com) occasionally
#      serves a handful of packages at a few hundred KB/s instead of its
#      usual multi-MB/s. Confirmed 2026-09-02 across three independent runs
#      that never touched the dpkg lock at all -- every one timed out at
#      exit 124 stalled mid-download of a single large package:
#        - PR #131 "Unit tests" job 100278667553 (libflite1, 13.6 MB,
#          stalled from 14:08:54 past the old 300s per-call bound)
#        - PR #135 "randomized-suite" job 100284786583 (libdav1d7, stalled
#          from 14:20:16 to 14:24:41 -- 4m25s for a 604 kB package)
#        - PR #132 "randomized-suite" job 100287702253 (same pattern)
#
# Bound both causes: stop the background upgrader before touching apt, wait
# for the dpkg/apt locks with a visible bounded loop, retry the network, and
# give the whole step enough headroom to survive a slow mirror -- but not
# forever. On failure, dump what's still holding apt/dpkg so the next
# failure is diagnosable from the log alone.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

LOCK_WAIT_SECS="${APT_LOCK_WAIT_SECS:-180}"
APT_TIMEOUT_SECS="${APT_CALL_TIMEOUT_SECS:-480}"
APT=(sudo -n apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3)

echo "::group::Stopping the runner's background apt/dpkg holders"
# unattended-upgrades and the apt-daily* timers/services are what held the
# dpkg lock for 3h49m on 2026-08-19. Stop and kill them defensively before
# ever touching apt ourselves; `|| true` throughout because a hosted image
# that has already finished (or never started) these units must not fail
# this step -- their absence is success, not an error.
sudo -n systemctl stop unattended-upgrades apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
sudo -n systemctl kill --kill-who=all apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
echo "::endgroup::"

echo "::group::Waiting for dpkg/apt locks (bounded to ${LOCK_WAIT_SECS}s)"
waited=0
while sudo -n fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1; do
  if [ "$waited" -ge "$LOCK_WAIT_SECS" ]; then
    echo "::warning::dpkg/apt locks still held after ${LOCK_WAIT_SECS}s; proceeding anyway -- apt-get's own DPkg::Lock::Timeout=120 makes the final call."
    break
  fi
  echo "Locks still held after ${waited}s, holder(s):"
  sudo -n fuser -v /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock 2>&1 || true
  sleep 5
  waited=$((waited + 5))
done
echo "::endgroup::"

report_apt_diagnostics() {
  echo "::group::apt/dpkg diagnostics (step failed)"
  ps -ef | grep -E 'apt|dpkg|unattended' | grep -v grep || true
  echo "::endgroup::"
}
trap report_apt_diagnostics ERR

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  timeout "$APT_TIMEOUT_SECS" "${APT[@]}" update
  timeout "$APT_TIMEOUT_SECS" "${APT[@]}" install -y ffmpeg
fi

# #151 TS-relay behavioral splice test (skips without tsp).
#
# GauntletGate T5: this tolerates a failed install with a warning and has NO
# junit-floor guard, unlike the suites gated on ffmpeg above. That is a
# DELIBERATE choice, not an oversight: TS-relay splice compliance belongs to
# the deferred `civiccast-cable` add-on (CLAUDE.md, closed architectural
# decisions), not the WSL lane's ship-critical streaming core. Cable-add-on
# CI coverage is intentionally best-effort until the add-on itself is in
# scope. If cable ships, this needs a floor guard matching the ffmpeg
# pattern above.
if ! command -v tsp >/dev/null 2>&1; then
  timeout "$APT_TIMEOUT_SECS" "${APT[@]}" install -y tsduck || echo '::warning::tsduck not installable; TS-relay splice test will skip (best-effort by design; see comment)'
fi

trap - ERR

ffmpeg -version | head -n 1
ffprobe -version | head -n 1

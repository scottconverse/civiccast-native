# CivicCast beta.12 - Field-Test Quick Start

This is a field-test guide for the native Windows beta. It is not a production
cutover instruction. `v1.0.0-beta.12` is the current published GitHub
pre-release, published October 10, 2026, with the station-download distribution
repair added October 11. The candidate is source
`a0c98cb7367dc106042ec89d35a91905470d350c`, producer run `38097350705`.
See the [Beta 12 verification record](releases/v1.0.0-beta.12-verification.md)
for observed results and limits. Follow only the exact procedure in the
owner-authorized tester handoff.

## Before you begin

1. Read the exact Beta 12 tester handoff and the Windows release-trust
   instructions.
2. For a first install or upgrade, use the complete download from the exact
   release. The handoff names the release helper,
   `download_windows_release_artifacts.ps1`, and its `-Install` option.
   It downloads and verifies `setup.exe`, the five runtime packs, and the
   multipart station-model bundle, then runs setup with `/S`. Do not install
   `setup.exe` alone. The October 11 R9 attempt predates this repair: it
   failed with actual installer exit 123 after four required signed station
   packs were missing and their embedded-index URLs were empty. That previously
   used machine had residual files and model caches, so the failure is not
   clean-machine or complete-kit installation proof and did not test the
   repaired download.
3. The recorded Beta 11-to-Beta 12 CPU-only Sandbox upgrade setup exited 0,
   reached a healthy service/API at schema 0089, preserved the initial data
   marker, and observed initial three-channel output with Whistle within
   capacity. The recorder wrapper failed at its first JSON save; no five-
   snapshot PASS was recorded. Do not assume this observation qualifies a
   fresh install, the repaired download, repair, or another station.
4. Before running the helper, compare its SHA-256 with its entry in the
   same-release `SHA256SUMS.txt` using the [Windows release-trust
   instructions](install/windows-release-trust.md). The helper then verifies
   the setup signature and hash, sidecar, runtime-pack hashes, multipart
   station parts and extracted file hashes. Setup checks the signed station
   metadata. Stop if any value differs.

## Install

1. Use the exact release-matched downloader named by the handoff and select
   `-Install`. It stages runtime packs under `packs\`, verifies and
   extracts the station bundle into `station\`, then runs the signed
   `setup.exe` with `/S`. Do not substitute a source ZIP, older release,
   or generic latest download. A fresh offline Sandbox setup and station
   activation completed with exit 0 and the service `Running`; the follow-on
   first-admin/three-channel check failed with only the first Python traceback
   line captured, so its cause is unresolved. Full UI/channel validation is not
   established; see the [verification record](releases/v1.0.0-beta.12-verification.md).
2. If Windows shows **Windows protected your PC**, choose **More info** and
   confirm the publisher is Scott Converse before continuing. If the publisher,
   filename or hash is wrong, choose **Don't run** and contact your technical
   lead.
3. Keep the PowerShell downloader window open until it reports **Done**. It
   waits for setup and reports a nonzero setup exit as an error. Preserve the
   console output and installer log at
   `C:\ProgramData\CivicCast\install-progress.log`; do not rerun after a
   failure without technical-lead review.
4. The helper runs setup with `/S`; it does not open the interactive model
   selection window. After setup returns successfully, open **First setup**
   from the **CivicCast Operator Console** shortcut or
   `http://127.0.0.1:8000/operator/`. A successful setup exit alone does not
   prove that first-admin setup or station readiness completed.

## First setup and recovery

1. On the station itself, open **First setup** from the **CivicCast Operator
   Console** shortcut, or by opening `http://127.0.0.1:8000/operator/` in a
   browser on the station.
2. Enter the station name and create the first administrator account.
3. When CivicCast shows the one-time recovery codes, select **Print kit** or
   **Save kit** and store the result away from the computer. Do not put codes
   or passwords in a report. Continue to the console only after the recovery
   kit is safely stored.
4. Confirm **System Health** is green. This is an installation check, not yet a
   beta release or production-readiness claim.

## Field-test boundary

Keep the station private while testing. Run the assigned rehearsal and tester
checks, record the exact candidate SHA and installed version, and wait for the
station owner's cutover decision. Routine steps within the assigned field
test do not need a new approval at every screen. Do not treat reaching the
operator console, an installer exit code of zero, or a version number as
proof that the station is ready for public cutover.

## If the download or setup fails

- Preserve the first failure. Record the release tag, helper filename, time,
  PowerShell output, and setup exit code if reported. Do not rerun setup before
  the technical lead reviews the failure.
- Setup runs with `/S`, so do not wait for the interactive model window or use
  its **Open installer log** button. Check
  `C:\ProgramData\CivicCast\install-progress.log` and preserve the downloader
  console output.
- If setup returned zero but the operator console or First setup is unavailable,
  record that separately. Do not treat the installer exit alone as proof that
  the service or station is ready.


## Verification limits - read before operating a station

The repaired public kit completed fresh offline Sandbox setup and station
activation: setup exited 0, the service was `Running`, and offline Ollama and
CPU faster-whisper self-tests passed. A follow-on first-admin/three-channel
check failed; only the generic first Python traceback line was captured, so its
cause is unresolved and full UI/channel validation is not established. No
repair, upgrade retest, or sustained-operation result is recorded. The R9 exit
123 was observed with the earlier incomplete asset set and does not test the
repaired package. See the [captured fresh-install result](ops/evidence/beta12-public-fresh-install-2026-10-11.json).

The Beta 12 Sandbox upgrade evidence is limited: setup exited 0, the service
and API were healthy at schema 0089, an initial-data marker survived, and
initial three-channel output was observed with Whistle within capacity. The
recorder failed during its first JSON save with
`Cannot convert value to type System.String.`; no five-snapshot PASS or
sustained-operation result was recorded.

The Beta 11 host caption run recorded 99.88% positive caption-input presence
across its sampled three-channel, 48-hour run. That is input-coverage
observation, not word accuracy, legal compliance, or Beta 12 caption
acceptance. No automatic 99% or 98% coverage floor was adopted; the station
owner decides what evidence is adequate. The run's excluded interval and other
reported limits are in its dated host report.

Live captions use Whistle CPU as the primary path, with per-channel Whisper
fallback. Whisper fallback is lazy; first-pass success does not establish
agreement with Whisper, and telemetry was disabled during the Beta 12 first
pass. Supported NVIDIA CUDA systems may accelerate Whisper work, but CPU-only
Medium Whisper fallback has not demonstrated real-time capacity. AMD or Intel
graphics do not imply Whisper GPU acceleration.

See the [Beta 12 verification record](releases/v1.0.0-beta.12-verification.md)
for package scope and limitations. SDI hardware, a cable headend and production
cutover require separate evidence.

## After a successful field test

Keep the signed kit, trusted handoff, installer log, recovery-kit confirmation,
and candidate-bound tester evidence together. A successful local installation
or soak is evidence for the named candidate only. Beta 12 is the current public
pre-release, with the incomplete verification scope described above. Field
results inform suitability for your station; production cutover remains the
station owner's decision.

# CivicCast beta.11 - Field-Test Quick Start

This is a field-test guide for the native Windows beta. It is not a production
cutover instruction. Use the exact beta release named in your tester handoff;
the public release page and `release-truth.yaml` decide which version is
currently available.

## Before you begin

1. Read the exact beta.11 tester handoff and the Windows release-trust
   instructions.
2. Use the complete signed beta.11 USB/LAN kit for a first install unless the
   handoff names a different, verified test path. The kit
   includes the installer, runtime packs, and the signed `station\` model
   bundle (about 21 GB), the offline way to bring the large AI components. The
   installer itself is small: its window also explains each large component,
   uses a copy already on the computer (**Found locally - verified**) and
   downloads the rest with a progress display and a **Stop downloading**
   button. The setup-only path with no complete kit has not been proven for a
   first install of this beta.11 candidate.
3. For an upgrade, use only the exact installer and procedure named in the
   handoff. Do not assume that another release's upgrade evidence covers this
   candidate.
4. Have your technical lead verify the exact installer filename and SHA-256
   against the trusted handoff, plus a `Valid` Authenticode signature whose
   publisher is **Scott Converse**. For a GitHub download, also verify the
   release's `setup.exe.sidecar.json`. In the USB/LAN kit,
   `station\SHA256SUMS.txt` covers the station bundle; use the trusted handoff
   for the installer hash. A matching hash alone is not proof of publisher
   identity. If any value differs, stop and report the mismatch.

## Install

1. On the station computer, open the signed USB/LAN kit and run its branded
   `CivicCast (Native)_1.0.0-beta.11_x64-setup.exe` installer. A GitHub download
   uses the name `setup.exe`; its hash must identify the same approved release.
   Do not substitute a source ZIP, an older release, or a generic "latest"
   download.
2. If Windows shows **Windows protected your PC**, choose **More info** and
   verify that the publisher is Scott Converse. If the publisher, filename, or
   hash is wrong, choose **Don't run** and contact your technical lead. If the
   checks match the approved test kit, choose **Run anyway** to continue.
3. Leave the installer open while it works. It should show changing progress
   details. Do not restart, close the window, or run a second installer during
   this step.
4. Complete the installation wizard using the **Next** or **Finish** buttons
   it shows. If the separate **CivicCast Installer** window opens, follow
   **Checking This Computer** and **What CivicCast Needs**, using **Continue**
   when offered. Local components should be marked **Found locally - verified**
   with a check mark. Wait for the setup steps to complete. The operator
   console may open automatically; if it does not, select **Open operator
   console** or use the **CivicCast Operator Console** shortcut.

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

## If the installer or setup window appears stuck

- If a step is taking a long time, first read the current status text and leave
  the window open. A long-running step is not proof of success or failure.
- Do **not** assume that **Waiting** means everything is installed. Do not
  select **Stop downloading** merely to continue. Inspect the installer log,
  verify **System Health**, and contact your technical lead if the state does not
  advance.
- In the installer window select **Open installer log**. If the window has
  closed, collect:

  `C:\ProgramData\CivicCast\install-progress.log`

  Also record the exact visible status, timestamp, candidate filename, and the
  last completed step. Do not retry repeatedly; a second run can obscure the
  first failure.
- If **System Health** is not green, the operator console cannot be reached,
  the service is missing, or any item is red, stop and report the evidence.
  Do not call the station installed or publish recordings from that failed
  setup. Preserve the logs and consult your technical lead before retrying or
  rebooting to clear an unexplained failure.

## Known limits of this beta.11 candidate - read before operating a station

The owner accepted a 24-hour three-station caption soak on the local beta.11
development overlay. It recorded 198 successful sampled channel checks across
66 eligible checkpoints; four checkpoints during an excluded gaming interval
were omitted. The overlay ran on a beta.9 station and is not proof that this
packaged beta.11 installer works.

The caption checks sampled decoding, freshness and continuity. They do not
prove accurate recognition of every word or captions for every second. Native
recognition timings exclude time waiting for the shared inference lock and
complete caption latency. Short monitor captures do not establish broadcast
loudness. Program-transition retries, lost acknowledgements and bounded relay
log trims were observed during the longer run; the sampled caption checks
passed. Check the station's actual output during the assigned field test and
report caption, audio, video and service problems separately.

Live captions use Whistle on the CPU, with Whisper as a backup; supported
NVIDIA CUDA systems can select Whisper as the primary engine. CPU-only Medium
Whisper fallback has not demonstrated real-time capacity. AMD or Intel
graphics do not imply Whisper GPU acceleration.

The corrected Beta 11 package from source `400cff08` passed a fresh offline
CPU-only Windows Sandbox installation with the complete kit, installed Help
verification, and a five-minute single-channel Whistle output check. See the
[package verification record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.11-verification.md).
Upgrade, repair, setup-only downloading, GPU operation and sustained
three-channel capacity remain unverified for that revision. SDI hardware,
a cable headend and production cutover are outside this field-test evidence.

## After a successful field test

Keep the signed kit, trusted handoff, installer log, recovery-kit confirmation,
and candidate-bound tester evidence together. A successful local installation
or soak is evidence for the named candidate only. Beta 11 is already publicly
published as a pre-release; field results inform suitability for your station.

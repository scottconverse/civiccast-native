# CivicCast beta.5 - Field-Test Quick Start

This is a field-test guide for the native Windows beta. It is not a production
cutover instruction. Use the exact beta release named in your tester handoff;
the public release page and `release-truth.yaml` decide which version is
currently available.

## Before you begin

1. Read the exact tester handoff and the Windows release-trust instructions.
2. Use the complete signed beta.5 USB/LAN kit for a first install. The kit
   includes the installer, runtime packs, and the signed `station\` model
   bundle (about 21 GB). A GitHub download by itself does not provide the model
   bundle needed by a new station.
3. If this is an upgrade from an already-installed beta.3-or-later station,
   use only the exact release assets the handoff names. Existing recordings,
   database data, settings, and cached AI models are retained by the supported
   in-place upgrade path.
4. Have your technical lead verify the exact installer filename and SHA-256
   against the trusted handoff and `SHA256SUMS.txt`, plus a `Valid`
   Authenticode signature whose publisher is **Scott Converse**. For a GitHub
   download, also verify the release's `setup.exe.sidecar.json`. The complete
   USB/LAN kit uses its own delivery manifest; do not assume it contains that
   GitHub sidecar. A matching hash alone is not proof of publisher identity.
   If any value differs, stop and report the mismatch.

## Install

1. On the station computer, open the signed USB/LAN kit and run its branded
   `CivicCast (Native)_1.0.0-beta.5_x64-setup.exe` installer. A GitHub download
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
   Console** shortcut or the installer handoff URL.
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
test do not need a new approval at every screen. Do not treat reaching the operator console,
an installer exit code of zero, or a version number as proof that the station
is ready for public cutover.

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

## After a successful field test

Keep the signed kit, hash manifest, installer log, recovery-kit confirmation,
and candidate-bound tester evidence together. A successful local installation
or soak is evidence for the named candidate only; it does not by itself make
beta.5 the public current release.

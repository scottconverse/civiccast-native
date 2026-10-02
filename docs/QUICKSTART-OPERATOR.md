# CivicCast beta.10 - Field-Test Quick Start

This is a field-test guide for the native Windows beta. It is not a production
cutover instruction. Use the exact beta release named in your tester handoff;
the public release page and `release-truth.yaml` decide which version is
currently available.

## Before you begin

1. Read the exact tester handoff and the Windows release-trust instructions.
2. Use the complete signed beta.10 USB/LAN kit for a first install. The kit
   includes the installer, runtime packs, and the signed `station\` model
   bundle (about 21 GB), the offline way to bring the large AI components. The
   installer itself is small: its window also explains each large component,
   uses a copy already on the computer (**Found locally - verified**) and
   downloads the rest with a progress display and a **Stop downloading**
   button. A first install that has no kit and no earlier install and relies
   only on downloads is not yet proven for beta.10, so use the kit your
   handoff names.
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
   `CivicCast (Native)_1.0.0-beta.10_x64-setup.exe` installer. A GitHub download
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

## Known limitations of this build (v1.0.0-beta.10) - read before operating a station

`v1.0.0-beta.10` is a beta candidate. It was held on air for eight hours on a
three-channel lab station with no restart, no black or silent gaps at program
changes, and loudness in range. The formal station acceptance (Gate A) has not
been run for it, and no human field tester has signed off on it. These are the
known, measured limits:

**Some spoken words can go without captions when the machine is busy.**
- Captions stay on the air on all three channels. When a channel's caption
  worker falls behind (most often while the station is preparing a long program
  for the first time), it skips its oldest audio to catch up instead of pausing
  for minutes. Those skipped seconds have no caption.
- In the eight-hour run this happened 13 times. On a quiet machine the total was
  about 160 seconds of speech across two channels.
- A fix is the next work item and is not in beta.10. **If your station must have
  every spoken word captioned, tell your technical lead before relying on this
  build, and check the captions during live meetings.**

**A program change can retry once.**
- Twice in eight hours a program change on the government channel did not take
  on its first try and corrected itself in about three seconds. Viewers saw
  nothing.

**One single-frame video drop.**
- One known one-frame (about 0.03 second) picture drop can happen where two
  parts of the same program join. It was seen once in eight hours.

**Quiet recordings are not boosted without limit.**
- Speech is leveled toward -16 LUFS (a standard loudness measure) when a program is prepared for air. A
  stretch of a recording that is too quiet for the leveling to reach the target
  is reported in the log, not boosted further, so it can sound quieter than
  the rest.

**Carried over from beta.9 and not re-tested in the beta.10 run.**
- When a channel's scheduled programming runs out and the schedule does not
  repeat, the channel can stop and need a manual start. The error then tells you
  to check the program's media even though the schedule is the problem.
- `/api/health` can report healthy while a channel is unable to air.
- The built-in decode-back check (it decodes the broadcast to confirm the
  captions) failed on certain cue timings in beta.9 and was not re-tested.

**Not proven.**
- Runs longer than eight hours, a real station, SDI hardware and a cable
  headend have not been tested for this build.

**Disk space.**
- CivicCast now keeps up to 60 GB of prepared copies of long programs (the
  default; it was 20 GB). Leave room on the data drive, or set
  `CIVICCAST_CONFORM_CACHE_GB` to a smaller number.

## After a successful field test

Keep the signed kit, hash manifest, installer log, recovery-kit confirmation,
and candidate-bound tester evidence together. A successful local installation
or soak is evidence for the named candidate only; it does not by itself make
beta.10 the public current release.

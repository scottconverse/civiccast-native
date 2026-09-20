# CivicCast beta.9 - Field-Test Quick Start

This is a field-test guide for the native Windows beta. It is not a production
cutover instruction. Use the exact beta release named in your tester handoff;
the public release page and `release-truth.yaml` decide which version is
currently available.

## Before you begin

1. Read the exact tester handoff and the Windows release-trust instructions.
2. Use the complete signed beta.9 USB/LAN kit for a first install. The kit
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
   `CivicCast (Native)_1.0.0-beta.9_x64-setup.exe` installer. A GitHub download
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

## Known limitations of this build (v1.0.0-beta.9) - read before operating a station

These are known, measured limitations of `v1.0.0-beta.9`. A **beta.10** release
is coming soon that addresses the caption interruptions on program changes, the
escalation behaviour, the end-of-schedule stop, and the playout worker stalls.
**If you are running a station where captions must stay up unattended, wait for beta.10.**

**Caption reliability - two channels are clean, three are not.**
- Captions run on the GPU, and caption text reaches the emitted output.
- **One and two channels are clean and measured.** Across one-channel and
  two-channel runs, per-segment latency stayed flat at about 5.3 seconds with
  **zero** caption backlog trips.
- **Three channels is the problem.** On the earlier code, three channels
  produced four or more backlog trips in a measured window, with latency
  spiking to 106 seconds. This is **not** a graphics-card limit: VRAM peaked at
  about 52% (about 7.6 GB free) and GPU use averaged 19%.
- With the caption-retention fix in this build, a **30-minute three-channel run
  had zero trips** (against 111 trips in 103 minutes on the earlier code).
- **Sustained three-channel operation is not proven.** The two-hour, four-hour,
  eight-hour, 25-hour and 72-hour runs were **not** completed. Do not read the
  30-minute result as a guarantee that three channels will stay healthy all day.

**Caption interruptions when the program changes.**
- A scheduled program change can trigger a channel reload that times out,
  restart the video worker, and clear captions. Caption blackouts on the three
  captured occurrences were **2.3, 2.8 and 4.6 minutes**.
- A worker can also exit cleanly (exit code 0) with no error and still clear
  captions.
- The pause and escalation ladder **never escalates** in practice: every trip is
  treated as a first offence and the wait never grows beyond the base window. A
  channel that trips repeatedly does not back off.
- A caption blackout per backlog trip is about **210 seconds** - not the 120
  seconds the log message implies (120 seconds of pause plus about 90 seconds to
  earn the recovery bar).

**Playout worker stalls.**
- A playout worker can stall with "no output for 10s" and be relaunched by the
  watchdog. The channel oscillates between STARTING, fallback slate and ON_AIR
  instead of holding air, and captions do not accumulate while it does.
- **This is frequent and long-standing, not rare.** In the retained five-day log
  window it fired **68 times** (1 on 09-14, 7 on 09-15, 20 on 09-16, 28 on
  09-17, 12 on 09-18).
- **It is unevenly distributed across channels:** 55 of the 68 stalls were on
  the public channel, 9 on government and 4 on education. A single channel can
  carry the large majority of the failures.
- A clean STOP then START does **not** clear it; the stall recurs on a fresh
  launch. The channel with the heaviest source is the one most likely to be
  stuck.

**End-of-schedule behaviour.**
- When a channel's scheduled programming runs out, the channel can be
  **STOPPED** and require a **manual start**, with an error telling the operator
  to check the program's media. That message is **misleading in this case** -
  the media is fine; the schedule is empty.

**Health endpoint.**
- `/api/health` can report **healthy while a channel is unable to air**.

**Decode-back verification.**
- There is **no working decode-back proof** in this build; the self-check
  currently fails on certain decoded cue timings.

## After a successful field test

Keep the signed kit, hash manifest, installer log, recovery-kit confirmation,
and candidate-bound tester evidence together. A successful local installation
or soak is evidence for the named candidate only; it does not by itself make
beta.9 the public current release.

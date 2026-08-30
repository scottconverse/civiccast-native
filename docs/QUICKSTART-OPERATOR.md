# CivicCast — Quick Start

**For the person setting up a new CivicCast station.** No computer experience
required. Follow the numbered steps in order. Everything CivicCast needs is on
the USB kit — no internet connection is required.

Set aside about **45 minutes**. Most of that is the computer working on its own.

---

## 1. Plug in the USB kit

Plug the CivicCast USB stick into the station computer.

## 2. Open the USB drive and double-click the setup program

It has a CivicCast icon and a name like `CivicCast (Native)_1.0.0-beta.1_x64-setup.exe`.

Windows asks one question before setup starts:

- **"Do you want to allow this app to make changes to your device?"** — click
  **Yes**. (Setup needs this to install the station.) The box names
  **Scott Converse** as the verified publisher; CivicCast is signed software.

## 3. Step through the first three setup screens

Setup opens a small window. Click the button at the bottom right each time:

1. A welcome page — click **Next**.
2. A page showing where CivicCast will be installed — leave it as it is and
   click **Next**.
3. Setup installs. **This takes about 30 minutes.** A progress bar moves and the
   text changes as it works. Leave it alone; don't close it, don't restart the
   computer.
4. When it says **Installation Complete**, click **Next**, then click
   **Finish** (leave both checkboxes ticked).

## 4. Let the CivicCast Installer finish the setup

Clicking Finish opens a second, larger window called **CivicCast Installer**.
This one does the last few steps:

1. **Checking This Computer** — it lists what it found and recommends a caption
   engine. Click **Continue**.
2. **What CivicCast Needs** — a list of the large pieces. Click **Continue**.
3. **Setting Up** — each item should say **"Found locally — verified ✓"**
   because everything came from your USB kit. Wait for it to finish.
4. When it's done, click **Open operator console**.

## 5. Follow First Setup

A page called **First setup** opens in your browser. Fill it in from top to
bottom:

- **Station name** — what your station is called.
- **Your admin account** — a display name, a username, and a password for
  yourself. This is the login you'll use from now on.
- **SAVE THE RECOVERY KIT.** Near the end, CivicCast shows a one-time set of
  recovery codes. Click **Print kit** or **Save kit** and put the codes
  somewhere safe **away from this computer** (a locked drawer or a safe — not a
  sticky note on the monitor). These codes are the *only* way back in if the
  admin password is ever lost, and CivicCast can never show them again. Once
  they're stored, tick the box and click **Continue to the console**.

## 6. You're live

You're signed in at the operator console — where you run meetings, manage
recordings, and check on the station.

**To get back here later**, use the **CivicCast Operator Console** shortcut on
the desktop or in the Start menu. You never need to run setup again.

The public page residents visit is at:

```
http://<this computer>:8000/
```

Ask your IT person for this computer's name or address to use in place of
`<this computer>` — for example `http://station-1:8000/`.

---

## If something looks wrong

- **A blue "Windows protected your PC" screen appears.** Uncommon — CivicCast
  is signed, but a computer that has never seen this publisher before can still
  show it once. Click **More info**, then **Run anyway**. Check that it names
  **Scott Converse** as the publisher; if it names anyone else, stop and call
  your IT person.

- **A step is taking a long time.** Installing takes about 30 minutes and the
  final setup a few more. As long as the window is on screen, it's working.
  It's safe to leave it and come back.

- **An item says "Waiting" and never starts.** Everything you need is already
  installed at that point — the station is running even if that screen looks
  stuck. Click **Stop downloading**, then **Open operator console** and carry
  on with Step 5.

- **You see "First setup can only be done from the station computer itself."**
  You're looking at the console from a different computer. First setup has to be
  done sitting at the station computer — open the **CivicCast Operator Console**
  shortcut on that machine and start again from Step 5. (Once setup is finished,
  the public page can be viewed from anywhere on the network.)

- **Anything shows up red, or an error you don't understand.** Stop and call
  your IT person. Don't guess. In the installer window, click **Open installer
  log** to hand them the exact record. If setup already closed, the same log is
  saved at:

  ```
  C:\ProgramData\CivicCast\install-progress.log
  ```

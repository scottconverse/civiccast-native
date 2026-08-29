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

Two Windows screens may appear before setup starts:

- A blue **"Windows protected your PC"** screen — click **More info**, then
  **Run anyway**.
- A **"Do you want to allow this app to make changes to your device?"** box —
  click **Yes**. (Setup needs this to install the station.)

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

- **A step is taking a long time.** Installing takes about 30 minutes and the
  final setup a few more. As long as the window is on screen, it's working.
  It's safe to leave it and come back.

- **An item says "Waiting" and never starts.** Everything you need is already
  installed at that point — the station is running even if that screen looks
  stuck. Click **Stop downloading**, then **Open operator console** and carry
  on with Step 5.

- **You see a page that says "This station hasn't been set up yet."** You
  reached the console without going through the installer's **Open operator
  console** button. Go back to the CivicCast Installer window and click that
  button. If you already closed it, call your IT person.

- **Anything shows up red, or an error you don't understand.** Stop and call
  your IT person. Don't guess. In the installer window, click **Open installer
  log** to hand them the exact record. If setup already closed, the same log is
  saved at:

  ```
  C:\ProgramData\CivicCast\install-progress.log
  ```

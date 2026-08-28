# CivicCast — Quick Start

**For the person setting up a new CivicCast station.** No computer experience
required. Just follow the numbered steps in order.

---

## 1. Plug in the USB kit

Plug the CivicCast USB stick into the station computer.

## 2. Double-click the setup program

Open the USB drive and double-click the CivicCast setup program (it has a
CivicCast icon and a name like `CivicCast (Native)_x64-setup.exe`).

Windows may show a blue **"Windows protected your PC"** screen. This is
normal for a new installer — click **More info**, then **Run anyway**.

## 3. Wait

Setup does everything on its own: it installs CivicCast, starts it, and
downloads the AI models the station uses for captions and meeting summaries.

**This can take anywhere from a few minutes to over an hour**, depending on
your internet connection — the AI models alone are several gigabytes. That's
normal. The screen stays active and shows what step it's on, so as long as
something is moving, it's working.

**It's safe to leave it running.** Don't close the window and don't unplug
or restart the computer while it's working. You don't have to watch it —
check back in a while.

## 4. Click "Open operator console"

When setup is done, its button changes to say **"Open operator console."**
Click it.

*(From now on, you don't need to run setup again to get back here — use the
**CivicCast Operator Console** shortcut on the desktop or in the Start
menu instead.)*

## 5. Follow First Setup

A page called **First setup** opens in your browser. Fill it in from top to
bottom:

- **Station name** — what your station is called.
- **Your admin account** — a display name, a username, and a password for
  yourself. This is the login you'll use every time you come back to the
  operator console.
- **SAVE THE RECOVERY KIT.** Near the end, CivicCast shows a one-time set of
  recovery codes. Click **Print kit** or **Save kit** and put the codes
  somewhere safe **away from this computer** (a locked drawer, a safe — not
  a sticky note on the monitor). These codes are the *only* way back in if
  the admin password is ever lost, and CivicCast can never show them again.
  Once you've stored them, check the box and click **Continue to the
  console**.

## 6. You're live

You're now signed in at the operator console — this is where you run
meetings, manage recordings, and check on the station.

The public page residents visit is at:

```
http://<this computer>:8000/
```

(Ask your IT person for this computer's real name or address to put in
place of `<this computer>` — for example `http://station-1:8000/`.)

---

## If something looks wrong

- **Setup is still on the same screen with no "Open operator console"
  button yet.** It's still working — see Step 3. Wait.
- **You see a page that says "This station hasn't been set up yet."** You
  reached the operator console without going through the CivicCast
  installer first. Go back to the installer window from Step 4 and click
  **Open operator console** there — that's the link that carries the
  station through First Setup correctly. If the installer window is
  already closed, run the setup program from Step 2 again.
- **Anything shows up red, or an error you don't understand.** Stop and
  call your IT person. Don't guess. In the setup window, click **Open
  installer log** to hand them the exact record of what happened. If setup
  already closed, the same log is saved at:

  ```
  C:\ProgramData\CivicCast\install-progress.log
  ```

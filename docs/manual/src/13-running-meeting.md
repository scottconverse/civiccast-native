# Running the meeting {#ch-running-meeting}

This chapter is for the people who work the room on meeting night: the camera operator, the meeting operator, and the volunteer who watches the screen while the council meets. It shows you how to check that the station is ready, run a live session, start and stop a channel, take a channel live from a camera, put scheduled programs on the air, drive the production control room, show community announcements between programs, and bring in remote guests. It also tells you, control by control, what each button really does. In this version of CivicCast several buttons that sound like "go on air" do something smaller than their names say, and a few things happen without any "Are you sure?" box.

> **Note:** CivicCast beta.11 is a GitHub pre-release for testing, not a production release. This chapter explains the current controls and their behavior; a **Known issue (beta.11)** box calls out a current mismatch between a screen and the program. Package-specific checks and limits are in the [beta.11 verification record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.11-verification.md).

## Before you start

**Where the screens are.** Everything in this chapter is in the left-hand menu of the operator console, in the section called **Run Meeting**: **Live**, **Facility**, **Control Room**, **Remote Contribution**, **Channels**, **CG Board** and **CG Designer**. The **Readiness** screen is in the section called **System Health**, which is folded shut until you click its name. If you have yet to sign in, see [Signing in and finding your way around](#ch-signing-in).

**Who can press what.** CivicCast has five roles. The table lists the role each control in this chapter needs. If your sign-in lacks the role, the screen usually shows a grey or amber note instead of working buttons.

| What you want to do | Role you need |
| --- | --- |
| Create, run and end a live session (Live) | Meeting operator |
| Check a meeting source (Live) | Meeting operator or Setup admin |
| Change a meeting source's address (Live) | Setup admin |
| Start, stop and restart a channel's feed (Channels) | Meeting operator |
| Take a channel live, return to schedule (Channels) | Meeting operator or Setup admin |
| Approve a program to air, take it off (Channels) | Publish operator or Setup admin |
| Change "Keep this channel on air" and other 24/7 settings | Setup admin |
| Lower-third banner (Channels) | Meeting operator (the screen only enables it for this role) |
| Open a Control Room session and fire cues | Meeting operator |
| Create a remote-guest room | Setup admin |
| Open a room, invite, admit, put guests on air | Meeting operator |
| Add and review community bulletins (CG Board) | Publish operator or Setup admin |
| Change the board layout (CG Designer) | Publish operator or Setup admin (Support admin can look only) |
| Facility router previews | Meeting operator or Support admin (see the Known issue in the Facility task) |

> **Note:** The sign-in screen accepts the station administrator's password or a recovery code, and that account carries all five roles. On most stations that means everyone who signs in can do everything in the table. The limits matter only if your IT person has arranged limited sign-ins. See [Signing in and finding your way around](#ch-signing-in).

**What must already be set up.** CivicCast cannot do these things from the screens in this chapter, so someone with the Setup admin role must have done them first.

* A meeting source (a camera or encoder CivicCast can pull video from) has been added. If none exists, the **Live** screen shows a card titled "Choose a camera or test source" with a link **Open camera and test media setup**.
* Each channel has an *outgoing-feed configuration*. This is the saved description of where the channel's video is sent (the resident web player, the *cable headend* - the equipment at the cable company that puts your channel on the cable system - and so on). Without one, the **Start** button on **Channels** stays grey.
* A recording location exists (the Live screen lists it as "Recording targets").

> **For IT staff:** setup of sources, outgoing feeds and recording locations is in [Configuring the station](#ch-configuration) and [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations).

**Times on these screens.** No screen in this chapter asks you to type a time. Times that CivicCast shows you (for example, in the list of programs on **Channels**) are formatted by your web browser in the time zone of the computer you are using. The one exception is the Control Room "locked by ... since ..." message, which shows the time in a raw year-month-day form that is normally UTC.

### Several different things called "on air"

The most important idea in this chapter: CivicCast has several separate controls that all say "on air", and each changes something different. Read this table once before meeting night.

| What you press | What it really changes |
| --- | --- |
| **Live** > **Start Live Stream** | The *live session record* and the public "on air" status residents see on the portal home page. It does **not** start or switch the channel's video feed. |
| **Channels** > **Start**, **Stop**, **Restart feed**, **Finish current item, then stop** | Sends a command to the channel's feed program. This is what starts and stops the channel's actual video. |
| **Channels** > **Take live** | Switches the channel from its schedule to a camera or encoder source right now. |
| **Channels** > **Approve & put on air** | Approves one scheduled program so it plays at its scheduled time. It does not play it at the moment you click. |
| **Remote Contribution** > **Take channel live** | Switches the channel to its configured live source after confirmation. It does not route a contribution guest into that source. |
| **Control Room** > **Fire cue** | Sends a command to your production gear (OBS, vMix, a camera, a router). It does not put anything on a channel. |

### A few words used here

* **Channel:** one outgoing program stream, such as "government". It has its own schedule and its own feed.
* **Feed (outgoing feed):** the background program that builds a channel's video and sends it to its outputs. Starting and stopping a channel means starting and stopping this feed.
* **Slate:** a plain card the channel shows when nothing is scheduled. The channel screens call this state "Showing slate".
* **Source:** a camera, encoder or test video CivicCast can pull live video from.
* **Session:** a period of work that has a start and an end, in the Live room or the Control Room.

## Check that the station is ready

Do this early on meeting night, before anyone is in the room. The same screen is covered in more depth in [When something looks wrong](#ch-something-wrong).

1. In the left menu, under **System Health**, click **Readiness**. The page's own title is "Safe to broadcast".
2. Read the banner called "On air right now". It lists each channel with a state word and a small colour tag, and it updates itself about every 5 seconds.
3. Read the card under the title. Its tag is **Ready** (green), **Check before meeting** (yellow) or **Do not broadcast yet** (red). The card's heading can also read "Ready with optional items", which means only optional items still need attention. The card's text says what to do next.
4. To run a full test, click **Check broadcast readiness**. This needs the Meeting operator role.

You should see a card titled "Broadcast readiness check result" with a line "Rehearsal result" that reads **Passed**, **Failed** or **Not run**.

> **Warning:** **Check broadcast readiness** has no confirmation box. It creates a private test live session called "Private first-broadcast rehearsal" on the channel `government`, copies the sample test video that was set up during first setup (if there is none, the result reads **Not run**), and saves a short test recording. If they do not already exist, it also adds a source called "CivicCast sample test source" (see the Known issue under "Choose and check a meeting source") and a test recording location. In the code we read, the test session is marked "On air" for a moment and then ended, and the portal home page reads the live session record, so residents could briefly see the test session as on air. We have not watched this happen. We could not confirm whether the test recording shows up in the Assets list. Do not run this check while a real meeting is on air.

> **Known issue (beta.11):** the Readiness page has no Refresh button. Only the "On air right now" banner updates by itself. The checklist, the feed cards and the other panels change only after you use one of their own buttons or reopen the page.

## Choose and check a meeting source

The **Live** screen walks you through one meeting from "pick a source" to "end and save the recording". The first step is to choose which source CivicCast will test.

1. In the left menu, under **Run Meeting**, click **Live**.
2. Read the top of the page: the heading "Live", then the sentence "Run pre-flight and start only after CivicCast verifies the source, storage, and network from the server." On the right are small tags showing the session state ("No session" until you create one) and, later, "Pre-flight ready" or "Pre-flight blocked".
3. Read the **Safe to broadcast** panel. It says **Ready**, **Check before meeting** or **Do not broadcast yet**, and has a **Resident preview** link that opens the resident portal in a new tab.
4. Open the **Broadcast channel** menu and choose the channel for this meeting. Your browser remembers the choice. Once you create a session, the menu is locked and says "Channel is fixed while a session exists."
5. Under **Source to check**, select the source to test and associate with the next **Start Live Stream** session. Selecting it alone does not switch the current channel broadcast.
6. Click **Check source**. The button reads "Checking source..." for up to about 8 seconds while CivicCast tries to read video from the source.

You should see the source's tag change to **Delivering** and text such as "Checked just now" or "Checked 2 seconds ago". The other tags are **Needs re-check** (video was seen, but longer ago than 30 seconds), **Not answering** (the last check failed; the reason appears in a red box titled "Live action failed.") and **Not checked**.

> **Tip:** a source's **Delivering** answer expires after 30 seconds by default (your IT person can change this to anything from 5 to 300 seconds). Run **Check source** again immediately before you do anything that depends on it, especially **Take live** on the Channels screen.

> **Known issue (beta.11):** The **On-air preview** never shows video. In the code we read, nothing draws a picture there. It always says "Source preview unavailable" and "No simulated preview or audio meter is shown." Watch your own monitor or the channel output for the picture.

> **Known issue (beta.11):** setup, or **Check broadcast readiness** on the Readiness screen, can add a source called "CivicCast sample test source" on the channel `government`. In the code we read, the **Run pre-flight** "Live source" row passes for that source by checking CivicCast's own sample video file, not a camera, so a pre-flight with that source selected proves nothing about your room. For a real meeting, choose your own camera or encoder source. **Check source** still tests that source over the network, and the code's own comments say nothing listens at its address, so it is not expected to pass.

In beta.12, only the unchanged bundled sample source uses its validated local sample video for rehearsal. After changing that source's channel, type, address or credentials, pre-flight checks the configured live source instead. An edited source cannot pass by reusing an unrelated sample file. For a meeting, select a source on the session's channel and make sure its fresh check passes.

If a Setup admin needs to change a source's address, they click **Edit source**, change the fields and click **Save source**. CivicCast warns: "Saving this change clears what CivicCast knows about this source. You will need to choose Check source again before it can take air." That warning appears only after you change the address, the type or the stored credential. Anyone else sees "Editing a source needs the setup admin role. Ask your station admin to change the address or type."

## Run a live session

A live session is CivicCast's record of one meeting being broadcast. These steps are in the order the buttons enable themselves. *Pre-flight* is a set of nine tests CivicCast runs before it lets you mark the session on air.

> **Warning:** the Live screen forgets your session if you leave it. See the last Known issue in this task before you open any other screen in the same browser tab. Keep Live in its own browser tab for the whole meeting.

1. Choose your channel and source and run **Check source** until it says **Delivering** (see the previous task).
2. In the **Session controls** box, click **Create live session**. The tag at the top changes from "No session" to **Idle**. The session is always named "Council live room".
3. Click **Start pre-flight**. The tag changes to **Pre-flight**. This button only moves the session to the next step. It checks nothing.
4. Tick the box "Operator confirms the meeting details and acknowledges the server-side pre-flight result."
5. Click **Run pre-flight**. The **Pre-flight checklist** at the bottom of the page fills with nine rows. You can run it as many times as you like.
6. Read every row. A row that failed has a red border and a "Next step." line telling you what to fix. Fix it, then click **Run pre-flight** again until the tag at the top says **Pre-flight ready**.
7. When you are ready, click **Start Live Stream**.

You should see the session tag change to **On air**. If the checks fail at this moment, a red box titled "Live action failed." says "Go on air blocked: a fresh source-bound server-side pre-flight did not pass. No broadcast was started. Correct the failed checks and run pre-flight again." CivicCast runs the checks again, including a new source check, when you click, so the click can take several seconds.

> **Warning:** **Start Live Stream** has **no confirmation box**. It sets the live session to "On air". The resident portal's home page then tells residents "Council live room is on air." and shows State "On air", whether or not the channel is actually broadcasting. Click it only when the channel's feed really is running (see [Start a channel](#start-a-channel)).

> **Known issue (beta.11):** in the code we read, **Start Live Stream** changes the session record and the public status only. It does not start the channel's feed, and it does not put your source on the channel. The error message above says "No broadcast was started", but a successful click does not start one either. To put a camera on a channel, use **Take live** on the Channels screen. If the channel's own feed is running, residents see it whether or not you press **Start Live Stream**.

The nine rows in the checklist are: **Network reachable**, **Recording storage**, **AI runtime**, **Live source**, **Recording target**, **Operator confirmation**, **Syndication**, **Internet Archive** and **NAS handoff**. Only five can stop you from going on air: Network reachable, Recording storage, Live source, Recording target and Operator confirmation. The other four report status and do not block. (AI runtime is optional here; Syndication, Internet Archive and NAS handoff describe what will happen to the recording after the meeting. A row for one of those three can show a red border, with the message that the broadcast can still go ahead.) What the five really test:

| Row | What it checks |
| --- | --- |
| Network reachable | The station can open a connection to at least one of two public internet addresses, 1.1.1.1 and then 8.8.8.8 (it waits up to 3 seconds for each by default). A station with no internet access cannot pass. |
| Recording storage | At least 50 GiB (about 50 gigabytes) is free on the drive CivicCast keeps its uploaded files on. This is the CivicCast data drive, not necessarily the recording drive. |
| Live source | The source you selected belongs to the session's channel and passes a fresh check. |
| Recording target | A real (not test) local recording location is configured. |
| Operator confirmation | The box in step 4 is ticked. |

> **Known issue (beta.11):** three more things on this screen are easy to misread. First, the **Safe to broadcast** panel near the top is worked out from the last test on the Readiness screen, not from the checklist on this page, so it can say "Check before meeting" while this page says "Pre-flight ready". Second, the hint on a failed Operator confirmation row says to tick the box "below", but the box is in **Session controls**, above the checklist. Third, the empty checklist says "Run pre-flight to populate the nine-check contract." It means "Click **Run pre-flight** to check the camera, the recording drive, the internet and your confirmation."

> **Known issue (beta.11):** **Create live session** appears to work only once. The session id is fixed ("council-live-room"). In the code we read, a second **Create live session**, on a later night, is refused with "LiveSession already exists: council-live-room", and nothing on the screen lists or reopens an old session. We read this in the code and did not repeat it on a running station. Until the product changes, plan on one live session per station and ask your IT person how to clear it. The next Known issue explains what happens if you refresh the page.

> **Warning:** During an active session, keep the Live page open. The error panel now advises you to ask the station administrator to check the CivicCast service and database, and warns that refreshing can lose the in-page session. If you refresh, close the tab, or leave Live in the same tab, the buttons can return to **Create live session** while **End Live Stream** is disabled. The fixed session id may then prevent creating another session, and the page has no way to reopen or end the existing one. Open **Channels** or the **Control Room** in a second browser tab or window.

## End a live session and find the recording

1. When the meeting is over, click **End Live Stream**. It is enabled only while the session is **On air**.
2. A box titled "End the live stream?" appears. Click **End live stream** to confirm, or **Cancel**.

3. Watch the **Recording finalization** panel that appears. It shows **Waiting**, then "Attempt N of M. The recording is being checked and packaged.", then "Recording saved as asset &lt;id&gt;. Find it in the Assets library."

If it fails, the panel shows the reason (or "Finalization failed."). Fix the cause, then click **Retry finalization**. See [After the meeting](#ch-after-meeting) for what to do with the saved recording.

> **Warning:** the box says "Residents watching the live stream lose it immediately." In the code we read, that is not true. **End Live Stream** only marks the session as ended and starts the saving of the recording. It does not stop the channel's feed, so the channel keeps broadcasting. To take the channel off the air, use **Stop** or **Finish current item, then stop** on the Channels screen.

> **Known issue (beta.11):** the saving step looks for a recording file named after the session in the recording location (for example `council-live-room.mp4`). Nothing on this screen creates that file, and in testing we could not confirm which part of CivicCast does. If the panel stays on **Waiting** or fails, ask your IT person to check that the recording location is receiving the meeting recording. By default CivicCast gives up waiting for the file 30 minutes after **End Live Stream**, and the panel then reads "No recording file was found for this session (expected ...)". While CivicCast is still retrying by itself the tag reads "Retrying". **Retry finalization** appears only after CivicCast has given up. It is shown to every role, but only a Meeting operator can use it.

## Start a channel

The **Channels** screen controls each channel's actual video feed.

1. In the left menu, under **Run Meeting**, click **Channels**. The heading is "Channels" and a tag says "refreshes every 30s".
2. In the row of channel cards under the heading, click the card for the channel you want. Each card shows the channel's name and its id (for example `government`). The first channel is selected for you.
3. Find the box **Outgoing channel feed**. It shows a state tag. The words you can see there are **On air**, **Showing slate**, **Starting**, **Stopping**, **Finishing current item**, **Changing source**, **Stopped** and **Needs attention**.
4. Click **Start**.
5. A box titled "Start the outgoing feed for &lt;channel&gt;?" says "&lt;channel&gt; goes live to its configured outputs and becomes visible to residents." Click **Start feed**.
6. The button reads "Queuing..." for a moment. The screen then checks the feed every 2 seconds for 20 seconds.

You should see the state tag change to **Starting** and then **On air**, or **Showing slate** if nothing is scheduled right now. "Starting" means CivicCast is preparing the first program, which can take a while on a cold start.

> **Warning:** **Start** makes the channel visible to residents and to every output set up for it (the web player, and any cable or streaming output). Start a channel only when you mean it to be public.

Clicking **Start** only *queues* a command. The feed program picks it up afterwards. If it does not, after 20 seconds a red box says "Start was queued but the feed did not start." and tells you to check that the CivicCast egress service (the background program that sends the channel out) is running on this station (System Health), then try **Start** again.

If **Start** is grey, a line under the button says why:

* "No outgoing-feed configuration for &lt;id&gt;. Apply a headend preset or the local rehearsal preset first." The channel has never been set up. Ask a Setup admin.
* "Outgoing feed for &lt;id&gt; is disabled in its egress configuration. Enable it in Outgoing feed configuration, then start."
* "Checking for an outgoing-feed configuration..." Wait a moment.
* "Could not check the outgoing-feed configuration for &lt;id&gt;. Retry the check, then start." Click **Retry check**.

If you see "Outgoing feed controls require the meeting operator role.", your sign-in cannot use these buttons.

## Stop, restart or finish a channel

Use the same **Outgoing channel feed** box.

| Button | Box that appears | Confirm button |
| --- | --- | --- |
| **Stop** | "Stop the outgoing feed for &lt;channel&gt;?" - "This takes &lt;channel&gt; off the air. Residents watching lose the stream until the feed is started again." | **Stop feed** |
| **Restart feed** | "Restart the outgoing feed for &lt;channel&gt;?" - "The stream drops briefly for residents while &lt;channel&gt; restarts." | **Restart feed** |
| **Finish current item, then stop** | "Finish the current item, then stop &lt;channel&gt;?" - "&lt;channel&gt; plays out its current item and then goes off the air until the feed is started again." | **Finish, then stop** |

> **Warning:** all three commands change what residents see right now. **Stop** drops the stream at once. Use **Finish current item, then stop** at the end of a meeting if you want the program to end cleanly.

> **Warning:** **Stop** may not keep the channel stopped. If **Keep this channel on air** is switched on for that channel (see the next task), CivicCast starts the channel again by itself after you stop it. The Stop box does not mention this.

> **Known issue (beta.11):** the screen refreshes every 30 seconds, and only **Start** is watched more closely. The screen does re-read the feed state once right after you confirm **Stop**, **Restart feed** or **Finish current item, then stop**, but the feed program may not have acted yet, so the state tag can take up to about 30 seconds to change. Do not click the button again straight away. Wait for the tag to change.

## Keep a channel on air all day (the 24/7 setting)

The box **Run this channel 24/7** holds the setting **Keep this channel on air**. Only a Setup admin can change it. Everyone else sees "Automation settings require the setup admin role."

The checkbox's own hint reads "Starts the feed automatically after restarts and crashes." The same box has **Allow software (CPU) encoding fallback**, a choice of **Station slate** or **Community bulletins** under "Between programs, show", a **Slate message**, and two optional output names for network video (**NDI output name (optional)**) and a video card (**SDI output device (optional)**). To save any change, click **Save automation settings**. It is enabled only after you change something, and "Unsaved changes" appears beside it.

What "Keep this channel on air" really does, from the code we read:

* By default, about every 2 seconds, CivicCast's automation looks at every enabled channel with this setting on.
* If the channel's feed is not running, CivicCast queues a **Start** for it. If the channel still is not running, it queues another about every 30 seconds.
* The code does not remember that a person pressed **Stop**. Its own comments describe "a stop the operator issued" as a reason to send a new start.

> **Warning:** **Save automation settings** has **no confirmation box**. Saving with **Keep this channel on air** ticked, on a channel whose configuration is enabled, can put the channel on the air without anyone pressing **Start**.

> **Known issue (beta.11):** with **Keep this channel on air** on, pressing **Stop** or **Finish current item, then stop** may only pause the channel for a short time. We read this in the code and have not watched it on a running station, so treat the exact timing as approximate. To keep a channel off the air, have a Setup admin untick **Keep this channel on air** and click **Save automation settings** first, then use **Stop**.

> **Known issue (beta.11):** if a channel has no outgoing-feed configuration, this box says "This channel has no outgoing-feed configuration yet. Create one from the channel egress runbook (or the setup flow) first; then automation settings appear here." A non-technical person cannot do that. The real fix is for a Setup admin to apply a headend preset (see the Cable headend box on the same screen, or ask IT).

## Live captions during the meeting

Live captions are a station setting, not a control on the Live screen. On a new station, **Show live captions on air** is off. A Setup admin can enable it in **Station Profile**; see [Live captions: what the settings change](#live-captions-what-the-settings-change).

Beta.11 uses Whistle on the CPU for live recognition and sends first-pass captions without waiting for a second recognition to agree. It serializes caption inference across channels on one station runtime to give playout priority. If Whistle fails or exceeds its 10-second request deadline, that channel uses Whisper until the live runtime restarts. Whisper is also used for recording transcription. NVIDIA CUDA is optional acceleration for Whisper, not a requirement for Whistle. Captions are best-effort and may have gaps under load.

Beta.12 starts Whistle without loading the Whisper backup first. A backup that cannot load therefore does not prevent Whistle from starting. Whisper loads when a channel actually needs fallback; that first switch can take longer, and insufficient memory or a backup startup failure can still interrupt that channel's captions.

When the switch is enabled, recognition resumes on the next worker scan, but the channel's caption route is added when the channel next starts. Stop and start each affected channel after enabling it. When switched off, recognition stops and queued audio drains on the next worker scan; the graph route is removed at the next channel start. The switch does not affect captions created later for recordings. For overload and fallback recovery steps, see [Captions late or missing](#captions-late-or-missing).

## Take a channel live from a camera (live takeover)

A *takeover* puts a live source on a channel right now, ahead of whatever is scheduled. You then hand the channel back to its schedule when you are done.

1. On the **Live** screen, click your source's card and click **Check source** until it says **Delivering**.
2. Go to **Channels** (if a live session is open on **Live**, do this in a second browser tab) and click the channel. Find the box **Live takeover**. It says "This channel is on its scheduled program."
3. Click **Take live**. If it is grey, the line beside it says "No live source is ready yet." Go back to step 1. By default the button goes grey again 30 seconds after your last good **Check source**. The Channels screen asks for this state every 15 seconds, so after a fresh **Check source** the button can take up to about 15 seconds to turn on.
4. A small form appears with the question "Why are you going live? (optional)". Type a reason if you like.
5. Click **Confirm take live**, or **Cancel**. The button reads "Going live…" while CivicCast works.

You should see a red badge reading "Live takeover" with the name of the person and how many minutes it has been live.

> **Warning:** **Confirm take live** overrides the schedule and changes what is on the air. There is no pop-up. The second click is the confirmation. If the source's last good check is older than the window (30 seconds by default) when you confirm, the code we read refuses the takeover before it re-checks anything. The error can then read something like "Live ingest path '&lt;channel&gt;:local' is disabled.", which names CivicCast's built-in placeholder path and not your camera. Click **Check source** again and retry. If the channel is already under takeover, the error says "Channel '&lt;id&gt;' is already under live takeover."

To hand the channel back:

1. In the same box, click **Return to schedule**.
2. Optionally type a note (the example text is "e.g. meeting adjourned").
3. Click **Confirm return to schedule**, or **Stay live** to cancel.

> **Warning:** **Confirm return to schedule** changes what is on the air. The takeover history marks the takeover "Returned" as soon as the command is queued, not when the feed has actually switched back.

> **Known issue (beta.11):** the screen never says which source it will use, and the source card you picked on **Live** is not sent with the request. In the code we read, **Take live** uses the first **Delivering** source in CivicCast's list for that channel, which may not be the one you selected. The red "Live takeover" badge shows only who took over and how long ago, not the source, and it appears as soon as CivicCast records your request, which can be before the picture has switched. The **Source:** line in the **Outgoing channel feed** box should name the live source once the switch happens (it can take up to 30 seconds to update; we did not watch this on a running station), and a Setup admin can read the source in "Takeover history". Always watch the channel's actual output. A takeover is planned for up to 3,600 seconds (one hour). In testing we could not confirm what happens when that hour ends, so return to the schedule yourself well before then.

A Setup admin also sees "Takeover history", which lists past takeovers with "Live" or "Returned", who did it, when, and the reason. If none exist it says "No live takeovers have been recorded for this channel."

## Put a scheduled program on the air (commit to air)

Programs that you want to play on a channel have to be *committed*. The box **Commit programs to air** on **Channels** does this. It lists the next 24 hours of programs for the selected channel. The same safety check is offered on the **Schedule** screen under the name **Publish to residents** (see [Before the meeting](#ch-before-meeting)); it does the same thing.

1. On **Channels**, find **Commit programs to air**. It says "Review the safety check, then approve a program to put it on this channel."
2. Under "Next 24 hours", find the program. Its tag is **Ready to review**, **Committed**, **Skipped (conflict)**, **Skipped (media)** or **Cancelled**. Only programs that are linked to a schedule item are listed.
3. Click **Review & prepare**. This is a dry run. It changes nothing.
4. Read the result. A green **Safe to air** tag means CivicCast found the media and no clash. A red **Not safe to air yet** tag comes with the reason: a message about missing media, or "Clashes with N other program(s) already scheduled:" followed by what overlaps. A gap before the program is listed as "Dead-air gap before this program (it can still air):".
5. If it says **Safe to air**, click **Approve & put on air**. To back out of the review, click **Cancel**.

You should see the program move to the "Recent commits" list with a tag: **Preparing**, **Queued to air**, **Couldn't reach the engine** or **Rolled back**.

> **Warning:** **Approve & put on air** has **no confirmation box**. It is a single click once the review says **Safe to air**. It publishes the schedule item to residents, saves an approval record in your name, and then queues a **Start** for the channel if the feed is stopped, or a reload if it is running, so the schedule is read again. The program plays at its scheduled time, not at the moment you click. On a stopped channel the click also starts the whole channel's feed.

To undo an approval:

1. In "Recent commits", click **Take off air** on that program.
2. Type a reason in the box "Why are you taking this off air?". The button stays grey until you do.
3. Click **Confirm take-off**, or **Keep on air** to cancel.

> **Warning:** **Confirm take-off** cancels the program's schedule item. It will not play, not merely pause. The engine is told to read the schedule again, and the approval is marked **Rolled back** with your reason.

> **Known issue (beta.11):** four things in this box are loose with words. The tag **Queued to air** means the command was queued, nothing more. The tag "On air (confirmed)" is never shown, because no code sets that state. A row for a future program says "aired &lt;time&gt;" even though it has not played. And if the list of past approvals cannot be loaded (for example, for a role that is not allowed to see it), the box still says "Nothing has been committed to air on this channel yet." instead of showing an error.

Without the Publish operator or Setup admin role, **Review & prepare** is grey and the box says "You can review the schedule here. Putting a program on air or taking it off requires the publish operator or setup admin role."
## Put a lower-third banner on a channel

A *lower third* is the strip of text across the lower part of the picture, such as "Town Council -- Live". The box **Lower-third banner** on **Channels** holds one line of text for the selected channel.

1. In **Lower-third text**, type your line (up to 240 characters).
2. Click **Put on air**. The box asks "Put this banner on air?"
3. Click **Confirm: put on air**, or **Cancel**.
4. To remove it, click **Take off air**, then **Confirm: take off air**.

> **Warning:** this changes what is on the air, but not at once. The confirmation line explains that the change applies "to this channel's next pipeline build (a fresh start or a scheduled content swap)" and "Does not hot-change an already-live broadcast's on-screen text." ("Pipeline" here means the chain of software steps that builds the channel's picture.)

> **Known issue (beta.11):** the tag beside the heading says **On air** as soon as you save, even though the picture has not changed. Treat it as "Saved: on". The banner reaches the picture only when the channel next restarts or swaps content. For this chapter we have not watched a banner appear on a live channel. The box works only for a channel that has an outgoing-feed configuration. Otherwise it says there is none yet. The screen's note says a Setup admin may also change the banner, but the button is enabled only for a Meeting operator.

## Change the cable headend (for Setup admins)

The box **Cable headend delivery** sets where a channel's cable-TV signal is sent. This is normally done once during setup, not on meeting night. If you are a Setup admin:

1. Choose a **Headend preset**, fill in the destination fields the preset needs, and click **Apply headend preset**. (For some presets the button reads **Enable web preview** instead.)
2. A box titled "Apply this headend preset?" spells out what will change. Click **Apply preset**, or **Cancel**.

> **Warning:** applying a preset changes what the channel outputs. If the channel is standing by on its slate, it restarts at once and every output drops for a few seconds. If a program is on air, nothing is interrupted and the change waits for the next stop and start. The box warns when other outputs, including the cable feed, will be removed. Do not apply a preset during a meeting unless IT has told you to.

> **For IT staff:** presets, destinations and the **Verify stream (TSDuck)** check are covered in [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations).

## Open a Control Room session

The **Control Room** drives your production equipment (OBS, vMix, Blackmagic ATEM switchers, HyperDeck recorders, PTZ cameras, CasparCG, routers and similar) during the meeting. It works through a small helper program that CivicCast calls the "TSR control service". In this chapter we call it the *production-control helper*.

You work on a *control surface*, which is a named bank of buttons. Each button is a *cue*, one action such as "Take scene" or "Router take". You open a *session* on the surface, test a cue with a *dry run* (a preview of what it would send), and then confirm it. A session is either **Test Mode**, in which nothing reaches your equipment, or **On-Air Mode**, in which cues are really sent.

> **Note:** the Control Room produces a source. It does not put anything on a channel. The page says so: "This console produces the source. Taking it to air on a channel is a Playout (S5) action — it is not fired from here." (Playout is the part of CivicCast that runs a channel; "S5" is an internal code name.) Use **Take live** on **Channels** for that.

> **Known issue (beta.11):** CivicCast's own readiness text (under **Technical detail** in the "Control-room readiness" card) says the Control Room's readiness is worked out from CivicCast's settings and test profiles, and that it is "not clean Windows install evidence, simulator evidence, real OBS/vMix/ATEM/NDI evidence, or station-device evidence." In plain words, the Control Room has not been proven against real production equipment in this beta. Rehearse in **Test Mode**, and keep your hardware's own controls within reach.

### Read the readiness panel

1. In the left menu, under **Run Meeting**, click **Control Room**. The heading is "Production Control Room".
2. Look in the readiness panel for a card called "TSR control service". If it is blocked, the helper is not running or cannot be reached. Tell your IT person. A separate amber bar that says "Production control unavailable — the TSR control service is not running or not configured. Cues cannot fire until it is restored." appears only after a device probe, a cue dry run or a cue fire fails for the same reason. It does not appear when the page first opens.
3. Read the card "Control-room readiness". It has a headline tag and a second tag, either "Equipment verified" or "Equipment check pending". Under it are five counters: **Devices**, **Surfaces**, **Cues**, **Open sessions** and **On-Air**.
4. If any check is blocked or has a warning, it appears as its own card with a recovery sentence. A blocked check has a button **Open Control Room Setup**. Only a Setup admin can use that screen.

> **Known issue (beta.11):** the headline can never read **Ready**. The "equipment verified" value is permanently false in this version, so the best the headline can say is **Check before meeting**, and the amber note "You can register switchers and run dry runs now. On-air readiness is confirmed once a check against the room's actual devices passes." never goes away. No screen offers that check. Read **Check before meeting** here as "CivicCast has not verified your equipment", not "something is broken". A red **Do not broadcast yet** does mean a real blocked check.

### Check your equipment

Under **Devices** each piece of gear is a small chip with its name, kind and tags such as **Reachable**, **Unreachable**, **Disabled** or **Not probed**, plus a health tag: **Healthy**, **Never probed**, "Stale — probe again" (older than 5 minutes) or **Unreachable**. A Setup admin or Support admin can click **Probe** on a chip to test it (the button reads "Probing…"). If there are no devices, the screen says "No devices to operate yet." and tells you to register one in Control Room Setup.

### Open a Test Mode session

1. Open the **Control surface** menu and pick a surface ("Select a surface…" is the empty choice).
2. Leave **Test Mode** selected, and click **Open Test Session**. The page shows a blue banner: "TEST MODE - device actions are blocked and recorded as test-only audit events."
3. Click a cue's button. This is a dry run only. A plan card appears with the cue name, the command text, the tag "Ready to send" or "Not ready", and a line such as "take-delay Nms · post-roll Nms".
4. If the cue is marked as needing confirmation, click **Test... (needs confirm)**, then **Confirm test action**. Otherwise click **Record test action**.
5. Watch the **Fired-cue audit** list. The row shows **Planned**. Nothing was sent to any device.
6. When you are done, click **End session**.

You should see the banner "Test action recorded." Test Mode never touches your equipment.

### Open an On-Air Mode session

1. Wait until the readiness panel has no blocked checks.
2. Open the **Control surface** menu and pick a surface.
3. Select **On-Air Mode**.
4. Pick a **Safe-state cue**. This is the recovery cue, the one that puts the room back in a known safe state if something goes wrong. The menu lists only cues that are marked as needing confirmation.
5. Tick the box "I understand On-Air cue actions may be sent to production devices".
6. A list called "On-Air prerequisites" shows "Ready:" or "Needs attention:" for **Control-room readiness**, **Safe-state cue selected** and **On-Air responsibility acknowledged**. When all three are ready, click **Open On-Air Session**.

You should see an amber banner: "ON-AIR MODE - cue actions can be sent to production devices. Safe-state cue: &lt;cue id&gt;." The banner shows the cue's internal id, not its name. The **Safe State** panel under it shows the name. While the session is open, the screen shows the time remaining and the exact deadline.

> **Warning:** in an On-Air session a cue really is sent to your equipment, and that can change the picture going to the channel. Always click the cue first (the dry run) and read the plan card.

If someone else already has the surface open, you see: "A session is already open on this surface, locked by &lt;name&gt; since &lt;time&gt;. A setup admin or support admin can force-close it to release the lock."

An On-Air session expires **30 minutes** after it opens. The countdown warns you as the deadline approaches. At expiry, ordinary cue controls pause. The session owner can still use **Panic: Run Safe State** while the session remains open; end the session to release the surface, then open a new one to continue. If a normal cue request reaches the server after expiry, CivicCast refuses that cue and leaves the session open, so the owner can still run Panic or end the session. Cues already sent are not undone. After a page refresh, CivicCast restores the selected surface and its open session, but not an earlier dry-run result; dry-run a cue again before firing it.

### Fire a cue

1. Click the cue's button. The plan card appears (the dry run).
2. Read the command text and check the tag says **Ready to send**.
3. Click **Fire... (needs confirm)**, then **Confirm fire**. A cue that is not marked as needing confirmation shows **Fire cue** instead, and one click sends it.
4. Read the banner: "Cue fired." The audit list adds a row tagged **Fired**, or **Failed** if the helper could not send it.

> **Warning:** **Confirm fire** and **Fire cue** change what your production gear is doing. There is no pop-up. The two-step button is the confirmation. If the cue or the device changed since your dry run, CivicCast refuses with "The cue preview is stale ... Dry Run the cue again before Live Fire."

### If a cue fails: Safe State and rollback

The **Safe State** panel appears once a session is open. In an On-Air session it names the recovery cue and has two buttons. In a Test Mode session it reads "No safe-state cue is configured for this session." and has no buttons, because Test Mode does not ask you to pick one.

* **Dry Run Safe State** previews the recovery cue.
* **Panic: Run Safe State** sends the configured safe-state cue immediately through the recovery action. It does not wait for a dry run and remains available to the session owner after the On-Air deadline, while that session remains open.

If a cue fails in an On-Air session, use **Panic: Run Safe State** in the Safe State panel. A good result reads "Rolled back to Safe State."

> **Warning:** **Panic: Run Safe State** has no confirmation box. It sends the recovery cue to your equipment at once.

### End a session

1. Click **End session**.
2. A box titled "End the control room session?" appears. For an On-Air session it says "This releases your operator lock on this control surface. Any cue already sent is not undone. Panic can still run the safe-state cue until you end the session." For Test Mode it says "This releases your operator lock on this control surface. No operator can fire cues on it until a new session is opened." Click **End session**, or **Cancel**.

The selected surface is remembered in this browser tab. Refreshing the page restores the open session for its owner without opening a duplicate; dry-run results are temporary, so repeat a dry run before firing. Another operator sees the active session as read-only. A Setup admin or Support admin can release that lock after confirming; releasing a lock does not undo cues already sent. An operator can end their own session after confirming. Ending a session releases its surface lock.

A Support admin can also type a note in **Operator note** and click **Create support bundle**. This builds a troubleshooting file with private details removed, and shows its location. Everyone else sees "Support bundles require support admin."

## Preview a router take (Facility)

The **Facility** screen is titled "Facility router". A *router* here means the video switching box that decides which camera or feed goes to which input, and a *take* is one switch.

> **Known issue (beta.11):** in this version the Facility screen is a **preview only, using sample data**. It cannot change a real router. The page says so with a tag, "hardware send disabled". The router, the sources and the destination it lists are a fixed built-in example, the same on every station: a "Control room router" at the address 192.0.2.10 (an address reserved for examples, which no real router uses), the sources "Council chamber" and "Bulletin board", and the destination "CivicCast capture". Do not treat them as your equipment. In the code we read, there is no screen or command that loads your own router.

What it does show is the exact command that *would* be sent. To look:

1. In the left menu, under **Run Meeting**, click **Facility**.
2. Click an endpoint card under **Router endpoints** (a tag shows "ready" or "off").
3. Click a route button such as "Council chamber to CivicCast capture", or use **Manual crosspoint** (choose a **Source** and a **Destination**, then click **Preview take**).
4. Read the **Take preview** card: the target, the protocol, the command, and a "Proof boundary" line that says what the preview does not do.

You should see the command text, and the tag "ready" or "blocked". No hardware is contacted, and nothing changes on any channel.

Two more previews need a channel chosen in **Target channel**: **Preview scheduled take** (a take timed 15 minutes from now with a 15-second lead, using a made-up item) and **Preview L-bar and squeezeback** (a plan for shrinking the picture to make room for a graphics frame). Neither runs anything.

> **Note:** nothing on this screen can change anything on the air. It sends nothing and has no confirmation boxes. The only real way to do a router take in this version is a Control Room cue of the kind "Router take" on a "TCP device".

> **Known issue (beta.11):** the "Take preview" card says "Operator action. Confirm the previewed route, then send the command from the router panel." There is no send control anywhere. Ignore that sentence. Also, the screen allows some roles that the server then refuses. A sign-in with only the Setup admin role can click the route buttons, **Preview take**, **Preview scheduled take** and **Preview L-bar and squeezeback** and get a refusal ("This action requires one of these CivicCast roles: meeting_operator, support_admin."). A Support admin has the opposite problem: the server allows these previews, but the screen greys out the scheduled-take and L-bar buttons for that role.

## Show community bulletins between programs (CG Board)

*CG* is short for "character generator", the part of a broadcast system that puts text and graphics on screen. In CivicCast the **CG Board** is the "community board" a channel can show between programs: a card with station and community announcements. It is **not** the lower-third banner (that is on **Channels**, see above).

The board is shown in the gaps between programs when the channel's filler is set to **Community bulletins** (on **Channels**, in "Run this channel 24/7", under "Between programs, show"). Otherwise it shows the **Station slate**. If no bulletins are approved, the channel falls back to the slate.

1. In the left menu, under **Run Meeting**, click **CG Board**.
2. Use the **Channel** menu to choose a channel ("Public board" is the first choice).
3. The **Template library** shows three layouts, and **Read-only board preview** shows a preview of the board's zones. Clicking a template only changes this preview.
4. In **Community bulletins**, click **Add bulletin**.
5. Fill in **Organization**, **Submitted by**, **Title** and **Message**. All four are required. The limits are 160 characters for the first two, 200 for the title and 500 for the message.
6. Click **Add bulletin** again (the second button, in the form). The form closes. The bulletin appears with the tag **Submitted**.
7. To let it air, click **Approve**. The tag changes to **Approved**.

To send a bulletin back, click **Request changes**, type a note and click **Send request**. The tag becomes **Needs changes**, with your note in amber ("Notes: …"). To remove a bulletin, click **Decline**, type a reason and click **Decline bulletin**.

> **Warning:** **Approve** has no confirmation box. Once approved, a bulletin is eligible to air as a slide between programs on the channel you chose in the **Channel** menu, if that channel's filler is **Community bulletins**. We did not watch a bulletin air for this chapter. **Decline** is how you pull one that is airing. A declined bulletin cannot be approved again from this screen. Add a new one instead.

> **Note:** This screen is for reviewing and approving between-program bulletins. The board preview is read-only here; use **CG Designer** to change templates, zones or feeds. Only a Setup admin or Publish operator can manage bulletins. You cannot set start and end dates for a bulletin here. If the station's database has not been prepared, adding fails with "Durable storage is not ready. Open Setup and choose Prepare storage before managing community bulletins."

## Design the community board (CG Designer)

**CG Designer** (the page title is "CG Board Designer") sets up the board itself for one channel: a template, its zones, outside feeds, a live preview and a change history. A *zone* is one box on the board, such as a ticker, a schedule, a logo, or a sponsor message. This is normally done before the meeting, not during it.

1. In the left menu, under **Run Meeting**, click **CG Designer**. You can see this item only with the Publish operator, Setup admin or Support admin role.
2. Choose a **Channel**.
3. If the channel has no board, choose a **Template** and click **Create board**.
4. To add a zone, click **Add zone**, fill in **Region**, **Zone kind** and **Content source**, then click **Add zone** again. To delete a zone, click **Delete**, then **Confirm delete?**.
5. To bring in an outside source such as a news feed or a calendar, click **Add feed**, fill in **Feed kind**, **Trust tier**, **Feed label**, **Source URL** and **Refresh (minutes)**, and click **Register feed**.
6. To vet individual feed items, click **Review items** on a feed and click **Approve** on each item you want to allow.
7. Check the **Live preview** and read **Board history** to see who changed what.

> **Warning:** the board is what viewers see between programs. Changing the **Board template** menu takes effect **immediately, with no confirmation**. Deleting a zone asks only "Confirm delete?".

> **Known issue (beta.11):** if you only have the Support admin role, you can open this screen but every Add, Edit and Delete button is missing, and nothing says why. Changing the template does not tell you what happens to existing zones, and we could not confirm that. You cannot switch a board off from here. The zone form lists some options as "coming in a future release" (live video in a zone and board background audio). Do not plan around them. Labels such as **Region**, **Zone kind**, **Trust tier** and **feed adapter** are not explained on screen. Ask whoever set up your board.

## Bring in remote guests (Remote Contribution)

**Remote Contribution** lets remote council members, presenters and public commenters join from a web browser, with nothing for them to install. CivicCast manages the *rooms*, the invite links and the guest list. The video mixing is done by separate software on your station (VDO.Ninja, a web video tool, and a *compositor*, a program that combines video sources into one picture). Those must be set up first.

> **For IT staff:** guest video needs a self-hosted VDO.Ninja service, a compositor, and a TURN relay (a server that helps guests behind firewalls connect). See [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations).

You see this item in the menu only with the Meeting operator, Setup admin or Support admin role.

### Set up a room and send invites

1. In the left menu, under **Run Meeting**, click **Remote Contribution**. A Setup admin first creates a room: type a **Room name** (the example is "Council Chamber Guests"), choose an enabled channel from **Configured channel**, then click **Create room**.
2. Click the room in the **Rooms** list.
3. Click **Open room**. The room's VDO.Ninja director opens in an embedded panel; use it to inspect guests and keep it open while sending guest controls. You can copy its link for use in a separate switcher. If you reload the page, click **Open room** again.
4. Under "Invite a guest", type the **Guest name**, choose a **Contribution role** (**Council member**, **Presenter** or **Public comment**), and click **Generate invite link**.
5. Copy the box labelled "Guest link for &lt;name&gt; — send this", and send it to that guest. Like the director link, this box is shown only right after you generate the link. If you reload the page or select another room it is gone, and the invite list shows only the guest's name, role and **Used** or **Pending**. Generate a new link if you did not copy it.

> **Note:** each guest link works for one guest, once, and expires after 4 hours. The screen says "single-use" but does not mention the 4 hours. Guests who join as **Public comment** must first accept terms before they can join. "Sent invites" lists each link as **Used** or **Pending**. A room holds up to 6 guests by default.

> **Current limitation:** the channel menu shows only configured, enabled egress channels. If none are available, ask a Setup admin to configure and enable a channel first; unknown or disabled channel ids cannot be used to create a room or take a channel live. Room-list and detail reads currently require Meeting operator or Support admin access. A Setup admin working alone cannot manage a room they created. Guest media composition into the channel is not connected in CivicCast; commissioning VDO.Ninja alone does not put a guest on air.

### Admit and control a guest

1. When a guest opens their link, they appear under **Guests** with the tag **In waiting room**.
2. Click **Admit** to mark them admitted in CivicCast. This does not put their media into the broadcast.
3. Keep the embedded VDO.Ninja director open. **Mute audio in director** and **Restore director audio** send VDO.Ninja audio controls; **Mute guest camera** and **Restore guest camera** send camera controls to that guest.
4. **Disconnect guest** asks for confirmation, then sends VDO.Ninja's targeted hangup command.

> **Important:** VDO.Ninja's director iframe does not confirm whether a mute, camera or hangup command succeeded. CivicCast records the latest browser-reported command as **sent, not verified** and keeps the guest's connection status unchanged. Check the director before treating a guest as disconnected. The audio control is for the director's audio path; it is not proof that the channel output is muted. Guest media composition into the channel is not implemented.

### Take the channel live

**Take channel live** is a separate, confirmed action. It switches the channel to its configured live source and can override the schedule. It does not route a contribution guest into the channel. To resume the schedule, use **Return to schedule** on **Channels**.

After checking in the director that a guest has left, click **Mark left after checking** and confirm. This changes only the CivicCast session record; it does not send a provider command.

### Close the room

1. Select the room and click **Close room**.
2. Confirm to send hangup requests for active guest sessions and close the CivicCast room record. The provider does not acknowledge those requests; active guests remain visible so you can inspect or retry controls. Mark each guest left only after verifying the director shows they have disconnected. Closing the room stops new invites; it does not return the channel to its schedule.

You can reopen the room and send new invites afterwards.

### Test guest connections (Support admins)

A Support admin sees a box **Diagnostics** with tags for "TURN reachable", "VDO up" and "coturn up" (or the opposite). Click **Test TURN connectivity** to probe the relay now.

## The meeting-night checklist

Print this page or copy it. The screens named here are covered earlier in the chapter.

**An hour before**

1. Open **Readiness**. The card should say **Ready** (green). If it says **Do not broadcast yet**, read its next step and tell your Setup admin.
2. On **Channels**, check the channel's state tag and "Now / next". Make sure the program you expect is scheduled (see [Before the meeting](#ch-before-meeting)).
3. If you plan to use a camera: on **Live**, pick the source and click **Check source** until it says **Delivering**.
4. If you use the Control Room: open a **Test Mode** session, dry-run and record one cue, and end it. Check that no amber "Production control unavailable" bar appears.
5. If you use remote guests: open the room, send the invite links, and ask guests to join early so they are in the waiting room.
6. On **Channels**, check whether **Keep this channel on air** is ticked, and whether you expect it to be.
7. On **Live**, click **Create live session** now. If it is refused with "LiveSession already exists: council-live-room", tell IT now, not when the meeting starts. If it works, leave that browser tab open and do not refresh it; you will not need to create the session again in step 9.

**At the start**

8. If you want a lower-third banner, set it first (see step 11). Then, if the channel is stopped, click **Start**, confirm **Start feed**, and watch for **On air** or **Showing slate**.
9. On the open **Live** tab (create the live session now if you did not in step 7), click **Start pre-flight**, tick the confirmation box, click **Run pre-flight**, and click **Start Live Stream** only when the channel really is broadcasting. Do not refresh the page after this.
10. To go to the camera, run **Check source** (it expires after 30 seconds by default), then **Take live**, **Confirm take live**. The red badge shows only who took over, not the source, so read the **Source:** line in the **Outgoing channel feed** box (it can take up to 30 seconds to update) and watch the channel's own output.
11. A lower-third banner is meant to take effect at the channel's next start (we have not watched one appear). On a channel that is already running it appears only when the channel next restarts or swaps content.

**During the meeting**

12. Keep **Live** and the Control Room page open in their own tabs. Do not refresh them.
13. If you use an On-Air Control Room session, open a new one before 30 minutes have passed.
14. Admit remote guests one at a time. Keep the VDO.Ninja director open and verify each guest there. Guest controls do not compose them into the broadcast; use **Take channel live** separately only for the channel's configured live source.
15. Watch the channel's own output, not the screen's tags. After **Stop**, **Restart feed** or **Return to schedule**, the tag can take up to 30 seconds to change.

**At the end**

16. Return the channel: **Return to schedule**, **Confirm return to schedule**.
17. Send disconnect requests for remaining guests, verify they left in the director, mark them left, then click **Close room**.
18. End any Control Room session: click **End session**.
19. If you want the channel off the air, click **Finish current item, then stop** (or **Stop**) and confirm. If **Keep this channel on air** is ticked, ask your Setup admin to untick it first.
20. On **Live**, click **End Live Stream**, confirm, and watch **Recording finalization** until it says "Recording saved as asset &lt;id&gt;." Then follow [After the meeting](#ch-after-meeting).

## If it did not work

| What you see | What it means and what to do |
| --- | --- |
| "Live-room controls require the meeting operator role. Source status and readiness checks remain visible." | Your sign-in lacks the Meeting operator role. Ask your Setup admin. |
| "Source preview unavailable - CivicCast has not verified incoming video or audio from &lt;source&gt;." | The Live screen never shows video in beta.11. It is not a fault. |
| A red box titled "Live action failed." | Ask the station administrator to check the CivicCast service and database. Keep this screen open during an active session; refreshing can lose the in-page session. |
| "Go on air blocked: a fresh source-bound server-side pre-flight did not pass." | A required checklist row failed when you clicked. Fix it, run **Run pre-flight**, try again. |
| "LiveSession already exists: council-live-room" | A live session has already been created on this station. See the Known issue in "Run a live session". Ask IT. |
| "Start was queued but the feed did not start." | The feed program did not respond in 20 seconds. Check Readiness, then click **Start** again. |
| "No live source is ready yet." (Take live is grey) | No source passed **Check source** in the last 30 seconds (by default). Run **Check source** on Live. |
| "Channel '&lt;id&gt;' is already under live takeover." | The channel is already live. Use **Return to schedule** first if you want to change it. |
| "Outgoing feed controls require the meeting operator role." | Your sign-in cannot start or stop channels. |
| A program says **Not safe to air yet** | Read the reason: missing media, or a clash with another program. Fix it on **Schedule** and review again. |
| **Couldn't reach the engine** on a committed program | The approval was saved, but the command to the feed did not go through. Check that the feed is running, and ask IT. |
| "Production control unavailable — the TSR control service is not running or not configured." | The Control Room helper is down. Tell IT. |
| "On-Air Mode expired before this cue could fire. Open a new On-Air session to continue." | The 30-minute limit passed. Open a new On-Air session. |
| "The cue preview is stale ... Dry Run the cue again before Live Fire." | The cue or device changed after your dry run. Click the cue again. |
| "A session is already open on this surface, locked by &lt;name&gt; since &lt;time&gt;." | Someone, maybe you before a refresh, has the surface open. Ask IT. |
| "Remote contribution isn't configured yet." | Guest video software has not been set up. Tell IT. |
| A guest-control notice says **sent, not verified** | The director iframe does not report command completion. Check the guest in the embedded director; use **Mark left after checking** only after verifying they have disconnected. |
| "Durable storage is not ready. Open Setup and choose Prepare storage ..." | The station's database is not ready. Tell IT. |
| "This action requires one of these CivicCast roles: ..." | Your sign-in lacks a role for that button. The names listed are the role names in short form. |

## Related

* [Signing in and finding your way around](#ch-signing-in)
* [Before the meeting: schedules, agendas, recording schedules](#ch-before-meeting)
* [After the meeting: assets, captions, summaries, approvals](#ch-after-meeting)
* [Publishing, and what residents see](#ch-publishing)
* [When something looks wrong](#ch-something-wrong)
* [Configuring the station](#ch-configuration)
* [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations)

<!-- SOURCES: inventory/screens/live.md; inventory/screens/channels.md; inventory/screens/controlroom.md; inventory/screens/remotecontribution.md; inventory/screens/facility.md; inventory/screens/cg.md; inventory/screens/cgdesigner.md; inventory/screens/health.md; inventory/screens/_shell-navigation-and-roles.md; inventory/screens/public-home.md (live-status wording); code verified directly: civiccast/live/router.py:255-347 (public on_air status), 501-535 (create, 409), 567-773 (preflight/go-on-air/end-broadcast are state-only), civiccast/live/preflight.py:135-195 (required checks, 50 GiB), civiccast/live/network_probe.py:51-52, civiccast/live/readiness.py:78-86 (30 s TTL, 5-300), civiccast/live/source_probe.py:138 (8 s), civiccast/live/store.py:266-286 (PK collision), civiccast/live/finalization_worker.py:861-874; apps/portal-operator/src/screens/LiveRoomScreen.tsx:63-65,1024-1143,1260,1364,1376-1440; civiccast/egress/automation.py:1-35,945,1348-1383 (auto_start re-issues start when no live process, 30 s retry, 2 s poll at 758); civiccast/egress/daemon.py:1495-1504; ChannelOpsScreen.tsx:692-830 (feed panel), 878-1074 (24/7 card), 1120-1277 (lower third), 1981; feed-command-confirm.ts:15-49; TakeoverCard.tsx:153-295; civiccast/egress/takeover_service.py:138-242; CommitToAirPanel.tsx:26,79-259,340-458; commit-format.ts:13-85; civiccast/schedule/commit_service.py:362-547; civiccast/egress/dispatcher.py:91-119; schedule/commit_models.py:79-88 (acknowledged never set); ScheduleScreen.tsx:708,745-751; civiccast/control_room/service.py:62-67,237,303-313,461-485,809; ControlRoomScreen.tsx:181-330,531,558-730; ControlRoomReadinessPanel.tsx:100-230; civiccast/live/contribution/service.py:57,323-395; civiccast/app.py:3075-3113; RemoteContributionScreen.tsx:344-407,601-690; civiccast/facility/store.py:41-88; facility/router.py:25-32; FacilityRouterScreen.tsx:304,391,850; CgBoardScreen.tsx:126,196-198,452-470,525-586,611,663,745; civiccast/egress/bulletin_filler.py:5-6,113,433; docs/releases/v1.0.0-beta.10-verification.md (proof status); second-pass checks: civiccast/installer/service.py:2530-2646,3780-3990 (sample source, rehearsal), civiccast/live/relay.py:105-125 and civiccast/egress/live_takeover.py (takeover refuses stale source before re-probe), civiccast/live/contribution/service.py:240-420 (admit keeps state connected), civiccast/facility/router.py:51-77, civiccast/stream/router.py:26-30 (roles), CommitToAirPanel.tsx:290-330 (upcoming list filters on schedule_item_id) -->

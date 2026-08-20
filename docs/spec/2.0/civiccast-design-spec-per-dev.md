Let me read the full UI/UX and relevant module sections before writing the list.

Here is the complete design brief. Organized by sprint, priority-ordered within each section. Sprint 0.3 is what's needed before any code can be written on the remaining pieces; everything after that is what you can define now to prevent design-blocking later.

---

## **CivicCast — Design Brief for the Design Team**

---

### **Foundational design system (blocks everything)**

Before any screen can be built, these need to exist:

1. **Design token values for Mode A standalone.** The spec says CivicCast uses `@civiccast/design-tokens`, a mirror of the CivicSuite tokens. That package does not exist yet. Need the actual values: color palette (semantic \+ brand), typography (font family, scale, weights, line heights), spacing (the 4px grid), border radii, elevation/shadows, animation timings.

2. **shadcn/ui theme.** The spec says shadcn/ui. shadcn requires a base theme selection. Which one, and what customizations? Specifically: are we on the default "zinc" neutral scale or something else? What's the brand primary color and its scale?

3. **Dark mode.** Supported or not in v1? If yes, define both palettes. If no, document that explicitly so operators on dark-mode systems don't get an unintentional white-on-white or broken theme.

4. **Icon set.** The spec names modules but not icons. What icon represents Schedule? Assets? Live? VOD? Captions? Summary Review? Syndication? Archive? Subscribers? Channel Settings? (shadcn/ui uses Lucide by default — is that the choice, or something else?)

5. **Toast / notification pattern.** Where do toasts appear? Duration? What does a success toast look like vs. an error toast? Which library (shadcn/ui Sonner, react-hot-toast, or the shadcn/ui toast primitive)?

6. **Confirmation dialog pattern.** The spec requires a confirm step before every destructive action (§4.1). What does that dialog look like? Single button ("Delete")? Double confirmation for the most destructive actions (like deleting a published asset)?

7. **Error message template.** The spec is explicit (§4.1): every error names the failure, names the file or operation, names the next step. Define the visual template for inline form errors, full-page errors, and error toasts.

8. **Loading and skeleton states.** What do loading states look like across the app? Skeletons? Spinners? Which contexts get which treatment?

9. **Performance budgets baked into design.** The spec (§4.1) requires: app loads in under 3 seconds on a 4-year-old tablet over 5 Mbps, first interactive frame under 1 second, every form submission acknowledges within 200ms. The design team should flag any component that is likely to violate these (e.g., a video thumbnail grid with 50 assets).

---

### **Sprint 0.3 — Operator shell skeleton**

10. **Top bar layout and contents.** What's in the top bar from left to right? Logo/wordmark placement. "Streaming Now" indicator — what does it look like when streaming is active vs. idle? Current asset display — what field is shown (title? ID?)? Time-to-next-event — what format ("Next: Council Meeting in 2h 14m")? What if nothing is scheduled ("No events scheduled")? Operator menu (account, logout) — where does it sit, and what's in it at Sprint 0.3 (before auth exists)?

11. **Left sidebar — full design.** Width expanded vs. icon-only vs. hamburger drawer at each breakpoint. Active item visual treatment. Hover state. Which items appear in the Sprint 0.3 nav (only Schedule and Assets exist — does the sidebar show all future items as disabled, or only show what's built)? Badge / notification indicator treatment (for future use like "3 items in review queue").

12. **Main pane chrome.** Default state when the shell first loads. What's the default view — the schedule, the asset library, or a dashboard?

13. **Right inspector.** When does it open and close? In Sprint 0.3, what triggers it? (An asset selected in the list? Never, because there's nothing to inspect yet?) If it's deferred entirely to Sprint 0.4+, document that explicitly so the layout reserves space.

14. **Mobile shell.** The spec says the sidebar becomes a hamburger drawer on phone widths (under 768px). What does the hamburger button look like? Where does it sit? Does the drawer slide in from the left or appear as an overlay? Does the top bar collapse at all on mobile?

15. **Profile-aware navigation.** At Sprint 0.3, only the "Public Meetings" and "Community Media" profiles are relevant. What does profile selection look like? A setting in the operator menu? A first-run prompt? Is there a visible profile indicator in the shell?

---

### **Sprint 0.3 — Asset upload UI**

16. **Entry point.** Where does the operator initiate an upload? A button in the Assets section of the sidebar? An "Upload" button in the asset list view? A floating action button?

17. **Upload form layout.** The API requires `asset_id`, `title`, `description` (optional), and a file. What does this form look like? Is it a full page, a modal, a side drawer? What's the field order? Are there character count indicators on title (max 200\) and description (max 2000)?

18. **Asset ID field.** Does the operator type this manually, or is it auto-generated (e.g., slugified from the title)? If auto-generated, can the operator override it? The current API pattern is `^[a-z0-9][a-z0-9-]{2,63}$` — if the operator types it manually, what does the validation feedback look like?

19. **File selection.** Drag-and-drop zone, file picker button, or both? What file types does the UI advertise as accepted (the backend validates but the UI should guide the operator)? What's the maximum file size, and is it shown?

20. **Upload and ingest progress.** Two sequential long-running operations: (a) file upload to server, (b) ffprobe ingest. The spec requires a progress indicator and cancel button for every long-running operation. What does each phase look like? A progress bar with percentage? A spinner with phase label ("Uploading… 42%", "Analyzing file…")? Can the operator cancel mid-upload? What happens to a partially uploaded file on cancel?

21. **Validation gate rejection UX.** When ffprobe rejects the file (unsupported codec, no video stream, etc.), what does the operator see? An inline error on the form? A modal? The spec requires the error to name the failure, name the file, and name the next step. Define the template: e.g., "test.wmv uses WMV2 video codec, which is not supported. Supported codecs: H.264, H.265, VP9, VP8, AV1, ProRes. Re-export the file and try again."

22. **Post-upload success.** After a successful upload and ingest, what happens? Navigate to the asset detail page? Show a success toast and stay on the form? Show the asset in the list with its new state? If the operator uploaded a file that passed ffprobe, the asset state is `validated` but has no manifest yet (HLS packaging is Sprint 0.4). Does the success screen communicate that the file is uploaded and ready for trim/scheduling, but not yet publicly viewable?

---

### **Sprint 0.3 — Asset library / list view**

23. **Layout.** Table, card grid, or list? What columns or fields are shown per asset? At minimum: title, state, upload date, duration, file size. What else?

24. **State indicators.** How does the operator see that an asset is in `pending_ingest`, `validated`, or `rejected` state? A color-coded badge? An icon? A text label? (The spec says no information conveyed by color alone — §18.5 — so the badge needs an icon or text alongside the color.)

25. **Per-asset actions.** What actions are available from the list? (Trim, Schedule, Delete, View details?) Where do they appear — a row action menu (three-dot), inline buttons, or only on the detail page?

26. **Empty state.** What does the asset library look like when no assets have been uploaded yet? An illustration? A "Upload your first asset" call-to-action?

27. **Search and filter.** Is there search in Sprint 0.3? Filter by state? Sort by date vs. name? Or is this deferred to a later sprint?

---

### **Sprint 0.3 — Trim / chapter editor**

This section has the most open questions. Every item below needs a specific answer.

**Timeline and scrubber:**

28. **Scrubber visual design.** What does the timeline look like? Options: (a) waveform visualization, (b) thumbnail strip (frames extracted at intervals), (c) plain timecode bar with a playhead. Which one, and at what detail level? A waveform requires audio extraction; a thumbnail strip requires frame extraction — both are backend work. Does the design team want to specify something simpler for v1?

29. **Timecode display.** What format — HH:MM:SS:FF (frames), HH:MM:SS.mmm (milliseconds), or HH:MM:SS? Is it editable (click to type a timecode and jump there)?

30. **In/out point interaction.** How does the operator set the in point and out point? Options: (a) keyboard shortcut (I for in, O for out) at current playhead position, (b) draggable handles on the timeline, (c) both. Which is primary on desktop? Which is primary on mobile (touch)?

31. **In/out point visual treatment.** Once set, how are in/out points shown on the timeline? Colored markers? Shaded region? A bracket overlay?

32. **Drag handle size and touch target on mobile.** The spec requires one-thumb phone operation. What's the minimum touch target size for the in/out handles? How does the operator differentiate tapping to seek from dragging a handle?

**Playback controls:**

33. **JKL shuttle speeds.** What are the speed steps? (e.g., J=reverse: 1x, 2x, 4x, 8x; K=pause; L=forward: 1x, 2x, 4x, 8x?) Is the current speed displayed on screen, and where?

34. **Frame-by-frame stepping.** Keyboard shortcut (left/right arrow when paused?) plus an on-screen button. What does the button look like? Where does it sit relative to the play button?

35. **Playback controls layout.** What's the full set of controls shown below the video player? Play/pause, frame-step left, frame-step right, JKL indicator, timecode display, volume. What's the order and grouping?

**Chapter markers:**

36. **Adding a chapter.** How does the operator add a chapter marker at the current playhead position? Keyboard shortcut (M?) plus an on-screen button? Or only via a menu?

37. **Chapter naming.** Where does the operator name a chapter? An inline text field that appears on the timeline at the marker position? A list panel alongside the timeline? Does the chapter name appear in the timeline scrubber or only in the list?

38. **Chapter list panel.** Is there a dedicated panel listing all chapters with their timecodes and names? Where does it sit — below the timeline? In the right inspector? Does it allow reordering?

39. **Deleting a chapter.** How? Click the marker and press Delete? A delete button in the chapter list? Confirmation required?

**Save behavior:**

40. **Destructive vs. non-destructive trim.** Does trim write a new file (destructive — original bytes modified or a new file created), or store in/out as metadata (non-destructive — original file untouched, trim applied at packaging time)? This is both a UX and backend architecture decision. The spec says assets are referenced by path — non-destructive is simpler and safer. But the operator UX differs significantly: non-destructive means "you can always undo the trim by resetting in/out," while destructive means "the original is gone." Which is it?

41. **Save / apply flow.** Is there an explicit Save button, or does the editor auto-save? If explicit: what happens to the asset state while unsaved changes exist (a "modified" indicator)? What's the confirmation copy for a destructive trim?

42. **Cancel / discard changes.** If the operator made trim/chapter changes and hits Cancel or navigates away, what happens? A "You have unsaved changes" browser-intercept-style warning? Or auto-save with no warning?

**Error and loading states:**

43. **Video loading.** What does the editor show while the video file is loading? A skeleton? A spinner over a dark rectangle?

44. **Video unavailable.** What if the file path is broken or the server can't serve the video? What error is shown, and what can the operator do?

45. **Trim point validation errors.** What if the operator sets out before in, or sets in past the end of the file? Inline error on the timeline? The controls snap to valid values? An alert?

---

### **Sprint 0.3 — Premiere / embargo scheduling UI**

46. **Entry point.** Where does the operator initiate scheduling? From the asset detail page (a "Schedule" button)? From a calendar/schedule view? Both?

47. **Scheduling mode selection.** The spec defines three modes: (1) live-event scheduling, (2) premiere scheduling (publish a recorded asset at a future time), (3) embargoed-release scheduling (approve now, publish later). At Sprint 0.3, only modes 2 and 3 are relevant (no live yet). How does the operator choose between premiere and embargo? Do they look different to the operator, or is it one form with a "scheduled publish time" field?

48. **Schedule form fields.** At minimum: asset (already selected if coming from asset detail), channel, scheduled date/time, scheduling mode. What else? A "notes" field? A recurrence option (deferred to later — but should the field be present and disabled, or absent entirely)?

49. **Date/time picker.** The spec requires timezone-explicit display with a `<TimezoneIndicator>` showing the operator's timezone vs. the broadcast's local timezone when they differ. What does this look like? A dual-timezone display below the picker? A warning when they differ? Which timezone is the "broadcast's local timezone" — a channel setting?

50. **Conflict detection error.** When btree\_gist rejects a conflicting schedule item, what does the operator see? An inline error naming the conflicting event: "This time slot conflicts with 'City Council Meeting' (6:00 PM – 9:00 PM). Choose a different time." Where does this error appear — on the form, or as a toast?

51. **Schedule calendar/grid view.** Is there a visual calendar showing scheduled items? If yes: week view? Day view? Month view? Does it show time blocks? Or is it just a list of upcoming scheduled items?

52. **Scheduled item states.** In the schedule list or calendar, how does the operator see the state of a scheduled item? (`scheduled`, `cancelled`, `published`) Color? Icon? Text badge?

53. **Cancel a scheduled item.** Confirmation flow: what's the copy? "Cancel this premiere" vs. "Remove from schedule"? Is cancellation reversible?

54. **Edit a scheduled item.** Can the operator change the scheduled time after creation? If yes, does conflict detection re-run on edit?

---

### **Sprint 0.4 — Live broadcast UI (define now, build later)**

55. **"Start Live Stream" / "End Live Stream" controls.** Where do they live in the shell? Top bar? A dedicated "Live" section of the main pane? What does the confirmation flow look like for ending a live stream (since it's a destructive action — the recording finalizes)?

56. **On-air preview.** What does the operator see during a live broadcast — a thumbnail-resolution preview of what's going out? Where does it sit in the layout? Is it always visible, or only when in the Live section?

57. **Source switcher panel.** During a live broadcast, the operator may switch between sources (camera A, camera B, screen share, etc.). What does the switcher UI look like? Buttons? A grid of source previews? What's the transition feedback (is there a "switching…" state)?

58. **Source drop alert.** When a live source drops mid-broadcast and falls back to slate, what does the operator see? A banner? A modal? An audio/visual alert? What action is required?

59. **Live caption sidebar.** During broadcast, the operator can monitor live captions. Where does this appear in the layout? Is it a collapsible panel? What does a low-confidence cue look like vs. a normal cue?

60. **Per-target syndication health badges.** The top bar shows syndication status during a live broadcast. What do the badges look like for "healthy," "degraded," "failed" states for each target? How many targets can be shown before the top bar overflows?

61. **Pre-flight checklist UI.** The 14-step checklist (§12.3). Is each step shown as a row with a pass/fail indicator? What does a step look like before it's run, while running, when it passes, when it fails? What's the "skip" interaction, and how is a skipped step indicated? Is there a summary view showing overall readiness before the operator clicks "Ready to go live"?

---

### **Sprint 0.5 — Caption review queue (define now, build later)**

62. **Review queue layout.** Is the queue a list of caption tracks awaiting review? Or a list of individual low-confidence cues across all tracks? Or both — a track list that expands to show its flagged segments?

63. **Low-confidence segment display.** The spec says Whisper flags low-confidence output. How are flagged segments shown? A color-coded confidence score? A visual indicator on the timeline where the segment lives?

64. **In-line caption editor.** What does editing a single cue look like? A text area that appears when you click a cue? An edit mode toggled by a button? Is the timecode editable, or just the text?

65. **Per-cue approve/edit/reject flow.** What are the three actions, and what do their buttons look like? What happens to the queue after the operator approves or rejects a cue — does the next cue auto-focus?

66. **Synchronized video playback.** When the operator clicks a cue, does the video seek to that timecode and play? Or does the operator have to manually scrub? Is the video player visible alongside the cue list, or does clicking a cue open a player?

---

### **Sprint 0.6 — Summary review UI (define now, build later)**

67. **Sourced-claim hyperlinks.** The spec says every claim in a summary links to the transcript timestamp range that supports it. What does this look like visually? Underlined text? A footnote-style citation? A highlight?

68. **Clicking a sourced claim.** What happens when the operator clicks a sourced-claim link? The spec says it seeks to that timestamp in the inline transcript player. Is the transcript player embedded in the summary review screen, or does clicking open a new view?

69. **The TranscriptScrubber component.** The spec defines this as a component that synchronizes a transcript with a video. What does it look like? Transcript on the left, video on the right? Active line highlighted as video plays? Clickable lines that seek the video?

70. **Approve / request revision / reject.** Three operator actions on a summary. What does approving look like — a big green "Approve and Queue for Publish" button? What does "request revision" mean in the UI (is this even a v1 feature, or does the operator edit the summary directly)?

71. **The refusal UI.** The spec says models refuse rather than guess when source evidence is insufficient. When the summary module refuses to produce a claim (e.g., "vote count not determinable from transcript"), what does the operator see in the review queue? A placeholder? A warning annotation? Something the operator can manually fill in?

---

### **Sprint 0.7 — Publish dashboard (define now, build later)**

72. **The seven plain-language states** (§18.3a) — define the visual treatment for each: "Ready for review," "Approved, publishing," "Public, archive pending," "Public, syndication degraded," "Archive complete," "Complete," "Needs operator action." What color, icon, and text represents each?

73. **Per-surface status display.** How does the dashboard show the status of each individual surface (portal, IA, YouTube, NAS, podcast, signed transcript)? A row per surface? A grid? What's the visual treatment for a surface that's pending vs. succeeded vs. failed?

74. **Retry flow.** When a surface fails (e.g., YouTube auth expired), what does the "Needs operator action" state look like in detail? Is there a "Retry" button per surface? A link to credential settings? What copy explains the failure?

75. **Canonical vs. reach distinction.** The spec requires the dashboard to visually distinguish canonical availability (portal is public) from reach availability (YouTube is up) and from archive completeness (IA \+ NAS). How is this distinction communicated to the operator — separate sections? A hierarchy of indicators?

---

### **Sprint 0.8 — Subscriber signup page (define now, build later)**

76. **Public-facing signup page.** This is resident-facing (not operator-facing). What does it look like? The spec says it must be accessible (WCAG 2.2 AA) and have double opt-in. Fields: email address, name (optional?), channel selection (if multiple channels exist). Design language: does it use the same design tokens as the operator shell, or a simplified public-facing variant?

77. **Double opt-in confirmation page.** After the resident clicks the link in their confirmation email, they land on a confirmation page. What does it say? Does it redirect to the portal afterward?

78. **The SubscriberStats operator view.** The spec names a `<SubscriberStats>` component showing per-channel subscriber count and growth chart. Where in the operator shell does it live — Channel Settings? A dedicated Subscribers section? What does the growth chart look like (line chart? bar chart? Recharts component)?

---

### **Sprint 0.10 — Installer wizard (define now, build later)**

79. **11-screen profile-driven wizard.** The spec describes this at a high level (§20). The design team needs to define all 11 screens: their titles, the fields/choices on each, the navigation (back/next/skip), and the completion state. This is a separate design package — it's large enough to be its own brief. Flag this as needing a dedicated session.

---

### **Public VOD portal (ongoing)**

80. **Portal page states for uploaded-but-not-packaged assets.** At Sprint 0.3, uploaded assets have no HLS manifest yet. The public portal currently only shows assets with `manifest_url`. When an operator links to an asset that's uploaded but not yet packaged, what does the resident see? A "coming soon" state? A 404? This matters now because the Sprint 0.3 exit criterion involves the operator seeing the asset on the portal.

81. **Asset detail page on the portal.** After HLS packaging (Sprint 0.4), the resident can watch the asset. What does the asset detail page look like? Title, description, player, captions track switcher, embed button, chapter navigation. Define this now so Sprint 0.4 has a target.

---

### **Cross-cutting questions**

82. **Auth / operator login.** The spec mentions bearer token or OIDC for Mode A. At Sprint 0.3, there's no auth. When auth lands, what does the login screen look like? Is this in scope for the design brief?

83. **Mobile keyboard shortcut fallback.** JKL shuttle, I/O in/out points, M for chapter markers — these are keyboard shortcuts that don't exist on a phone. For every keyboard shortcut defined, the design team needs to define the corresponding on-screen touch control. These should be designed together, not as an afterthought.

84. **Responsive behavior of every screen.** The spec mandates full one-thumb phone operation for every primary workflow. Every screen in this brief needs a mobile layout defined, not just the desktop layout.

85. **Audit log visibility.** The spec mentions an audit log for many actions (overrides, approvals, skipped pre-flight steps). Is the audit log visible to the operator in the UI? Where? Or is it backend-only in v1?

# Beta 17 deferred field follow-up

**Owner decision:** defer these field and workflow follow-ups until after the
`v1.0.0-beta.16` release. They are not a Beta 16 release gate or
evidence that Beta 16 has the same behavior. Recheck relevant items against the
actual candidate when the owner schedules that work.

Evidence source: `D:\CivicCast-Beta15-Evidence\MICROMONSTERPC\CivicCast-Beta15-FieldTest-MICROMONSTERPC-20261013-110159\FINAL-REPORT.md`.

## Confirmed Beta 15 observations

- **Scheduled programmes showed slate on R9.** During the scheduled speech
  windows, sampled output on all three channels was CivicCast slate with silent
  audio and header-only captions. A later long-soak tester remained on slate,
  so that interval did not establish useful speech captions or capacity. The
  cause is unconfirmed; do not attribute it to Whistle. Investigate schedule
  preparation, planned-start propagation, source transitions, and output proof.
- **CG playlist hardcodes missing segments.** The observed playlist returned
  HTTP 200 and listed `cg-00000.ts` and `cg-00001.ts`, which returned 404. A
  source review found `cg/service.py`'s `build_hls_manifest` still emits these
  fixed segment names and found no segment implementation there. Implement a
  CG segment producer and generate the playlist from its available segments;
  verify every listed URL. No Beta16 installed-runtime reproduction has been
  established.
- **Installed native executable needs signing.** The installed
  `CivicCast Native.exe` reported `NotSigned`; the outer setup executable was
  separately reported as validly signed. The signing workflow signs the outer
  setup but leaves the installed executable unsigned. Sign the installed
  executable as part of packaging and verify its installed signature. No Beta16
  installed-runtime reproduction has been established.
- **Trimmed captions retain source timestamps.** A source trimmed from 34
  seconds to 2–32 seconds packaged as about 30.04 seconds, while generated cues
  still included source times 0–3 and 30–34. Source review found
  `publish/router.py` passes the original `source_path` and
  `captions/vod_job.py` has no trim-time mapping. Rebase cues onto the packaged
  timeline and verify playback. The report did not establish the exact
  resident-player subtitle offset; no Beta16 installed-runtime reproduction
  has been established.
- **R9 free space fell by 15.117 GiB.** C: decreased from 198.192 GiB at the
  formal baseline to 183.075 GiB at the last checkpoint. The responsible paths
  were not identified. Investigate the storage accounting; this is not a
  confirmed CivicCast leak.

## Lower-priority observations and incomplete workflows

- **UI/process reporting differed.** The UI used GStreamer-oriented worker
  language while native workers were FFmpeg processes; some PID and
  stopped/running descriptions also differed from fresh process evidence.
  Reconcile the labels and status sources; no common cause was confirmed.
- **Share-link clipboard behavior is unconfirmed.** After a Copy action, the
  clipboard still held the earlier Library URL. The current link was not
  verified and there was no proof that the copy action ran, so this is not a
  confirmed clipboard defect.
- **Summary workflow stopped at a memory safeguard.** Generation was deferred
  with 12.7 GiB available against an 8 GiB model request plus an 8 GiB
  broadcast reserve. The safeguard worked; summary editing, approval, export,
  and publication were not completed. Verify the full workflow with adequate
  memory before assigning a product defect.
- **Caption review and Spanish workflow were incomplete.** Two low-confidence
  English cues were not compared against audio; resident caption attachment
  and Spanish translation/review/publication were not completed. These gaps do
  not prove a translation or captioning bug.

The field report describes one in-place Beta 12-to-Beta 15 upgrade on
MICROMONSTERPC. It records these package-specific observations and their
measurement limits; it does not identify all causes, and it is not Beta 16
candidate verification. The [Beta 15 verification record](../releases/v1.0.0-beta.15-verification.md)
and [Beta 16 package verification record](../releases/v1.0.0-beta.16-verification.md)
remain the package-specific sources for those releases.

# AUTORUN-9z soak #2: reschedule the approved soak assets on kit 91caebc, start, restart the soak clock
- mission: soak8-e1acfe6
- host: DESKTOP-VBMA6O5
- utc: 20260905T210648Z
- kit: C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6
- DryRun: False


## stale soak-clock state (from the 9d run that never actually started anything)
removed stale state file: C:\CivicCastSoak\state\soak-started
removed stale state file: C:\CivicCastSoak\state\last-egress-run
stale state file not present (nothing to remove): C:\CivicCastSoak\state\last-rollup-hours
stale state file not present (nothing to remove): C:\CivicCastSoak\repo\soak\final-verdict.json
station healthy; schema=current db_revision=
staff token loaded from C:\CivicCastSoak\state\token
samples found: 4
  - YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_001_1080p.mp4 (17 MB)
  - YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p.mp4 (4 MB)
  - YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p.mp4 (33 MB)
  - YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p.mp4 (819 MB)
ffprobe: not found -- falling back to a 30s default duration per clip

## channel config PUT bodies (built now; PUT deferred to after scheduling -- see file header B-B rationale)
config body for public:
```json
{
    "channel_id":  "public",
    "enabled":  true,
    "auto_start":  true,
    "allow_software_fallback":  true,
    "fill_policy":  "slate",
    "slate_message":  "Soak8 AUTORUN-9e -- three-channel product-engine soak.",
    "sinks":  [
                  {
                      "kind":  "udp-ts",
                      "label":  "soak8-9e-public",
                      "uri":  "udp://127.0.0.1:9001",
                      "latency_ms":  2000,
                      "loudness_regime":  "inherit",
                      "eas_tone_strip_enabled":  true
                  }
              ]
}
```
config body for education:
```json
{
    "channel_id":  "education",
    "enabled":  true,
    "auto_start":  true,
    "allow_software_fallback":  true,
    "fill_policy":  "slate",
    "slate_message":  "Soak8 AUTORUN-9e -- three-channel product-engine soak.",
    "sinks":  [
                  {
                      "kind":  "udp-ts",
                      "label":  "soak8-9e-education",
                      "uri":  "udp://127.0.0.1:9002",
                      "latency_ms":  2000,
                      "loudness_regime":  "inherit",
                      "eas_tone_strip_enabled":  true
                  }
              ]
}
```
config body for government:
```json
{
    "channel_id":  "government",
    "enabled":  true,
    "auto_start":  true,
    "allow_software_fallback":  true,
    "fill_policy":  "slate",
    "slate_message":  "Soak8 AUTORUN-9e -- three-channel product-engine soak.",
    "sinks":  [
                  {
                      "kind":  "udp-ts",
                      "label":  "soak8-9e-government",
                      "uri":  "udp://127.0.0.1:9003",
                      "latency_ms":  2000,
                      "loudness_regime":  "inherit",
                      "eas_tone_strip_enabled":  true
                  }
              ]
}
```

## asset upload call (per staged clip)
POST $base/api/staff/assets/upload -- multipart/form-data: fields asset_id, title, file=<clip bytes>, Authorization: Bearer <token>
staged clip count (cap 4): 4
  - C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\samples\YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_001_1080p.mp4
  - C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\samples\YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p.mp4
  - C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\samples\YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p.mp4
  - C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\samples\YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p.mp4

## schedule item body (per item) -- POST $base/api/staff/schedule
```json
{
    "asset_id":  "\u003casset_id\u003e",
    "channel_id":  "\u003cchannel_id\u003e",
    "mode":  "premiere",
    "scheduled_at":  "\u003ciso8601 utc\u003e",
    "duration_seconds":  "\u003cint, from ffprobe\u003e",
    "notes":  "Soak8 AUTORUN-9z soak #2 on kit 91caebc"
}
```
## commit-to-air body (per item) -- POST $base/api/staff/playout/commit
```json
{
    "channel_id":  "\u003cchannel_id\u003e",
    "occurrence_id":  "\u003cper-item id\u003e",
    "schedule_item_id":  "\u003cfrom the schedule POST response\u003e"
}
```
schedule window: 120 + 15 minutes per channel, back-to-back using each clip's real ffprobe duration, cycling the staged clips
GET /api/staff/assets?limit=200 -> 200 [{"asset_id":"soak8-9u-260905134834-alzj","title":"Soak8 9e Asset YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p 2026-09-05 13:48:34","description":null,"meeting_body":null,"state":"validated","manifest_url":"/media/vod/soak8-9u-260905134834-alzj/playlist.m3u8","published_at":"2026-09-05T20:03:01.369828Z","file_path":"C:\\ProgramData\\CivicCast\\data\\uploa
asset records returned: 4
asset reused: soak8-9u-260905134834-alzj (duration_seconds=2365, state=validated, title=Soak8 9e Asset YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p 2026-09-05 13:48:34)
asset reused: soak8-9u-260905134813-ebno (duration_seconds=667, state=validated, title=Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 13:48:13)
asset reused: soak8-9u-260905134810-wgkq (duration_seconds=67, state=validated, title=Soak8 9e Asset YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p 2026-09-05 13:48:10)
asset reused: soak8-9u-260905134758-zsyr (duration_seconds=67, state=validated, title=Soak8 9e Asset YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_001_1080p 2026-09-05 13:47:58)
schedule item FAILED channel=public asset=soak8-9u-260905134834-alzj status=409 body=
schedule item FAILED channel=public asset=soak8-9u-260905134813-ebno status=409 body=
schedule item FAILED channel=public asset=soak8-9u-260905134810-wgkq status=409 body=
channel=public schedule_items_created=4 schedule_items_committed=4 schedule_items_commit_failed=0 schedule_items_failed=5
schedule item FAILED channel=education asset=soak8-9u-260905134834-alzj status=409 body=
schedule item FAILED channel=education asset=soak8-9u-260905134813-ebno status=409 body=
schedule item FAILED channel=education asset=soak8-9u-260905134810-wgkq status=409 body=
channel=education schedule_items_created=4 schedule_items_committed=4 schedule_items_commit_failed=0 schedule_items_failed=5
schedule item FAILED channel=government asset=soak8-9u-260905134834-alzj status=409 body=
schedule item FAILED channel=government asset=soak8-9u-260905134813-ebno status=409 body=
schedule item FAILED channel=government asset=soak8-9u-260905134810-wgkq status=409 body=
channel=government schedule_items_created=4 schedule_items_committed=4 schedule_items_commit_failed=0 schedule_items_failed=5
PUT config public: ok (udp 127.0.0.1:9001)
start queued: public
PUT config education: ok (udp 127.0.0.1:9002)
start queued: education
PUT config government: ok (udp 127.0.0.1:9003)
start queued: government

## per-channel state/pid after start (poll up to 3 minutes for ON_AIR)
public: config_ok=True start_ok=True state=ON_AIR pid=46360 last_error=
education: config_ok=True start_ok=True state=ON_AIR pid=41460 last_error=
government: config_ok=True start_ok=True state=ON_AIR pid=19896 last_error=
observed worker processes: gst-launch-1.0=0 ffmpeg=1
soak #3 (30-s items) probes archived to soak/archive-91caebc-soak3-30s-items; relaunch/pid/rollup counters reset
soak-started WRITTEN (UTC): 2026-09-05T21:08:51.9581138Z -- at least one channel confirmed ON_AIR

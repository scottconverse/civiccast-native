# AUTORUN-9w restart channels after the CLEAN reinstall of 91caebc (9u saw no ON_AIR within 3 min), then restart the soak
- host: DESKTOP-VBMA6O5
- utc: 20260905T201628Z

health: status=healthy version=1.0.0-beta.5 schema=current
## channel state BEFORE
public : 200 {"channel_id":"public","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p 2026-09-05 13:48:10","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.714727Z","pid":25036,"last_error":null}
education : 200 {"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p 2026-09-05 13:48:34","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.668023Z","pid":14076,"last_error":null}
government : 200 {"channel_id":"government","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 13:48:13","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.688813Z","pid":39788,"last_error":null}
GET /api/staff/egress/channels -> 200 [{"channel_id":"education","enabled":true,"sink_count":1,"state":{"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p 2026-09-05 13:48:34","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.668023Z","pid":14076,"last_error":null},"latest_health":{"channel_id":"education","sampled_at":"2026-09-05T20:16:28.655733Z","state":"ON_AIR","sink_connected":{"soak8-9e-education":false},"encoder_fps":null,"encoder_bitrate_kbps":null,"dropped_frames":0,"seconds_on_air":40,"last_
## start commands
start public -> 202 {"command":{"channel_id":"public","action":"start","issued_at":"2026-09-05T20:16:29.545229Z","issued_by":"soakadmin","command_id":"egress-2b37195a-3d63-4810-81d9-c98ce6c9cbec"},"queued":true}
start education -> 202 {"command":{"channel_id":"education","action":"start","issued_at":"2026-09-05T20:16:29.573678Z","issued_by":"soakadmin","command_id":"egress-fea3c6f9-5d6c-4d61-a461-60001484a715"},"queued":true}
start government -> 202 {"command":{"channel_id":"government","action":"start","issued_at":"2026-09-05T20:16:29.597632Z","issued_by":"soakadmin","command_id":"egress-0d4b83d1-0403-4438-8a58-4d956d481ee9"},"queued":true}
## channel state AFTER (poll up to 6 min)
public : 200 {"channel_id":"public","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p 2026-09-05 13:48:10","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.714727Z","pid":25036,"last_error":null}
education : 200 {"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p 2026-09-05 13:48:34","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.668023Z","pid":14076,"last_error":null}
government : 200 {"channel_id":"government","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 13:48:13","current_proof_event_id":null,"updated_at":"2026-09-05T20:16:28.688813Z","pid":39788,"last_error":null}
ON_AIR: 3/3 [public, education, government]
old probes archived to soak/archive-91caebc-soak2-oldcode; counters reset; soak #3 started 2026-09-05T20:16:29.7453113Z on kit 91caebccc6a6decef476fea5cd785a9ff19abfe6

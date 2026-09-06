# AUTORUN-9zl restart channels after the CLEAN install of 609273d (9zj saw no ON_AIR within 3 min), then restart the soak
- host: DESKTOP-VBMA6O5
- utc: 20260906T022615Z

health: status=healthy version=1.0.0-beta.5 schema=current
## channel state BEFORE
public : 200 {"channel_id":"public","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.481317Z","pid":40628,"last_error":null}
education : 200 {"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.414808Z","pid":33192,"last_error":null}
government : 200 {"channel_id":"government","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.452744Z","pid":24456,"last_error":null}
GET /api/staff/egress/channels -> 200 [{"channel_id":"education","enabled":true,"sink_count":1,"state":{"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.414808Z","pid":33192,"last_error":null},"latest_health":{"channel_id":"education","sampled_at":"2026-09-06T02:26:14.414808Z","state":"ON_AIR","sink_connected":{"soak8-9e-education":false},"encoder_fps":null,"encoder_bitrate_kbps":null,"dropped_frames":0,"seconds_on_air":12,"last_l
## start commands
start public -> 202 {"command":{"channel_id":"public","action":"start","issued_at":"2026-09-06T02:26:16.281914Z","issued_by":"soakadmin","command_id":"egress-a9fc837e-aaa1-4b16-ace9-00b04aada81f"},"queued":true}
start education -> 202 {"command":{"channel_id":"education","action":"start","issued_at":"2026-09-06T02:26:16.297084Z","issued_by":"soakadmin","command_id":"egress-a74b93ab-065b-4081-a7ce-2b2398fb9493"},"queued":true}
start government -> 202 {"command":{"channel_id":"government","action":"start","issued_at":"2026-09-06T02:26:16.334970Z","issued_by":"soakadmin","command_id":"egress-e0fe5eec-112e-4ab4-b2b4-7fa2be451f05"},"queued":true}
## channel state AFTER (poll up to 6 min)
public : 200 {"channel_id":"public","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.481317Z","pid":40628,"last_error":null}
education : 200 {"channel_id":"education","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.414808Z","pid":33192,"last_error":null}
government : 200 {"channel_id":"government","state":"ON_AIR","current_source_label":"Soak8 9e Asset YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p 2026-09-05 19:57:15","current_proof_event_id":null,"updated_at":"2026-09-06T02:26:14.452744Z","pid":24456,"last_error":null}
ON_AIR: 3/3 [public, education, government]
old probes archived to soak/archive-609273d-prev-soak; counters reset; soak #5 started 2026-09-06T02:26:16.5653747Z on kit 609273da22b968b8ed9320dfc158d67b01eb30b3

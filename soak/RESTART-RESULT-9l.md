# AUTORUN-9l restart channels after the 91caebc upgrade, then restart the soak
- host: DESKTOP-VBMA6O5
- utc: 20260905T183629Z

health: status=healthy version=1.0.0-beta.5 schema=current
## channel state BEFORE
public : 200 {"channel_id":"public","state":"FALLBACK_SLATE","current_source_label":null,"current_proof_event_id":null,"updated_at":"2026-09-05T18:36:27.075920Z","pid":null,"last_error":"No valid source plan is available; generated fallback slate."}
education : 200 {"channel_id":"education","state":"FALLBACK_SLATE","current_source_label":"CivicCast slate","current_proof_event_id":"egress-proof-700be6ab-c777-4d87-84dc-8e1f5c5c603f","updated_at":"2026-09-05T18:36:19.090545Z","pid":37360,"last_error":null}
government : 200 {"channel_id":"government","state":"FALLBACK_SLATE","current_source_label":"CivicCast slate","current_proof_event_id":"egress-proof-b74564bc-0c8d-42f6-9706-66c3a92d1686","updated_at":"2026-09-05T18:36:19.124042Z","pid":41332,"last_error":null}
GET /api/staff/egress/channels -> 200 [{"channel_id":"education","enabled":true,"sink_count":1,"state":{"channel_id":"education","state":"FALLBACK_SLATE","current_source_label":"CivicCast slate","current_proof_event_id":"egress-proof-700be6ab-c777-4d87-84dc-8e1f5c5c603f","updated_at":"2026-09-05T18:36:19.090545Z","pid":37360,"last_error":null},"latest_health":{"channel_id":"education","sampled_at":"2026-09-05T18:36:19.090545Z","state":"FALLBACK_SLATE","sink_connected":{"soak8-9e-education":true},"encoder_fps":null,"encoder_bitrate_kbps":null,"dropped_frames":0,"seconds_on_air":161,"last_loudness_lufs":-70.0,"caption_status":"not-v
## start commands
start public -> 202 {"command":{"channel_id":"public","action":"start","issued_at":"2026-09-05T18:36:30.231969Z","issued_by":"soakadmin","command_id":"egress-12bdd2bc-74bf-4c79-9110-0bbc3d430daf"},"queued":true}
start education -> 202 {"command":{"channel_id":"education","action":"start","issued_at":"2026-09-05T18:36:30.260436Z","issued_by":"soakadmin","command_id":"egress-bdcbcaa2-6cc1-40c8-9e77-25586e58694c"},"queued":true}
start government -> 202 {"command":{"channel_id":"government","action":"start","issued_at":"2026-09-05T18:36:30.279154Z","issued_by":"soakadmin","command_id":"egress-1c3586ca-959d-44c8-99e2-98809b39652d"},"queued":true}
## channel state AFTER (poll up to 6 min)
public : 200 {"channel_id":"public","state":"ON_AIR","current_source_label":"CivicCast slate","current_proof_event_id":null,"updated_at":"2026-09-05T18:37:00.101174Z","pid":25116,"last_error":null}
education : 200 {"channel_id":"education","state":"ON_AIR","current_source_label":"CivicCast slate","current_proof_event_id":null,"updated_at":"2026-09-05T18:37:00.051351Z","pid":38976,"last_error":null}
government : 200 {"channel_id":"government","state":"ON_AIR","current_source_label":"CivicCast slate","current_proof_event_id":null,"updated_at":"2026-09-05T18:37:00.073304Z","pid":41332,"last_error":null}
ON_AIR: 3/3 [public, education, government]
soak #1 history archived to soak/archive-e502074-soak1; counters reset; soak #2 started 2026-09-05T18:37:00.8256726Z on kit 91caebccc6a6decef476fea5cd785a9ff19abfe6

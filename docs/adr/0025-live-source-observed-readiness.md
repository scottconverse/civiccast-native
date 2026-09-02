# ADR 0025 -- Live-source readiness is an observation, and only SRT may carry a credential

- **Status:** Accepted
- **Date:** 2026-09-02
- **Work package:** WP-07 (implementation plan, audit finding ENG-003)
- **Supersedes:** nothing. Completes the fix bug B5 started.

## Context

A configured live source (`live_sources` row) was treated as ready because it
existed. `civiccast.live.relay._source_path` stamped
`health_state = RELAY_HEALTH_READY` on every configured row, with a docstring
arguing that the ingest plan "describes WHICH paths exist and are configured,
not whether media is flowing right now".

That argument was wrong in the one place it mattered.
`civiccast.egress.live_takeover.build_live_takeover_source_plan` refuses any
path whose `health_state` is not `ready`, and it is the only gate a manual
takeover passes before a takeover audit row is written and a route-change
command is queued. So "configured" was silently promoted to "safe to cut to":
a camera unplugged for a week and a live encoder were indistinguishable right
up to the moment air went black.

Two further defects sat next to it.

1. `/api/staff/live/ingest-plan` had been fixed under B5 to include the
   channel's `LiveSourceStore` rows, but `civiccast.app._resolve_takeover_service`
   still built its ingest-plan provider from relay configuration only -- as did
   `civiccast.cli._build_takeover_service`. A source could appear in the API
   plan while being invisible to production takeover.
2. `live_sources.credentials_handle` had existed since migration `0007` and
   nothing anywhere read it back. An operator could store a handle, have it
   echoed back by the API, and the station would still probe and open the
   source with no credential at all.

There was also no update path at all: `LiveSourceStore` shipped `create` /
`get` / `list`, deferring edit "until a later rung defines the operator-cancel
+ edit UX".

## Decisions

### D1 -- Readiness is a persisted observation with a TTL, not a property of the row

Migration `0086_live_source_probe_state` adds `probe_state`,
`probe_observed_at`, `probe_detail`, `probe_error_code`,
`probe_last_success_at`, and `row_version` to `live_sources`.

Four operator-facing states: `never_probed`, `ready`, `stale`, `failed`.
Only three are persisted. **`stale` is deliberately not a stored value** -- it
is derived from `probe_observed_at` against the readiness TTL. A persisted
"stale" would outlive the successful probe that should have cleared it.

Durable rather than in-memory because an in-memory cache resets to empty on
restart, and the reading a station wants after a service restart thirty
seconds before gavel is "nobody has looked", not "everything is ready".

Existing rows backfill to `never_probed`. Upgrading an already-configured
station into "everything is ready" would reproduce the exact defect.

### D2 -- The readiness TTL is 30 seconds, bounded 5-300, and clamps rather than raises

`CIVICCAST_LIVE_SOURCE_READINESS_TTL_SECONDS`, following the repository's
existing `CIVICCAST_*` env-var settings idiom (there is no central `Settings`
class). Thirty seconds is short enough that "ready" means "ready now" in the
minute before a meeting, long enough that clicking through the Live Room does
not re-probe every encoder on every render.

Out-of-range and unparseable values clamp or fall back. This value is read on
the request path that renders the Live Room; a mistyped env var must not take
the operator's source list down. The clamped value is reported by the API, so
the UI and the takeover gate can never disagree about which TTL was applied.

### D3 -- The takeover gate re-probes before any durable side effect

`TakeoverService.take` gains an injected `readiness_verifier`, called after the
source plan is built and **before** the audit row is written or the command is
queued. Ordering is the decision: an audit row is the station's durable record
that a takeover happened, and the queued command moves air as soon as the
daemon reads it.

The verifier (`LiveSourceReadinessService.verify_for_takeover`) re-reads the
row, compares its endpoint against the endpoint the plan actually offered
(closing the plan-built-then-source-edited race), reuses a within-TTL success,
and performs one bounded fresh probe for every other state. Anything uncertain
-- row gone, endpoint changed, probe refused, credential unresolved, observation
unrecordable -- fails closed with a named reason.

The verifier is additive, not the floor. The floor is the plan's own
`health_state`, which D1 made observation-derived, so a caller that omits the
verifier still cannot take air with an unchecked source.

### D4 -- Editing a source clears its readiness in the same transaction

`PATCH /api/staff/live/sources/{id}` plus `LiveSourceStore.update`. Any change
to **what would be probed** -- endpoint, source type, channel, credential
reference -- resets the row to `never_probed` in the same transaction that
applies the edit. A rename does not: the name is not part of what gets probed,
and forcing a re-probe to rename a camera before gavel would be a worse
product.

`probe_last_success_at` deliberately survives both an edit and a later failure:
"never worked" and "worked until 09:41" are different facts.

`row_version` gives optimistic concurrency. A PATCH carrying a stale
`expected_row_version` is refused 409 with both versions, rather than silently
discarding the other operator's edit. Omitting it is last-writer-wins, which is
what a scripted single-operator station wants.

Validation runs against the **merged** row, not the request body, so changing
only `source_type` is checked against the endpoint the row already holds.

### D5 -- One place decides what endpoint shape each source type accepts

`civiccast.live.source_endpoints.normalize_endpoint`, keyed on the persisted
`source_type` rather than on the Setup wizard's `kind`, and applied to both
create and update. It returns the canonical stored value so two spellings of
one address cannot become two rows.

`rtmps` maps to source type `rtmp` and `rtsps` to `rtsp` because the Setup
wizard has always stored the TLS spellings that way and the schema's
`live_sources_source_type_check` has no value to store instead. Rejecting them
would break every existing TLS source on its next edit.

NDI takes a source **name** -- spaces and parentheses included, because that is
how an NDI sender advertises itself -- and never a path.

### D6 -- Only SRT may carry a stored credential; RTSP and RTMP authenticated shapes are rejected

`CREDENTIAL_SUPPORTED_SOURCE_TYPES = {"srt"}`.

SRT qualifies because its passphrase is a first-class option on both runtimes
this product drives: FFmpeg's libsrt protocol option `-passphrase`, and
GStreamer's `srtsrc passphrase=` property. The secret never has to be
interpolated into an endpoint URL that gets persisted, logged, returned in an
ingest plan, or written into proof output.

RTSP and RTMP are excluded. Neither FFmpeg demuxer accepts a username/password
anywhere except inside the URL, so an authenticated RTSP/RTMP source could only
be probed by building `rtsp://user:secret@host/...`. GStreamer's `rtspsrc` does
have `user-id`/`user-pw`, but a source CivicCast cannot *probe* can never
become observed-ready, so playout capability alone is not enough. NDI has no
credential concept.

Rejection is explicit, not silent: the API refuses the shape with operator
copy, and the UI disables the credential control and shows that copy.

### D7 -- The handle travels; the secret is resolved at execution time

The database stores only the opaque handle. `civiccast.live.secrets` is a
keyring-backed namespace (`civiccast.live-source`) matching
`civiccast.ai_models.secrets` and `civiccast.control_room.secrets`, and an
injected `SecretResolver` resolves it **per probe** -- so rotating a passphrase
in the credential store takes effect on the next check without a restart.

For playout the constraint is sharper: `graph_from_config` runs in the strategy
process and its result is written to a JSON file on disk for the worker to read
back, so anything in `ElementSpec.props` is persisted. `ElementSpec` therefore
gains `secret_props` (property name -> handle), serialized as handles, resolved
by the worker in `PlayoutPipeline._make` at element-construction time. A handle
that cannot be resolved raises rather than starting the feed unauthenticated.

Everything the probe returns is passed through `redact_secrets` before it
reaches a row, a response, or a log line -- belt-and-suspenders against a future
libsrt build echoing the option it was handed back through stderr.

## Consequences

- A station upgrading to `0086` sees every configured source as "Not checked"
  until an operator presses **Check source**. That is the intended, safe
  reading, and it is a visible behaviour change for existing stations.
- Manual takeover now performs a bounded ffprobe in the request path when the
  stored observation is not fresh. That is one subprocess with an existing
  wall-clock ceiling, on an action that is already synchronous.
- The pre-existing SRT **sink** path (`bridge.sink_element_spec`) still
  resolves its passphrase eagerly into a URI query parameter. That is out of
  WP-07's scope and is recorded here rather than silently left unmentioned.
- No push-to-CivicCast RTMP listener is introduced, and no GStreamer engine
  rebuild was required.

## Known limitations

- No physical encoder was used. The probe subprocess boundary and the
  GStreamer element-construction boundary are proven at their seams; the
  end-to-end "a real SRT encoder with a passphrase takes air" path needs a
  station with hardware, which is the LPM lab's job after the software lands.
- `-passphrase` reaches ffprobe as one argv element of a short-lived child
  process, so it is visible to another process running as the same Windows user
  for the duration of the probe. That is the narrowest channel FFmpeg offers;
  the alternative (a URL query parameter) would additionally reach logs, ingest
  plans, and proof output.

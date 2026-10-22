# Station federation

Use **Run meeting → Other stations** to browse another trusted station's published
programmes, open their public watch pages, and monitor or start/stop selected
remote channels. The remote station remains responsible for publication,
playback access and channel execution. A command receipt means **queued**;
refresh status to confirm the remote daemon actually changed state.

## Configure trusted stations

The station administrator provisions `federation.json` beside the service's
`station-state.json`. `CIVICCAST_FEDERATION_CONFIG` can select another file.
An absent file means no peers are configured; a malformed file produces an
actionable configuration error. Filesystem and service-environment access
remain administrator responsibilities. The operator screen accepts station
IDs, not arbitrary remote URLs, bearer tokens or proxy commands.

Example configuration:

```json
{
  "stations": [
    {
      "station_id": "neighbor",
      "label": "Neighbor community station",
      "public_origin": "https://watch.neighbor.example",
      "staff_origin": "https://staff.neighbor.example",
      "token_env": "CIVICCAST_NEIGHBOR_STAFF_TOKEN",
      "channel_ids": ["public", "government"]
    }
  ]
}
```

Use the actual public and staff HTTPS origins, without URL paths, query
parameters, fragments or embedded credentials. Private LAN HTTPS hosts are
supported. Both servers need valid trusted certificates. Peer requests do
not follow redirects or use environment-configured HTTP proxies. Only the
fixed public asset catalogue and staff egress channel/status/command routes
are accessed. At most 32 peers and 32 managed channels per peer are accepted.

For catalogue-only access, omit `staff_origin` and `token_env`. To permit
management, configure both and place a remote station staff bearer token in
the named **service environment variable**, not in this JSON file or the
browser. Use CivicCast's existing supported token provisioning/rotation
procedure. The token must hold the remote `meeting_operator` role to issue
commands. Its remote role checks still apply; revocation or insufficient
roles results in a truthful remote-authorization error. The remote HTTPS
proxy must also allow the central station's network. Local publication
permissions do not grant remote management permissions.

Changing the configuration file takes effect on the next request. Changing a
secret in the service environment requires the existing Windows service
configuration/restart procedure before the process can read the new value.
Token values and token environment names
are never returned by the federation API. They are not sent with public
catalogue requests. Remove a peer to withdraw access from this console;
revoke its remote token to withdraw that credential everywhere.

## Operator workflow

1. Open **Run meeting → Other stations** and select a configured station.
2. Browse its published programmes and open a public watch link. These links
   use the station's canonical `/#/watch/{asset_id}` route. Publication does
   not grant a redistribution license; use the station's normal programme
   sharing arrangements.
3. If management is configured, refresh channel status. Only channel IDs
   allowed in the local peer configuration appear.
4. Select Start or Stop and explicitly confirm the action for that station and
   channel. The remote staff API checks its own configuration and roles.
5. Review the queue receipt, then refresh status. A timeout may happen after
   the command was queued: check the remote state before retrying.

The local roles `setup_admin`, `meeting_operator`, `support_admin` and
`publish_operator` can browse peers. Only `setup_admin` and `meeting_operator`
can issue remote Start/Stop. Remote command attribution uses the configured
remote staff identity; the central log additionally records the local
operator, station, channel, action and acknowledged command ID.

Catalogue sharing uses the actual published-asset endpoint
`/api/public/assets`, not the app-platform's sample catalogue. Only entries
with a publication timestamp are projected, with title, duration, timestamp
and a watch link. It returns at most 100 programmes with an explicit truncated
flag. Peer responses are limited to 1 MiB and a 12-second overall request
budget. Larger catalogues fail clearly rather than silently inventing a
complete result. Refresh the peer directly when this limit is reached.

This workflow shares catalogue/watch references and central channel controls.
It does not copy media into another station, alter its schedule or configuration,
or assert that an acknowledged command executed. The configured trust
relationship is established by the station administrator, not by automatic
peer discovery.

## Development verification

Initial endpoint RED on the existing actual application:
`.venv/Scripts/python.exe -m pytest tests/federation/test_federation.py -q --tb=short`
returned `1 failed in 3.94s` because the station-list endpoint returned 404
instead of 200. This was before the implementation and application wiring.

The same focused module now exercises two real `create_app()` ASGI instances:
one central console and one peer. Requests cross the HTTP client/ASGI transport
boundary and use the peer's existing public catalogue, bearer authentication,
role checks, egress store and command queue. The check confirms published-only
catalogue links, no credential on public requests, remote credential identity,
restricted local roles, remote role refusal, explicit Stop confirmation,
fixed actions and managed channels, and queue acknowledgement while the
remote state remains STOPPED. Additional checks cover rejected unsafe origins,
redirect refusal, response-size limits, malformed data, remote refusal/timeout,
sanitized error messages and no network requests for unknown peers or absent
credentials.

Final command:
`.venv/Scripts/python.exe -m pytest tests/federation/test_federation.py -q --tb=short`
returned `18 passed in 7.12s`. The first expanded run had three setup errors
because the test configuration omitted a required slate message; the next
had three test errors from naming the existing queue reader incorrectly.
Those fixture errors were corrected without weakening product assertions.

The tests use local ASGI transport and in-memory stores. They do not claim a
deployed cross-machine HTTPS connection, certificate provisioning, remote
daemon execution or installed-package verification. No actual station token,
service, configuration or broadcast was changed. Existing ephemeral-app
startup logs about unset frontend distributions are expected for these API
fixtures; they do not establish installed UI behavior.

Independent source review found no material backend defect. Scoped Python
lint/format checks passed. Receipt: `proved: focused ASGI API module 18 passed
· lane: Critical` (remote authentication and channel commands).

# CivicCast Reference CTV Prototype

This is the v1.6 software reference client for connected-TV feed work. It is a
small browser-based prototype that consumes the public CivicCast CTV feed and
renders live channels plus VOD items with stable content IDs.

## Run

Open `index.html` directly, or serve this folder with any static file server.
By default it reads `/api/public/channels/ctv/feed`. For local testing against a
different API, add a `feed` query parameter:

```text
index.html?feed=http://127.0.0.1:8000/api/public/channels/ctv/feed
```

## Boundary

This prototype proves the public feed contract and UI behavior. It does not
claim Roku Channel Store publication, DRM readiness, remote-control certification,
Comcast/headend delivery, or hardware output compatibility.

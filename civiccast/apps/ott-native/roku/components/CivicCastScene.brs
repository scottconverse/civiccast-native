' SPDX-License-Identifier: Apache-2.0
' Copyright (c) The CivicCast Authors
'
' Behaviour script for the CivicCastScene SceneGraph component.
'
' init() runs once at component construction; we wire up the channel-list
' onItemSelected handler, kick off the config fetch on a urlTransfer task
' so the UI thread stays responsive, and observe the video node's state
' so we can hide it cleanly when playback ends.
'
' Real CivicCast app-platform contract (civiccast/app_platform/models.py):
'   1. GET <API_BASE_URL>/api/public/app/config -> StationAppConfig
'      { "station_name": "...", "default_channel_id": "...",
'        "channels": [ { "channel_id": "...", "branding":
'        { "display_name": "..." }, "live_state_url": "/api/public/app/
'        channels/<id>/live" } ] }
'   2. GET <API_BASE_URL><channel.live_state_url> -> LiveState
'      { "state": "on_air"|"off_air"|"fallback", "playback_url": "https://
'        .../index.m3u8" | invalid, "title": "...", "fallback_reason": "..." }
' `live_state_url` is a path relative to API_BASE_URL, not an absolute URL —
' resolve it before fetching. `playback_url` is the HLS manifest handed
' directly to the Video node.

' --- Defaults / config ------------------------------------------------------

' The configured CivicCast public API base. In production this is overridden
' by Roku's "channel config" — for the starter, we ship a placeholder. See
' README.md for how the station administrator overrides it.
'
' A function, not a top-level `const` — plain BrightScript (as opposed to
' the BrighterScript superset) does not support top-level const
' declarations. This file is shipped as standard .brs and sideloaded as-is.
function getApiBaseUrl() as String
    return "https://civiccast.example.com"
end function

' --- Lifecycle --------------------------------------------------------------

sub init()
    m.channels = []
    m.statusLabel = m.top.findNode("statusLabel")
    m.channelList = m.top.findNode("channelList")
    m.video = m.top.findNode("videoPlayer")

    m.channelList.observeField("itemSelected", "onChannelSelected")
    m.video.observeField("state", "onVideoStateChanged")

    fetchConfig()
end sub

' --- Channel-list fetch -----------------------------------------------------

sub fetchConfig()
    body = getJson(getApiBaseUrl() + "/api/public/app/config")
    if body = invalid then
        showEmptyState("Could not reach the CivicCast public API. Check network access and the station's API URL, then retry.")
        return
    end if

    parsed = parseJson(body)
    if parsed = invalid or not isAssocArray(parsed) then
        showEmptyState("Malformed config response. Check the CivicCast public API, then retry.")
        return
    end if

    ' Update station identity.
    stationLabel = m.top.findNode("stationNameLabel")
    if parsed.station_name <> invalid then stationLabel.text = parsed.station_name

    ' Pull channels[] from StationAppConfig. Each entry has branding.display_name
    ' + live_state_url (the live playback_url is resolved separately, per
    ' channel, on selection — see fetchLiveStateAndPlay()).
    rawChannels = parsed.channels
    if rawChannels = invalid or rawChannels.count() = 0 then
        showEmptyState("No channels are configured yet. Finish station setup in the operator console, then retry.")
        return
    end if

    m.channels = []
    for each entry in rawChannels
        title = "(unnamed)"
        if entry.branding <> invalid and entry.branding.display_name <> invalid and entry.branding.display_name <> "" then
            title = entry.branding.display_name
        end if
        liveStateUrl = entry.live_state_url
        if liveStateUrl = invalid then liveStateUrl = ""
        m.channels.push({ title: title, live_state_url: liveStateUrl })
    end for

    renderChannels("")
end sub

sub showEmptyState(reason as String)
    m.channels = [{ title: "No channels configured", live_state_url: "" }]
    renderChannels(reason)
end sub

sub renderChannels(statusText as String)
    contentNode = CreateObject("roSGNode", "ContentNode")
    for each ch in m.channels
        row = contentNode.CreateChild("ContentNode")
        row.title = ch.title
    end for
    m.channelList.content = contentNode

    if statusText = "" then
        m.statusLabel.visible = false
    else
        m.statusLabel.text = statusText
        m.statusLabel.visible = true
    end if

    m.channelList.setFocus(true)
end sub

' --- Selection / playback ---------------------------------------------------

sub onChannelSelected()
    idx = m.channelList.itemSelected
    if idx < 0 or idx >= m.channels.count() then return
    ch = m.channels[idx]
    if ch.live_state_url = "" then
        m.statusLabel.text = ch.title + ": no live-state URL configured."
        m.statusLabel.visible = true
        return
    end if

    fetchLiveStateAndPlay(ch)
end sub

' Fetches LiveState for the selected channel and starts playback of
' playback_url. This is a second, per-channel request — the config response
' only carries the URL to fetch it from, not the HLS URL itself.
sub fetchLiveStateAndPlay(ch as Object)
    m.statusLabel.text = ch.title + ": loading stream…"
    m.statusLabel.visible = true

    url = resolveUrl(ch.live_state_url)
    body = getJson(url)
    if body = invalid then
        m.statusLabel.text = ch.title + ": could not reach live-state endpoint."
        return
    end if

    live = parseJson(body)
    if live = invalid or not isAssocArray(live) then
        m.statusLabel.text = ch.title + ": malformed live-state response."
        return
    end if

    playbackUrl = live.playback_url
    if playbackUrl = invalid or playbackUrl = "" then
        state = live.state
        if state = invalid then state = "unknown"
        reason = live.fallback_reason
        if reason = invalid then reason = live.title
        if reason = invalid then reason = "no active program"
        m.statusLabel.text = ch.title + ": " + state + " (" + reason + ")"
        return
    end if

    content = CreateObject("roSGNode", "ContentNode")
    content.url = playbackUrl
    content.streamFormat = "hls"
    content.title = ch.title

    m.statusLabel.visible = false
    m.video.content = content
    m.video.visible = true
    m.video.translation = [0, 0]
    m.video.width = 1920
    m.video.height = 1080
    m.video.control = "play"
    m.video.setFocus(true)
end sub

sub onVideoStateChanged()
    state = m.video.state
    ' Roku video states: none / buffering / playing / paused / stopped /
    ' finished / error. Return to the list when the video ends or errors.
    if state = "finished" or state = "error" or state = "stopped" then
        m.video.visible = false
        m.channelList.setFocus(true)
    end if
end sub

' --- Helpers ----------------------------------------------------------------

' Synchronous GET returning the response body string, or invalid on any
' transport/HTTP failure. Used for both the config and live-state fetches.
function getJson(url as String) as Dynamic
    port = CreateObject("roMessagePort")
    xfer = CreateObject("roUrlTransfer")
    xfer.setMessagePort(port)
    xfer.setUrl(url)
    xfer.AddHeader("Accept", "application/json")

    ok = xfer.AsyncGetToString()
    if not ok then return invalid

    msg = wait(5000, port)
    if type(msg) <> "roUrlEvent" then return invalid
    if msg.GetResponseCode() <> 200 then return invalid

    return msg.GetString()
end function

' `live_state_url` is a path relative to API_BASE_URL (e.g.
' "/api/public/app/channels/public/live"), not an absolute URL.
function resolveUrl(path as String) as String
    if Left(path, 4) = "http" then return path
    base = getApiBaseUrl()
    if Right(base, 1) = "/" then base = Left(base, Len(base) - 1)
    if Left(path, 1) <> "/" then path = "/" + path
    return base + path
end function

function isAssocArray(v as Dynamic) as Boolean
    return type(v) = "roAssociativeArray" or type(v) = "Object"
end function

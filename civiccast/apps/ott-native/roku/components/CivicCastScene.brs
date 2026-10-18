' SPDX-License-Identifier: Apache-2.0
' Copyright (c) The CivicCast Authors
'
' Behaviour script for the CivicCastScene SceneGraph component.
'
' init() runs once at component construction; we wire up the channel-list
' onItemSelected handler, fetch the station catalog, and observe the video node's state
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

' The configured CivicCast public API base, persisted from Station address.
' The example host is only the initial value before station setup.
'
' A function, not a top-level `const` — plain BrightScript (as opposed to
' the BrighterScript superset) does not support top-level const
' declarations. This file is shipped as standard .brs and sideloaded as-is.
function getApiBaseUrl() as String
    settings = CreateObject("roRegistrySection", "CivicCast")
    saved = settings.read("apiBaseUrl")
    if saved <> invalid and saved <> "" then return saved
    return "https://civiccast.example.com"
end function

' --- Lifecycle --------------------------------------------------------------

sub init()
    m.channels = []
    m.replays = []
    m.catalogReady = false
    m.pendingLaunchArgs = invalid
    m.statusLabel = m.top.findNode("statusLabel")
    m.channelList = m.top.findNode("channelList")
    m.artwork = m.top.findNode("artwork")
    m.video = m.top.findNode("videoPlayer")

    m.channelList.observeField("itemSelected", "onChannelSelected")
    m.channelList.observeField("itemFocused", "onItemFocused")
    m.video.observeField("state", "onVideoStateChanged")

    fetchConfig()
end sub

' --- Channel-list fetch -----------------------------------------------------

sub fetchConfig()
    m.catalogReady = false
    m.replays = []
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
        logoUrl = invalid
        if entry.branding <> invalid then logoUrl = entry.branding.logo_url
        m.channels.push({ title: title, channel_id: entry.channel_id, live_state_url: liveStateUrl, poster_url: logoUrl })
    end for

    fetchReplays()
    renderChannels("")
    m.catalogReady = true
    openDeepLink()
end sub

sub onLaunchArgsChanged()
    m.pendingLaunchArgs = m.top.launchArgs
    openDeepLink()
end sub

sub openDeepLink()
    if m.catalogReady <> true then return
    args = m.pendingLaunchArgs
    if args = invalid or not isAssocArray(args) then return
    ' Consume once, including an unknown id, so a catalog refresh cannot replay it.
    m.pendingLaunchArgs = invalid
    target = args.contentid
    if target = invalid or target = "" then return
    for each replay in m.replays
        if replay.item_id = target then
            playStream(replay.title, replay.playback_url)
            return
        end if
    end for
    for each channel in m.channels
        if channel.channel_id = target then
            fetchLiveStateAndPlay(channel)
            return
        end if
    end for
end sub

sub fetchReplays()
    body = getJson(getApiBaseUrl() + "/api/public/assets")
    if body = invalid then return
    assets = parseJson(body)
    if assets = invalid or not isArray(assets) then return
    for each asset in assets
        if asset.asset_id <> invalid and asset.title <> invalid and asset.manifest_url <> invalid then
            m.replays.push({ title: asset.title, item_id: asset.asset_id, playback_url: asset.manifest_url, poster_url: asset.poster_url })
        end if
    end for
end sub

sub showEmptyState(reason as String)
    m.channels = [{ title: "No channels configured", live_state_url: "" }]
    renderChannels(reason)
end sub

sub renderChannels(statusText as String)
    contentNode = CreateObject("roSGNode", "ContentNode")
    m.items = []
    for each ch in m.channels
        row = contentNode.CreateChild("ContentNode")
        row.title = ch.title
        m.items.push(ch)
    end for
    for each replay in m.replays
        row = contentNode.CreateChild("ContentNode")
        row.title = "Replay: " + replay.title
        m.items.push(replay)
    end for
    m.channelList.content = contentNode
    onItemFocused()

    if statusText = "" then
        m.statusLabel.visible = false
    else
        m.statusLabel.text = statusText
        m.statusLabel.visible = true
    end if

    m.channelList.setFocus(true)
end sub

sub onItemFocused()
    idx = m.channelList.itemFocused
    m.artwork.visible = false
    if idx = invalid then return
    if idx < 0 or idx >= m.items.count() then return
    imageUrl = m.items[idx].poster_url
    if imageUrl = invalid or imageUrl = "" then return
    m.artwork.uri = resolveUrl(imageUrl)
    m.artwork.visible = true
end sub

' --- Selection / playback ---------------------------------------------------

sub onChannelSelected()
    idx = m.channelList.itemSelected
    if idx < 0 or idx >= m.items.count() then return
    ch = m.items[idx]
    if ch.playback_url <> invalid then
        playStream(ch.title, ch.playback_url)
        return
    end if
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

    playStream(ch.title, playbackUrl)
end sub

sub playStream(title as String, playbackUrl as String)
    content = CreateObject("roSGNode", "ContentNode")
    content.url = resolveUrl(playbackUrl)
    content.streamFormat = "hls"
    content.title = title

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

function onKeyEvent(key as String, press as Boolean) as Boolean
    ' Keep Roku's native player options (including captions and audio) available.
    if m.video.visible then return false
    if press and key = "options" then
        menu = CreateObject("roSGNode", "Dialog")
        menu.title = "CivicCast options"
        menu.buttons = ["Search", "Station address", "Cancel"]
        menu.observeField("buttonSelected", "onOptionsSelected")
        m.top.dialog = menu
        return true
    end if
    return false
end function

sub onOptionsSelected()
    selected = m.top.dialog.buttonSelected
    m.top.dialog = invalid
    if selected = 0 then
        openKeyboard("Search channels and replays", "search")
    else if selected = 1 then
        openKeyboard("Station API address", "station")
    end if
end sub

sub openKeyboard(title as String, purpose as String)
    m.keyboardPurpose = purpose
    keyboard = CreateObject("roSGNode", "KeyboardDialog")
    keyboard.title = title
    keyboard.buttons = ["OK", "Cancel"]
    if purpose = "station" then keyboard.text = getApiBaseUrl()
    keyboard.observeField("buttonSelected", "onKeyboardSelected")
    m.top.dialog = keyboard
end sub

sub onKeyboardSelected()
    keyboard = m.top.dialog
    selected = keyboard.buttonSelected
    value = keyboard.text
    m.top.dialog = invalid
    if selected <> 0 then return
    if m.keyboardPurpose = "station" then
        if Left(value, 8) <> "https://" then
            m.statusLabel.text = "Enter the full HTTPS station address."
            m.statusLabel.visible = true
            return
        end if
        settings = CreateObject("roRegistrySection", "CivicCast")
        settings.write("apiBaseUrl", value)
        settings.flush()
        fetchConfig()
    else
        renderSearch(value)
    end if
end sub

sub renderSearch(query as String)
    contentNode = CreateObject("roSGNode", "ContentNode")
    m.items = []
    lowerQuery = LCase(query)
    for each channel in m.channels
        if Instr(1, LCase(channel.title), lowerQuery) > 0 then
            row = contentNode.CreateChild("ContentNode")
            row.title = channel.title
            m.items.push(channel)
        end if
    end for
    for each replay in m.replays
        if Instr(1, LCase(replay.title), lowerQuery) > 0 then
            row = contentNode.CreateChild("ContentNode")
            row.title = "Replay: " + replay.title
            m.items.push(replay)
        end if
    end for
    m.channelList.content = contentNode
    m.channelList.setFocus(true)
    m.statusLabel.text = "Search: " + query
    m.statusLabel.visible = true
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

function isArray(v as Dynamic) as Boolean
    return type(v) = "roArray"
end function

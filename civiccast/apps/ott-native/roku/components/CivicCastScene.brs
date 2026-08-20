' SPDX-License-Identifier: Apache-2.0
' Copyright (c) The CivicCast Authors
'
' Behaviour script for the CivicCastScene SceneGraph component.
'
' init() runs once at component construction; we wire up the channel-list
' onItemSelected handler, kick off the config fetch on a urlTransfer task
' so the UI thread stays responsive, and observe the video node's state
' so we can hide it cleanly when playback ends.

' --- Defaults / config ------------------------------------------------------

' The configured CivicCast public API base. In production this is overridden
' by Roku's "channel config" — for the starter, we ship a placeholder. See
' README.md for how the station administrator overrides it.
const API_BASE_URL = "https://civiccast.example.com"

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
    ' We launch the network request on a Task-style node — Roku's standard
    ' pattern for async HTTP that keeps the UI thread alive. For brevity the
    ' starter ships an inline xfer; production replaces this with a proper
    ' ConfigFetchTask.brs running on its own thread.
    port = CreateObject("roMessagePort")
    xfer = CreateObject("roUrlTransfer")
    xfer.setMessagePort(port)
    xfer.setUrl(API_BASE_URL + "/api/public/app/config")
    xfer.AddHeader("Accept", "application/json")

    ok = xfer.AsyncGetToString()
    if not ok then
        showEmptyState("Could not start network request. Check the CivicCast public API URL, then retry.")
        return
    end if

    msg = wait(5000, port)
    if type(msg) <> "roUrlEvent" then
        showEmptyState("Network request timed out. Check network access to the CivicCast public API, then retry.")
        return
    end if

    if msg.GetResponseCode() <> 200 then
        showEmptyState("API returned " + msg.GetResponseCode().toStr() + ". Check station setup, then retry.")
        return
    end if

    body = msg.GetString()
    parsed = parseJson(body)
    if parsed = invalid or not isAssocArray(parsed) then
        showEmptyState("Malformed config response. Check the CivicCast public API, then retry.")
        return
    end if

    ' Update station identity.
    stationLabel = m.top.findNode("stationNameLabel")
    if parsed.station_name <> invalid then stationLabel.text = parsed.station_name

    ' Pull channels[] from config. Each entry is expected to have title + hls_url;
    ' missing or empty array becomes an explicit setup state, not fake content.
    rawChannels = parsed.channels
    if rawChannels = invalid or rawChannels.count() = 0 then
        showEmptyState("No channels are configured yet. Finish station setup in the operator console, then retry.")
        return
    end if

    m.channels = []
    for each entry in rawChannels
        title = entry.title
        url = entry.hls_url
        if title = invalid or title = "" then title = "(unnamed)"
        if url = invalid or url = "" then url = ""
        m.channels.push({ title: title, hls_url: url })
    end for

    renderChannels("")
end sub

sub showEmptyState(reason as String)
    m.channels = [{ title: "No channels configured", hls_url: "" }]
    renderChannels(reason)
end sub

sub renderChannels(statusText as String)
    contentNode = CreateObject("roSGNode", "ContentNode")
    for each ch in m.channels
        row = contentNode.CreateChild("ContentNode")
        row.title = ch.title
        row.streamUrls = [ch.hls_url]
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
    if ch.hls_url = "" then
        m.statusLabel.text = ch.title + ": no stream URL configured."
        m.statusLabel.visible = true
        return
    end if

    content = CreateObject("roSGNode", "ContentNode")
    content.url = ch.hls_url
    content.streamFormat = "hls"
    content.title = ch.title

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

function isAssocArray(v as Dynamic) as Boolean
    return type(v) = "roAssociativeArray" or type(v) = "Object"
end function

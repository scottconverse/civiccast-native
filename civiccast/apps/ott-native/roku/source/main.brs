' SPDX-License-Identifier: Apache-2.0
' Copyright (c) The CivicCast Authors
'
' Entry point for the CivicCast Roku channel.
'
' Roku boots a channel by calling Main(args as Dynamic). The standard pattern
' is to create a Scene + screen, hand control to it, and block on a
' MessagePort until the user backs all the way out. We follow that pattern
' verbatim — the actual UI lives in the SceneGraph XML under components/.
'
' See README.md for the build + sideload story.

sub Main(args as Dynamic)
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.setMessagePort(port)

    ' Pass any launch args (Roku passes the contentId, mediaType, source from
    ' deep-link suspends here) into the Scene so the supports_input_launch=1
    ' wiring in the manifest is honored.
    scene = screen.CreateScene("CivicCastScene")
    scene.launchArgs = args
    screen.show()

    while true
        msg = wait(0, port)
        msgType = type(msg)
        if msgType = "roSGScreenEvent"
            if msg.isScreenClosed() then return
        end if
    end while
end sub

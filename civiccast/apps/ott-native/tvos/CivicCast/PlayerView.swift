// PlayerView.swift — tvOS AVPlayer view.
//
// VideoPlayer on tvOS uses the platform's full-screen transport
// controls automatically (Siri Remote scrub, AirPlay, captions).

import SwiftUI
import AVKit

struct PlayerView: View {
    let channel: Channel

    @State private var player: AVPlayer?

    var body: some View {
        Group {
            if let player {
                VideoPlayer(player: player)
                    .ignoresSafeArea()
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else {
                ProgressView("Preparing stream…")
                    .controlSize(.large)
            }
        }
        .task {
            if let url = channel.hlsURL {
                let asset = AVURLAsset(url: url)
                let item = AVPlayerItem(asset: asset)
                player = AVPlayer(playerItem: item)
            }
        }
    }
}

// PlayerView.swift
//
// AVPlayer-backed HLS playback. AVPlayer has native HLS support so
// no third-party player is needed; the same code works on tvOS.

import SwiftUI
import AVKit

struct PlayerView: View {
    let channel: Channel

    @State private var player: AVPlayer?

    var body: some View {
        Group {
            if let player {
                VideoPlayer(player: player)
                    .ignoresSafeArea(edges: .bottom)
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else {
                ProgressView("Preparing stream…")
            }
        }
        .navigationTitle(channel.name)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if let url = channel.hlsURL {
                let asset = AVURLAsset(url: url)
                let item = AVPlayerItem(asset: asset)
                player = AVPlayer(playerItem: item)
            }
        }
    }
}

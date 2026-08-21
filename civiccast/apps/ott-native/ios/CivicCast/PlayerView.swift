// PlayerView.swift
//
// AVPlayer-backed HLS playback. AVPlayer has native HLS support so
// no third-party player is needed; the same code works on tvOS.
//
// Fetches the channel's LiveState (`GET <live_state_url>`) to resolve
// `playback_url` — the real backend contract, not a flat hlsUrl field.

import SwiftUI
import AVKit

struct PlayerView: View {
    let channel: Channel

    @EnvironmentObject private var store: ConfigStore
    @State private var player: AVPlayer?
    @State private var status: String?

    var body: some View {
        Group {
            if let player {
                VideoPlayer(player: player)
                    .ignoresSafeArea(edges: .bottom)
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else {
                VStack(spacing: 12) {
                    ProgressView("Preparing stream…")
                    if let status {
                        Text(status)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                    }
                }
            }
        }
        .navigationTitle(channel.branding.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await loadAndPlay()
        }
    }

    private func loadAndPlay() async {
        do {
            let live = try await store.client.fetchLiveState(channel.liveStateUrl)
            guard let url = live.playbackURL else {
                status = live.summary
                return
            }
            let asset = AVURLAsset(url: url)
            let item = AVPlayerItem(asset: asset)
            player = AVPlayer(playerItem: item)
        } catch {
            status = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

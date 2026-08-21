// PlayerView.swift — tvOS AVPlayer view.
//
// VideoPlayer on tvOS uses the platform's full-screen transport
// controls automatically (Siri Remote scrub, AirPlay, captions).
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
                    .ignoresSafeArea()
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else {
                VStack(spacing: 16) {
                    ProgressView("Preparing stream…")
                        .controlSize(.large)
                    if let status {
                        Text(status)
                            .font(.title3)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 80)
                    }
                }
            }
        }
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

// PlayerView.swift
//
// AVPlayerViewController-backed HLS playback. AVPlayer has native HLS support so
// no third-party player is needed; the same code works on tvOS.
//
// Fetches the channel's LiveState (`GET <live_state_url>`) to resolve
// `playback_url` — the real backend contract, not a flat hlsUrl field.

import SwiftUI
import AVKit

/// AVKit exposes the platform's audio-language, caption, AirPlay and PiP controls.
private struct SystemPlayerView: UIViewControllerRepresentable {
    let player: AVPlayer

    func makeUIViewController(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        controller.player = player
        controller.showsPlaybackControls = true
        controller.allowsPictureInPicturePlayback = true
        return controller
    }

    func updateUIViewController(_ controller: AVPlayerViewController, context: Context) {
        controller.player = player
    }
}

struct PlayerView: View {
    let channel: Channel?
    let replay: PublishedAsset?

    init(channel: Channel) {
        self.channel = channel
        self.replay = nil
    }

    init(replay: PublishedAsset) {
        self.channel = nil
        self.replay = replay
    }

    @EnvironmentObject private var store: ConfigStore
    @State private var player: AVPlayer?
    @State private var status: String?

    var body: some View {
        Group {
            if let player {
                SystemPlayerView(player: player)
                    .ignoresSafeArea(edges: .bottom)
                    .onAppear { player.play() }
                    .onDisappear { player.pause() }
            } else {
                VStack(spacing: 12) {
                    if status == nil { ProgressView("Preparing stream…") }
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
        .navigationTitle(channel?.branding.displayName ?? replay?.title ?? "CivicCast")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await loadAndPlay()
        }
    }

    private func loadAndPlay() async {
        do {
            let url: URL
            if let replay, let replayURL = store.client.mediaURL(replay.manifestUrl) {
                url = replayURL
            } else if let channel {
                let live = try await store.client.fetchLiveState(channel.liveStateUrl)
                guard let liveURL = live.playbackUrl.flatMap(store.client.mediaURL) else {
                    status = live.summary
                    return
                }
                url = liveURL
            } else {
                status = "This replay has no playback URL."
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

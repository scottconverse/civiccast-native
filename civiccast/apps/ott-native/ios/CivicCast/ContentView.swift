// ContentView.swift
//
// iOS channel list. Tap a row to push the AVPlayer view. Reads the real
// `StationAppConfig` contract via CivicCastCore's NetworkClient/ConfigStore
// (station_name / channels[].branding.display_name / channels[].live_state_url).

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var store: ConfigStore

    var body: some View {
        NavigationStack {
            Group {
                switch store.state {
                case .idle, .loading:
                    ProgressView("Loading station…")
                        .controlSize(.large)
                case .error(let message):
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 48))
                            .foregroundStyle(.orange)
                        Text("Could not load station")
                            .font(.headline)
                        Text(message)
                            .font(.subheadline)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal)
                        Button("Retry") {
                            Task { await store.load() }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                case .loaded(let config):
                    StationView(config: config)
                }
            }
            .navigationTitle("CivicCast")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

private struct StationView: View {
    let config: ConfigResponse

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    Text(config.stationName)
                        .font(.title2.bold())
                    Text("\(config.channels.count) channel\(config.channels.count == 1 ? "" : "s")")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            }
            Section("Channels") {
                ForEach(config.channels) { channel in
                    NavigationLink(value: channel) {
                        ChannelRow(channel: channel)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationDestination(for: Channel.self) { channel in
            PlayerView(channel: channel)
        }
    }
}

private struct ChannelRow: View {
    let channel: Channel

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 6)
                .fill(brandColor.opacity(0.15))
                .frame(width: 56, height: 32)
                .overlay(
                    Image(systemName: "tv")
                        .foregroundStyle(brandColor)
                )
            VStack(alignment: .leading, spacing: 2) {
                Text(channel.branding.displayName)
                    .font(.body)
                Text(channel.branding.shortName ?? channel.id)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private var brandColor: Color {
        Color(hex: channel.branding.color) ?? .accentColor
    }
}

#Preview {
    let preview = ConfigStore()
    return ContentView()
        .environmentObject(preview)
}

// ContentView.swift
//
// iOS channel list. Tap a row to push the AVPlayer view. Reads the real
// `StationAppConfig` contract via CivicCastCore's NetworkClient/ConfigStore
// (station_name / channels[].branding.display_name / channels[].live_state_url).

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var store: ConfigStore
    @State private var path = NavigationPath()
    @State private var showStationSettings = false

    var body: some View {
        NavigationStack(path: $path) {
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
        .onReceive(store.$pendingLink) { link in openPendingLink(link, state: store.state) }
        .onReceive(store.$state) { state in openPendingLink(store.pendingLink, state: state) }
        .onReceive(store.$stationAddress) { _ in path = NavigationPath() }
        .toolbar { Button("Station") { showStationSettings = true } }
        .sheet(isPresented: $showStationSettings) {
            StationSettingsView().environmentObject(store)
        }
    }

    private func openPendingLink(_ link: AppDeepLink?, state: ConfigStore.State) {
        guard case .loaded(let config) = state, let link else { return }
        switch link {
        case .channel(let id):
            guard let channel = config.channels.first(where: { $0.id == id }) else { return }
            path.append(channel)
        case .replay(let id):
            guard let replay = store.replays.first(where: { $0.id == id }) else { return }
            path.append(replay)
        }
        store.pendingLink = nil
    }
}

private struct StationView: View {
    let config: ConfigResponse
    @EnvironmentObject private var store: ConfigStore
    @State private var search = ""

    private var filteredReplays: [PublishedAsset] {
        guard !search.isEmpty else { return store.replays }
        return store.replays.filter {
            $0.title.localizedCaseInsensitiveContains(search)
                || ($0.description?.localizedCaseInsensitiveContains(search) ?? false)
        }
    }

    private var filteredChannels: [Channel] {
        guard !search.isEmpty else { return config.channels }
        return config.channels.filter {
            $0.branding.displayName.localizedCaseInsensitiveContains(search)
                || ($0.branding.shortName?.localizedCaseInsensitiveContains(search) ?? false)
        }
    }

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
                ForEach(filteredChannels) { channel in
                    NavigationLink(value: channel) {
                        ChannelRow(channel: channel)
                    }
                }
            }
            Section("Published station replays") {
                ForEach(filteredReplays) { replay in
                    NavigationLink(value: replay) {
                        HStack {
                            if let poster = replay.posterUrl,
                               let url = store.client.mediaURL(poster) {
                                AsyncImage(url: url) { image in
                                    image.resizable().scaledToFill()
                                } placeholder: {
                                    Color.secondary.opacity(0.15)
                                }
                                .frame(width: 80, height: 45)
                                .clipped()
                                .accessibilityHidden(true)
                            }
                            Text(replay.title)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .searchable(text: $search, prompt: "Search channels and replays")
        .navigationDestination(for: Channel.self) { channel in
            PlayerView(channel: channel)
        }
        .navigationDestination(for: PublishedAsset.self) { replay in
            PlayerView(replay: replay)
        }
    }
}

private struct ChannelRow: View {
    let channel: Channel
    @EnvironmentObject private var store: ConfigStore

    var body: some View {
        HStack(spacing: 12) {
            if let logo = channel.branding.logoUrl,
               let url = store.client.mediaURL(logo) {
                AsyncImage(url: url) { image in
                    image.resizable().scaledToFit()
                } placeholder: {
                    Color.secondary.opacity(0.15)
                }
                .frame(width: 56, height: 32)
                .accessibilityHidden(true)
            } else {
                RoundedRectangle(cornerRadius: 6)
                    .fill(brandColor.opacity(0.15))
                    .frame(width: 56, height: 32)
                    .overlay(Image(systemName: "tv").foregroundStyle(brandColor))
                    .accessibilityHidden(true)
            }
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

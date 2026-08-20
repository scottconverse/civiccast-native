// ContentView.swift — tvOS channel browser.
//
// tvOS focus-engine notes:
// - We use NavigationStack + a List of rows; `List` rows are
//   focusable by default on tvOS, so an explicit `.focusable()`
//   isn't required for the rows themselves. We use `.buttonStyle(.card)`
//   on the channel rows to get the canonical tvOS card highlight on
//   focus. `.focusEffectDisabled(false)` is the default — listed here
//   only so a future cleanup can grep for it.
// - The "Retry" button uses `.borderedProminent` which works on tvOS
//   with the focus-engine outline.

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
                    VStack(spacing: 24) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 80))
                            .foregroundStyle(.orange)
                        Text("Could not load station")
                            .font(.title)
                        Text(message)
                            .font(.title3)
                            .multilineTextAlignment(.center)
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 80)
                        Button("Retry") {
                            Task { await store.load() }
                        }
                        .buttonStyle(.borderedProminent)
                        .focusable()
                    }
                case .loaded(let config):
                    StationView(config: config)
                }
            }
        }
    }
}

private struct StationView: View {
    let config: ConfigResponse

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 4) {
                Text(config.station.name)
                    .font(.largeTitle.bold())
                Text("\(config.channels.count) channel\(config.channels.count == 1 ? "" : "s")")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 80)
            .padding(.top, 60)

            ScrollView {
                LazyVStack(spacing: 24) {
                    ForEach(config.channels) { channel in
                        NavigationLink(value: channel) {
                            ChannelCard(channel: channel)
                        }
                        .buttonStyle(.card)
                        // .focusEffectDisabled(false) is the default;
                        // listed in the file header as a search anchor.
                    }
                }
                .padding(.horizontal, 80)
                .padding(.bottom, 60)
            }
        }
        .navigationDestination(for: Channel.self) { channel in
            PlayerView(channel: channel)
        }
    }
}

private struct ChannelCard: View {
    let channel: Channel

    var body: some View {
        HStack(spacing: 24) {
            RoundedRectangle(cornerRadius: 12)
                .fill(.tint.opacity(0.20))
                .frame(width: 220, height: 124)
                .overlay(
                    Image(systemName: "tv")
                        .font(.system(size: 56))
                        .foregroundStyle(.tint)
                )
            VStack(alignment: .leading, spacing: 8) {
                Text(channel.name)
                    .font(.title2)
                Text(channel.id)
                    .font(.body)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

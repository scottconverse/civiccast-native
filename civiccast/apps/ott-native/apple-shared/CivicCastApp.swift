// CivicCastApp.swift
//
// Shared app entry point (SwiftUI @main + ConfigStore) for both the iOS
// and tvOS targets. Single canonical copy — see CivicCastCore.swift's
// header for the file-sharing rationale. ContentView() and PlayerView()
// are resolved per-target (each target supplies its own).

import SwiftUI

@main
struct CivicCastApp: App {
    @StateObject private var store = ConfigStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .onOpenURL { url in
                    store.pendingLink = AppDeepLink(url: url)
                }
                .task {
                    await store.load()
                }
        }
    }
}

/// Observable wrapper around the API client. Splits "loading", "loaded",
/// "error" so SwiftUI can render the three states explicitly.
@MainActor
final class ConfigStore: ObservableObject {
    private static let stationURLKey = "CivicCastStationURL"
    enum State {
        case idle
        case loading
        case loaded(ConfigResponse)
        case error(String)
    }

    @Published var state: State = .idle
    @Published var replays: [PublishedAsset] = []
    @Published var pendingLink: AppDeepLink?
    @Published var stationAddress: String =
        UserDefaults.standard.string(forKey: stationURLKey)
        ?? (Bundle.main.object(forInfoDictionaryKey: "APIBaseURL") as? String)
        ?? ""

    var client: NetworkClient {
        NetworkClient(baseURL: URL(string: stationAddress) ?? URL(string: "https://civiccast.example.com")!)
    }

    func setStationAddress(_ address: String) async throws {
        let value = address.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: value), url.scheme == "https", url.host != nil,
              url.path.isEmpty, url.query == nil, url.fragment == nil,
              url.user == nil, url.password == nil else {
            throw NetworkError.badURL
        }
        UserDefaults.standard.set(value, forKey: Self.stationURLKey)
        stationAddress = value
        await load()
    }

    func load() async {
        state = .loading
        do {
            let config = try await client.fetchConfig()
            replays = (try? await client.fetchPublishedAssets()) ?? []
            state = .loaded(config)
        } catch {
            state = .error((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

enum AppDeepLink: Equatable {
    case channel(String)
    case replay(String)

    init?(url: URL) {
        guard url.scheme == "civiccast", url.pathComponents.count == 2 else { return nil }
        let identifier = url.pathComponents[1]
        guard !identifier.isEmpty else { return nil }
        switch url.host {
        case "channel": self = .channel(identifier)
        case "replay": self = .replay(identifier)
        default: return nil
        }
    }
}

struct StationSettingsView: View {
    @EnvironmentObject private var store: ConfigStore
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Station address").font(.title2.bold())
            Text("Enter the HTTPS address of your CivicCast station.")
                .foregroundStyle(.secondary)
            TextField("https://station.example.org", text: $address)
                .accessibilityLabel("CivicCast station address")
            if let error {
                Text(error).foregroundStyle(.red)
            }
            Button("Save station") {
                Task {
                    do {
                        try await store.setStationAddress(address)
                        dismiss()
                    } catch {
                        self.error = error.localizedDescription
                    }
                }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(32)
        .onAppear { address = store.stationAddress }
    }
}

// CivicCastApp.swift
//
// iOS app entry point. Swift 5.9, SwiftUI macro-based @main.

import SwiftUI

@main
struct CivicCastApp: App {
    @StateObject private var store = ConfigStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
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
    enum State {
        case idle
        case loading
        case loaded(ConfigResponse)
        case error(String)
    }

    @Published var state: State = .idle

    private let client = NetworkClient.fromBundle()

    func load() async {
        state = .loading
        do {
            let config = try await client.fetchConfig()
            state = .loaded(config)
        } catch {
            state = .error((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }
}

// CivicCastApp.swift — tvOS entry point.

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

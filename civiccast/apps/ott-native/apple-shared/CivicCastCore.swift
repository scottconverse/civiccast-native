// CivicCastCore.swift
//
// Shared model + network client for the CivicCast Apple apps (iOS/iPadOS
// and tvOS). This file is the SINGLE canonical copy — both
// ../ios/CivicCast.xcodeproj and ../tvos/CivicCast.xcodeproj reference this
// exact path via a SOURCE_ROOT-relative PBXFileReference rather than each
// keeping their own inline copy. Do not fork this file per-target; if a
// platform genuinely needs different network/model behavior, add a
// `#if os(tvOS)` branch here rather than duplicating the file.
//
// Platform-specific UI (ContentView.swift, PlayerView.swift) stays
// per-target on purpose — tvOS focus-engine layout and iOS touch layout
// are legitimately different, not duplicated code.

import Foundation

// MARK: - API contract
//
// This talks to the REAL CivicCast app-platform contract
// (`civiccast/app_platform/models.py`, `civiccast/app_platform/router.py`),
// not a simplified projection:
//
// 1. `GET <APIBaseURL>/api/public/app/config` -> StationAppConfig
//    { "station_name": "...", "default_channel_id": "...",
//      "channels": [ { "channel_id": "...", "branding": { "display_name":
//      "...", "color": "#2458A6" }, "live_state_url": "/api/public/app/
//      channels/<id>/live", ... } ] }
// 2. `GET <APIBaseURL><channel.live_state_url>` -> LiveState
//    { "state": "on_air" | "off_air" | "fallback", "playback_url":
//      "https://.../index.m3u8" | null, "title": "...",
//      "fallback_reason": "..." }
//
// `live_state_url` is a path relative to the API host, not an absolute
// URL — resolve it against `baseURL` before fetching. `playback_url` is
// the HLS manifest AVPlayer/VideoPlayer plays directly.

public struct ChannelBranding: Codable, Hashable, Sendable {
    public let displayName: String
    public let shortName: String?
    public let color: String?
    public let logoText: String?
    public let logoUrl: String?

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case shortName = "short_name"
        case color
        case logoText = "logo_text"
        case logoUrl = "logo_url"
    }
}

public struct Channel: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let branding: ChannelBranding
    public let liveStateUrl: String

    enum CodingKeys: String, CodingKey {
        case id = "channel_id"
        case branding
        case liveStateUrl = "live_state_url"
    }
}

public struct ConfigResponse: Codable, Hashable, Sendable {
    public let stationName: String
    public let defaultChannelId: String
    public let channels: [Channel]

    enum CodingKeys: String, CodingKey {
        case stationName = "station_name"
        case defaultChannelId = "default_channel_id"
        case channels
    }

    /// Mirrors `selectDefaultChannel()` in
    /// `app-platform-shells/src/shell.mjs`: prefer the configured default,
    /// fall back to the first channel.
    public var defaultChannel: Channel? {
        channels.first(where: { $0.id == defaultChannelId }) ?? channels.first
    }
}

public struct LiveState: Codable, Hashable, Sendable {
    public let state: String
    public let playbackUrl: String?
    public let title: String?
    public let fallbackReason: String?

    enum CodingKeys: String, CodingKey {
        case state
        case playbackUrl = "playback_url"
        case title
        case fallbackReason = "fallback_reason"
    }

    public var playbackURL: URL? { playbackUrl.flatMap(URL.init(string:)) }

    /// Mirrors `liveSummary()` in `app-platform-shells/src/shell.mjs`.
    public var summary: String {
        let label = state == "fallback" ? (fallbackReason ?? "fallback") : (title ?? playbackUrl ?? "no active program")
        return "\(state): \(label)"
    }
}

// MARK: - Network client

public enum NetworkError: Error, LocalizedError {
    case badURL
    case badStatus(Int)
    case decoding(Error)
    case transport(Error)
    case noChannels

    public var errorDescription: String? {
        switch self {
        case .badURL: return "API base URL is not a valid URL."
        case .badStatus(let code): return "Server returned HTTP \(code)."
        case .decoding(let err): return "Could not decode response: \(err.localizedDescription)"
        case .transport(let err): return "Network error: \(err.localizedDescription)"
        case .noChannels: return "Station config has no channels configured."
        }
    }
}

public actor NetworkClient {
    private let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    /// Reads `APIBaseURL` from the main bundle's Info.plist, falling back
    /// to https://civiccast.example.com. Call this from the app entry
    /// point so the override survives build-time configuration.
    public static func fromBundle(_ bundle: Bundle = .main) -> NetworkClient {
        let fallback = URL(string: "https://civiccast.example.com")!
        let configured = (bundle.object(forInfoDictionaryKey: "APIBaseURL") as? String)
            .flatMap(URL.init(string:))
        return NetworkClient(baseURL: configured ?? fallback)
    }

    public func fetchConfig() async throws -> ConfigResponse {
        try await getJSON(ConfigResponse.self, path: "api/public/app/config")
    }

    /// Fetches the live-playback state for a channel. `liveStateUrl` is the
    /// path returned in `Channel.liveStateUrl` (relative to `baseURL`).
    public func fetchLiveState(_ liveStateUrl: String) async throws -> LiveState {
        try await getJSON(LiveState.self, relativeTo: liveStateUrl)
    }

    /// Convenience used by the entry points: load config, resolve the
    /// default channel, and fetch its live state in one call.
    public func fetchDefaultChannelExperience() async throws -> (config: ConfigResponse, channel: Channel, live: LiveState) {
        let config = try await fetchConfig()
        guard let channel = config.defaultChannel else {
            throw NetworkError.noChannels
        }
        let live = try await fetchLiveState(channel.liveStateUrl)
        return (config, channel, live)
    }

    private func getJSON<T: Decodable>(_ type: T.Type, path: String) async throws -> T {
        let url = baseURL.appendingPathComponent(path)
        return try await getJSON(type, url: url)
    }

    private func getJSON<T: Decodable>(_ type: T.Type, relativeTo path: String) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw NetworkError.badURL
        }
        return try await getJSON(type, url: url)
    }

    private func getJSON<T: Decodable>(_ type: T.Type, url: URL) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("CivicCastNative/0.1 (Apple)", forHTTPHeaderField: "User-Agent")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw NetworkError.transport(error)
        }

        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw NetworkError.badStatus(http.statusCode)
        }

        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw NetworkError.decoding(error)
        }
    }
}

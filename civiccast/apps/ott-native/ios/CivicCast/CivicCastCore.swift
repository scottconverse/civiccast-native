// CivicCastCore.swift
//
// Shared model + network client for the CivicCast iOS app.
// Inline-copied into the tvOS target as well — see ../../README.md
// for the rationale (small shared surface, independently buildable
// variants, promote to a SwiftPM package once the surface grows).

import Foundation

// MARK: - API contract
//
// The apps call `GET <APIBaseURL>/api/public/app/config` and expect:
//
// {
//   "station": { "name": "City of Example Civic TV",
//                "logoUrl": "https://cdn.example.com/logo.png" },
//   "channels": [
//     {
//       "id": "ch1",
//       "name": "Government Channel",
//       "hlsUrl": "https://cdn.example.com/hls/ch1/master.m3u8",
//       "posterUrl": "https://cdn.example.com/posters/ch1.jpg"
//     }
//   ]
// }
//
// This is the same simplified shape consumed by the Android variants
// (android-mobile, android-tv, fire-tv) so that all native targets
// are wire-compatible. The full backend `StationAppConfig` schema is
// richer (see docs/openapi.json); a tiny projection endpoint or
// gateway maps it to this shape — see ../../README.md.

public struct Station: Codable, Hashable, Sendable {
    public let name: String
    public let logoUrl: String?

    enum CodingKeys: String, CodingKey {
        case name
        case logoUrl
    }
}

public struct Channel: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String
    public let hlsUrl: String
    public let posterUrl: String?

    public var hlsURL: URL? { URL(string: hlsUrl) }
    public var posterURL: URL? { posterUrl.flatMap(URL.init(string:)) }
}

public struct ConfigResponse: Codable, Hashable, Sendable {
    public let station: Station
    public let channels: [Channel]
}

// MARK: - Network client

public enum NetworkError: Error, LocalizedError {
    case badURL
    case badStatus(Int)
    case decoding(Error)
    case transport(Error)

    public var errorDescription: String? {
        switch self {
        case .badURL: return "API base URL is not a valid URL."
        case .badStatus(let code): return "Server returned HTTP \(code)."
        case .decoding(let err): return "Could not decode response: \(err.localizedDescription)"
        case .transport(let err): return "Network error: \(err.localizedDescription)"
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
        let url = baseURL.appendingPathComponent("api/public/app/config")
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
            let decoder = JSONDecoder()
            // The backend returns snake_case in some endpoints; the
            // app-config projection used here uses camelCase to match
            // the Android variants. Leave default key strategy.
            return try decoder.decode(ConfigResponse.self, from: data)
        } catch {
            throw NetworkError.decoding(error)
        }
    }
}

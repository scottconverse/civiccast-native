// CivicCastCore.swift
//
// Inline copy of the shared model + network client. Identical to
// ../../ios/CivicCast/CivicCastCore.swift on purpose — see the
// project README for the rationale on inline copy vs. SwiftPM package.

import Foundation

public struct Station: Codable, Hashable, Sendable {
    public let name: String
    public let logoUrl: String?
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
        request.setValue("CivicCastNative/0.1 (Apple tvOS)", forHTTPHeaderField: "User-Agent")

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
            return try JSONDecoder().decode(ConfigResponse.self, from: data)
        } catch {
            throw NetworkError.decoding(error)
        }
    }
}

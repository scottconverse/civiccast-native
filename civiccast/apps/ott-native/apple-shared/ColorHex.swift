// ColorHex.swift
//
// Shared `Color(hex:)` helper so both the iOS and tvOS ContentView can
// render `ChannelBranding.color` (a "#RRGGBB" hex string from the
// StationAppConfig contract) without a third-party dependency. Single
// canonical copy — see CivicCastCore.swift's header for the rationale.

import SwiftUI

extension Color {
    /// Parses a "#RRGGBB" or "RRGGBB" hex string. Returns nil for
    /// anything else so callers can fall back to `.accentColor`.
    init?(hex: String?) {
        guard var hex = hex?.trimmingCharacters(in: .whitespacesAndNewlines), !hex.isEmpty else {
            return nil
        }
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6, let value = UInt32(hex, radix: 16) else {
            return nil
        }
        let r = Double((value >> 16) & 0xFF) / 255
        let g = Double((value >> 8) & 0xFF) / 255
        let b = Double(value & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

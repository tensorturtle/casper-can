//  Appearance.swift
//  Typeface, weight, colour palette and light/dark override.
//
//  Kept separate from DashboardConfig: that stores *what* is displayed, this stores
//  *how it looks*. They are edited in different screens and persist under different
//  keys, so a reset of one does not disturb the other.
//
//  Read through the environment with a fallback default, so SwiftUI previews and
//  any view constructed outside the app's hierarchy still render.

import Foundation
import Observation
import SwiftUI

/// Typeface for the big numbers.
enum ValueTypeface: String, CaseIterable, Codable, Identifiable {
    case rounded
    case neutral
    case technical
    case serif

    var id: String { rawValue }

    var title: String {
        switch self {
        case .rounded: "Rounded"
        case .neutral: "Neutral"
        case .technical: "Technical"
        case .serif: "Serif"
        }
    }

    var subtitle: String {
        switch self {
        case .rounded: "SF Rounded — soft, friendly"
        case .neutral: "SF Pro — plain system face"
        case .technical: "SF Mono — instrument panel"
        case .serif: "New York — editorial"
        }
    }

    var design: Font.Design {
        switch self {
        case .rounded: .rounded
        case .neutral: .default
        case .technical: .monospaced
        case .serif: .serif
        }
    }
}

/// Stroke weight for the big numbers. Thinner reads as more instrument-like;
/// heavier is easier to catch at a glance.
enum ValueWeight: String, CaseIterable, Codable, Identifiable {
    case regular
    case medium
    case semibold
    case bold
    case heavy

    var id: String { rawValue }

    var title: String { rawValue.capitalized }

    var font: Font.Weight {
        switch self {
        case .regular: .regular
        case .medium: .medium
        case .semibold: .semibold
        case .bold: .bold
        case .heavy: .heavy
        }
    }
}

/// A colour pair: the normal gauge accent, and the "past redline" colour.
///
/// Both are defined per palette rather than hardcoding red, because a warm accent
/// needs a different warning colour to stay distinguishable — an amber gauge with
/// a red warning is far less legible than an amber gauge with a crimson one.
enum ThemePalette: String, CaseIterable, Codable, Identifiable {
    case blue
    case amber
    case teal
    case green
    case violet
    case mono

    var id: String { rawValue }

    var title: String {
        switch self {
        case .blue: "Blue"
        case .amber: "Amber"
        case .teal: "Teal"
        case .green: "Green"
        case .violet: "Violet"
        case .mono: "Monochrome"
        }
    }

    var accent: Color {
        switch self {
        case .blue: Color(red: 0.20, green: 0.55, blue: 1.00)
        case .amber: Color(red: 1.00, green: 0.70, blue: 0.15)
        case .teal: Color(red: 0.15, green: 0.78, blue: 0.78)
        case .green: Color(red: 0.30, green: 0.82, blue: 0.42)
        case .violet: Color(red: 0.65, green: 0.45, blue: 1.00)
        // Follows the foreground colour, so it inverts with light/dark.
        case .mono: .primary
        }
    }

    /// Past-redline colour. Chosen to stay separable from `accent`.
    var hot: Color {
        switch self {
        case .blue, .teal, .violet, .green: Color(red: 1.00, green: 0.27, blue: 0.23)
        // Against a warm accent, a deeper crimson reads as distinct where plain
        // red does not.
        case .amber: Color(red: 0.90, green: 0.13, blue: 0.20)
        case .mono: Color(red: 1.00, green: 0.35, blue: 0.30)
        }
    }
}

enum ColorSchemeChoice: String, CaseIterable, Codable, Identifiable {
    case system
    case dark
    case light

    var id: String { rawValue }
    var title: String { rawValue.capitalized }

    var scheme: ColorScheme? {
        switch self {
        case .system: nil
        case .dark: .dark
        case .light: .light
        }
    }
}

@Observable
final class Appearance {
    var typeface: ValueTypeface { didSet { save("appearance.typeface", typeface.rawValue) } }
    var weight: ValueWeight { didSet { save("appearance.weight", weight.rawValue) } }
    var palette: ThemePalette { didSet { save("appearance.palette", palette.rawValue) } }
    var colorScheme: ColorSchemeChoice {
        didSet { save("appearance.colorScheme", colorScheme.rawValue) }
    }

    /// Used when no `Appearance` is in the environment — previews, mainly. Also the
    /// documented default set.
    static let fallback = Appearance()

    init() {
        let defaults = UserDefaults.standard
        typeface = ValueTypeface(
            rawValue: defaults.string(forKey: "appearance.typeface") ?? ""
        ) ?? .neutral
        weight = ValueWeight(
            rawValue: defaults.string(forKey: "appearance.weight") ?? ""
        ) ?? .semibold
        palette = ThemePalette(
            rawValue: defaults.string(forKey: "appearance.palette") ?? ""
        ) ?? .blue
        colorScheme = ColorSchemeChoice(
            rawValue: defaults.string(forKey: "appearance.colorScheme") ?? ""
        ) ?? .system
    }

    private func save(_ key: String, _ value: String) {
        UserDefaults.standard.set(value, forKey: key)
    }

    // Convenience for the views.
    var accent: Color { palette.accent }
    var hot: Color { palette.hot }

    func valueFont(size: CGFloat) -> Font {
        .system(size: size, weight: weight.font, design: typeface.design)
    }

    func labelFont(size: CGFloat) -> Font {
        .system(size: size, weight: .medium, design: typeface.design)
    }

    func reset() {
        typeface = .neutral
        weight = .semibold
        palette = .blue
        colorScheme = .system
    }
}

extension EnvironmentValues {
    /// Non-optional accessor with a fallback, so no view needs to handle a missing
    /// `Appearance` in the environment. Needs a setter to be injectable with
    /// `.environment(\.appearance, …)`.
    var appearance: Appearance {
        get { self[AppearanceKey.self] }
        set { self[AppearanceKey.self] = newValue }
    }
}

private struct AppearanceKey: EnvironmentKey {
    static let defaultValue = Appearance.fallback
}

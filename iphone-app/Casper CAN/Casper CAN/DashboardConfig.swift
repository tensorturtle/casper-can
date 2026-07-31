//  DashboardConfig.swift
//  Which metrics are on the dashboard, in what order, drawn how, and which one is
//  the hero.
//
//  Persisted to UserDefaults as JSON. Small enough that there is no reason to
//  involve SwiftData, and a flat JSON blob survives adding fields to MetricConfig
//  without a migration.

import Foundation
import Observation
import SwiftUI

enum GaugeStyleKind: String, CaseIterable, Codable, Identifiable {
    case number
    case circular
    case linear
    case indicator

    var id: String { rawValue }

    var title: String {
        switch self {
        case .number: "Number"
        case .circular: "Circular gauge"
        case .linear: "Linear bar"
        case .indicator: "Indicator lamp"
        }
    }

    var symbol: String {
        switch self {
        case .number: "textformat.123"
        case .circular: "gauge.with.needle"
        case .linear: "chart.bar.fill"
        case .indicator: "lightbulb.fill"
        }
    }
}

/// How one metric is displayed.
struct MetricConfig: Identifiable, Codable, Equatable {
    var metric: VehicleMetric
    var style: GaugeStyleKind
    var minimum: Double
    var maximum: Double

    /// Values at or above this read as "hot". Nil disables the warning entirely.
    var redline: Double?

    /// Also warn below `-redline`, for signed quantities where a large negative
    /// value is equally significant (steering torque hard left, say).
    var mirrorRedline: Bool

    var id: String { metric.rawValue }

    init(_ metric: VehicleMetric) {
        self.metric = metric
        self.style = metric.defaultStyle
        self.minimum = metric.defaultRange.lowerBound
        self.maximum = metric.defaultRange.upperBound
        self.redline = metric.defaultRedline
        self.mirrorRedline = metric.isBipolar
    }

    /// Guarded against an inverted or zero-width range, which the settings
    /// steppers can otherwise produce and which would divide by zero below.
    var range: ClosedRange<Double> {
        minimum < maximum ? minimum...maximum : minimum...(minimum + 1)
    }

    /// 0...1 position of `value` within the range, clamped.
    func fraction(of value: Double) -> Double {
        let r = range
        return ((value - r.lowerBound) / (r.upperBound - r.lowerBound)).clamped(to: 0...1)
    }

    func isHot(_ value: Double) -> Bool {
        guard let redline else { return false }
        if mirrorRedline { return abs(value) >= abs(redline) }
        return value >= redline
    }

    /// The widest string this tile can plausibly display, used to reserve a fixed
    /// width so the layout does not shift as digits come and go.
    ///
    /// Derived from the configured range rather than a digit count, so it picks up
    /// the sign, the decimal point and the thousands separator exactly as the
    /// formatter will render them - "-10,000" reserves more room than "10000" would
    /// suggest, and "460.0" more than "460".
    ///
    /// The extremes are the widest values because digits are monospaced: more
    /// magnitude means more digits and more separators, never fewer. A reading that
    /// overshoots the configured range keeps the same width unless it also gains a
    /// digit, which is a deliberate trade - reserving for the theoretical maximum of
    /// every signal would shrink every number for the sake of cases that do not
    /// occur.
    var widthTemplate: String {
        if metric.isBoolean { return "OFF" }
        let low = metric.format(range.lowerBound)
        let high = metric.format(range.upperBound)
        // Longest by character count; on a tie prefer the negative, whose sign
        // still occupies space.
        if low.count == high.count { return low.hasPrefix("-") ? low : high }
        return low.count > high.count ? low : high
    }

    /// Styles that make sense for this metric. A boolean has nothing to sweep, so
    /// it is offered only as a lamp or a bare ON/OFF.
    var availableStyles: [GaugeStyleKind] {
        metric.isBoolean ? [.indicator, .number] : [.number, .circular, .linear]
    }
}

@Observable
final class DashboardConfig {
    /// Enabled tiles, in display order.
    var tiles: [MetricConfig] {
        didSet { save() }
    }

    /// The metric shown in the 2x2 hero tile. Nil means no hero — the grid is then
    /// uniform. Kept separate from `tiles` so promoting a metric to hero does not
    /// disturb the position it returns to when demoted.
    var heroMetric: VehicleMetric? {
        didSet { saveHero() }
    }

    // Keys are versioned: wire v3 renamed the metric set, so a v1 payload would
    // decode to nothing useful. A fresh key is cheaper than a migration.
    private static let tilesKey = "dashboard.tiles.v3"
    private static let heroKey = "dashboard.hero.v3"

    /// A curated starting set. There are 34 metrics available; showing all of them
    /// on first launch would bury the ones that matter. The picker offers the rest,
    /// grouped by subject, plus a one-tap "add every metric".
    static let defaultMetrics: [VehicleMetric] = [
        .speed, .rpm, .coolant, .throttle,
        .steeringAngle, .steeringTorque,
        .fuelLevel, .voltage,
        .acCompressor, .checkEngine,
    ]

    init() {
        if let data = UserDefaults.standard.data(forKey: Self.tilesKey),
           let decoded = try? JSONDecoder().decode([MetricConfig].self, from: data) {
            tiles = decoded
        } else {
            tiles = Self.defaultMetrics.map { MetricConfig($0) }
        }

        if let raw = UserDefaults.standard.string(forKey: Self.heroKey) {
            // An empty string is an explicit "no hero", distinct from never set.
            heroMetric = raw.isEmpty ? nil : VehicleMetric(rawValue: raw)
        } else {
            heroMetric = .speed
        }
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(tiles) else { return }
        UserDefaults.standard.set(data, forKey: Self.tilesKey)
    }

    private func saveHero() {
        UserDefaults.standard.set(heroMetric?.rawValue ?? "", forKey: Self.heroKey)
    }

    func isEnabled(_ metric: VehicleMetric) -> Bool {
        tiles.contains { $0.metric == metric }
    }

    func setEnabled(_ metric: VehicleMetric, _ enabled: Bool) {
        if enabled {
            guard !isEnabled(metric) else { return }
            // Insert in declaration order so toggling off and on again does not
            // shuffle a tile to the end.
            let target = VehicleMetric.allCases.firstIndex(of: metric) ?? 0
            let insertAt = tiles.firstIndex {
                (VehicleMetric.allCases.firstIndex(of: $0.metric) ?? 0) > target
            } ?? tiles.endIndex
            tiles.insert(MetricConfig(metric), at: insertAt)
        } else {
            tiles.removeAll { $0.metric == metric }
            // A hero that is no longer displayed would leave an empty slot.
            if heroMetric == metric { heroMetric = nil }
        }
    }

    /// The hero's config, if the hero is set and still enabled.
    var heroConfig: MetricConfig? {
        guard let heroMetric else { return nil }
        return tiles.first { $0.metric == heroMetric }
    }

    /// Tiles for the regular grid: everything except the hero.
    var gridTiles: [MetricConfig] {
        tiles.filter { $0.metric != heroMetric }
    }

    func binding(for metric: VehicleMetric) -> Binding<MetricConfig>? {
        guard let index = tiles.firstIndex(where: { $0.metric == metric }) else {
            return nil
        }
        return Binding(
            get: { self.tiles[index] },
            set: { self.tiles[index] = $0 }
        )
    }

    /// Show everything. Preserves any customisation already made to a tile.
    func enableAll() {
        let existing = Dictionary(uniqueKeysWithValues: tiles.map { ($0.metric, $0) })
        tiles = VehicleMetric.allCases.map { existing[$0] ?? MetricConfig($0) }
    }

    func resetToDefaults() {
        tiles = Self.defaultMetrics.map { MetricConfig($0) }
        heroMetric = .speed
    }
}

extension Comparable {
    func clamped(to limits: ClosedRange<Self>) -> Self {
        min(max(self, limits.lowerBound), limits.upperBound)
    }
}

//  DashboardConfig.swift
//  Which measurements are on the dashboard, in what order, drawn how.
//
//  Persisted to UserDefaults as JSON. Small enough that there is no reason to
//  involve SwiftData, and a flat JSON blob survives adding fields to
//  MetricConfig without a migration.

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

/// How one measurement is displayed.
struct MetricConfig: Identifiable, Codable, Equatable {
    var measurement: VehicleMetric
    var style: GaugeStyleKind
    var minimum: Double
    var maximum: Double

    /// Values at or above this read as "hot". Nil disables the warning entirely.
    var redline: Double?

    /// Also warn below `-redline`, for signed quantities where a large negative
    /// value is equally significant (steering torque hard left, say).
    var mirrorRedline: Bool

    var id: String { measurement.rawValue }

    init(_ measurement: VehicleMetric) {
        self.measurement = measurement
        self.style = measurement.defaultStyle
        self.minimum = measurement.defaultRange.lowerBound
        self.maximum = measurement.defaultRange.upperBound
        self.redline = measurement.defaultRedline
        self.mirrorRedline = measurement.isBipolar
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

    /// Styles that make sense for this measurement. A boolean has nothing to
    /// sweep, so it is offered only as a lamp or a bare ON/OFF.
    var availableStyles: [GaugeStyleKind] {
        measurement.isBoolean ? [.indicator, .number] : [.number, .circular, .linear]
    }
}

@Observable
final class DashboardConfig {
    /// Enabled tiles, in display order.
    var tiles: [MetricConfig] {
        didSet { save() }
    }

    private static let storageKey = "dashboard.tiles.v1"

    init() {
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let decoded = try? JSONDecoder().decode([MetricConfig].self, from: data) {
            tiles = decoded
        } else {
            // First launch: everything on, in the declared order, so the user sees
            // what is available and removes rather than hunts.
            //
            // A closure rather than `map(MetricConfig.init)`: this project builds
            // with SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor, which makes that
            // initializer main-actor isolated. Passing it as a bare function
            // reference crosses isolation; calling it inside a non-escaping
            // closure inherits this context's isolation instead.
            tiles = VehicleMetric.allCases.map { MetricConfig($0) }
        }
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(tiles) else { return }
        UserDefaults.standard.set(data, forKey: Self.storageKey)
    }

    func isEnabled(_ measurement: VehicleMetric) -> Bool {
        tiles.contains { $0.measurement == measurement }
    }

    func setEnabled(_ measurement: VehicleMetric, _ enabled: Bool) {
        if enabled {
            guard !isEnabled(measurement) else { return }
            // Insert in declaration order so toggling off and on again does not
            // shuffle a tile to the end.
            let target = VehicleMetric.allCases.firstIndex(of: measurement) ?? 0
            let insertAt = tiles.firstIndex {
                (VehicleMetric.allCases.firstIndex(of: $0.measurement) ?? 0) > target
            } ?? tiles.endIndex
            tiles.insert(MetricConfig(measurement), at: insertAt)
        } else {
            tiles.removeAll { $0.measurement == measurement }
        }
    }

    func binding(for measurement: VehicleMetric) -> Binding<MetricConfig>? {
        guard let index = tiles.firstIndex(where: { $0.measurement == measurement }) else {
            return nil
        }
        return Binding(
            get: { self.tiles[index] },
            set: { self.tiles[index] = $0 }
        )
    }

    func resetToDefaults() {
        tiles = VehicleMetric.allCases.map { MetricConfig($0) }
    }
}

extension Comparable {
    func clamped(to limits: ClosedRange<Self>) -> Self {
        min(max(self, limits.lowerBound), limits.upperBound)
    }
}

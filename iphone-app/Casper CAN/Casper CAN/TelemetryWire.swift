//  TelemetryWire.swift
//  The wire contract with the Radxa appliance.
//
//  This file is the Swift mirror of TELEMETRY_STRUCT in
//  ../../../appliance/ble_peripheral.py. Both sides must change together; the
//  `wireVersion` reported by the status characteristic exists so a mismatch is
//  detectable rather than silently wrong.

import Foundation
import CoreBluetooth

enum Wire {
    static let service = CBUUID(string: "6E1A0001-8B2F-4D3A-9C47-2F5B7A1E9D00")
    static let telemetry = CBUUID(string: "6E1A0002-8B2F-4D3A-9C47-2F5B7A1E9D00")
    static let status = CBUUID(string: "6E1A0003-8B2F-4D3A-9C47-2F5B7A1E9D00")

    /// The appliance advertises this local name by default (`--name` overrides it).
    static let defaultLocalName = "CasperCAN"

    /// Wire version this app understands. Compared against the status characteristic.
    static let supportedVersion = 1

    static let frameLength = 12
}

/// One decoded telemetry sample.
///
/// The board sends a fixed 12-byte little-endian frame rather than JSON, because
/// per-notification overhead is the scarce resource on BLE. Little-endian is
/// deliberate: it matches the iPhone's native byte order, so the integers load
/// directly with no byteswap.
///
///     offset  type      field
///     0       uint32    monotonic timestamp, ms since board start
///     4       uint16    speed, km/h * 100
///     6       int16     steering angle, deg * 10   (+ = left)
///     8       int16     steering torque, raw counts (+ = right)
///     10      uint8     flags (bit0 = A/C compressor, bit1 = MIL)
///     11      uint8     reserved
struct TelemetryFrame: Equatable {
    var uptime: Duration
    var speedKph: Double
    var steeringAngleDeg: Double
    var steeringTorque: Double
    var acCompressorOn: Bool
    var milOn: Bool

    /// Wall-clock arrival time, for staleness display. Not from the wire - the
    /// board sends its own monotonic uptime, which cannot be compared to ours.
    var receivedAt: Date = .now

    private enum Flags {
        static let acCompressor: UInt8 = 1 << 0
        static let mil: UInt8 = 1 << 1
    }

    /// Decode a notification payload. Returns nil on a short or oversized frame
    /// rather than trapping - a malformed packet should drop one sample, not the
    /// connection.
    init?(payload: Data) {
        guard payload.count == Wire.frameLength else { return nil }

        // Copy into a correctly-aligned buffer before loading. `Data`'s backing
        // store carries no alignment guarantee, and loadUnaligned is only
        // available on raw buffers - going through withUnsafeBytes on a Data
        // slice risks a misaligned load on a sliced instance.
        let bytes = [UInt8](payload)

        func u16(_ offset: Int) -> UInt16 {
            UInt16(bytes[offset]) | (UInt16(bytes[offset + 1]) << 8)
        }
        func i16(_ offset: Int) -> Int16 { Int16(bitPattern: u16(offset)) }
        func u32(_ offset: Int) -> UInt32 {
            UInt32(bytes[offset]) | (UInt32(bytes[offset + 1]) << 8)
                | (UInt32(bytes[offset + 2]) << 16) | (UInt32(bytes[offset + 3]) << 24)
        }

        self.uptime = .milliseconds(Int(u32(0)))
        self.speedKph = Double(u16(4)) / 100.0
        self.steeringAngleDeg = Double(i16(6)) / 10.0
        self.steeringTorque = Double(i16(8))

        let flags = bytes[10]
        self.acCompressorOn = flags & Flags.acCompressor != 0
        self.milOn = flags & Flags.mil != 0
    }

    /// Placeholder shown before the first sample arrives, and in SwiftUI previews.
    static let zero = TelemetryFrame(
        uptime: .zero, speedKph: 0, steeringAngleDeg: 0,
        steeringTorque: 0, acCompressorOn: false, milOn: false
    )

    private init(
        uptime: Duration, speedKph: Double, steeringAngleDeg: Double,
        steeringTorque: Double, acCompressorOn: Bool, milOn: Bool
    ) {
        self.uptime = uptime
        self.speedKph = speedKph
        self.steeringAngleDeg = steeringAngleDeg
        self.steeringTorque = steeringTorque
        self.acCompressorOn = acCompressorOn
        self.milOn = milOn
    }
}

/// Decoded form of the status characteristic (JSON, read on connect).
struct ApplianceStatus: Decodable {
    var service: String
    var wireVersion: Int
    var source: String
    var telemetryLen: Int
    var notifyIntervalS: Double
    var notificationsSent: Int

    enum CodingKeys: String, CodingKey {
        case service
        case wireVersion = "wire_version"
        case source
        case telemetryLen = "telemetry_len"
        case notifyIntervalS = "notify_interval_s"
        case notificationsSent = "notifications_sent"
    }

    /// True when the board is serving made-up data. Worth surfacing in the UI -
    /// otherwise a convincing synthetic sweep reads as a working CAN connection.
    var isSynthetic: Bool { source == "synthetic" }

    var isCompatible: Bool { wireVersion == Wire.supportedVersion }
}

// MARK: - Measurements

/// A quantity the appliance reports, and how to present it.
///
/// Adding a signal means adding a case here plus a line in `value(from:)`. The
/// per-metric defaults are starting points; the user overrides range, style and
/// redline in `MetricSettingsView`.
enum VehicleMetric: String, CaseIterable, Codable, Identifiable {
    case speed
    case steeringAngle
    case steeringTorque
    case acCompressor
    case checkEngine

    var id: String { rawValue }

    var title: String {
        switch self {
        case .speed: "Speed"
        case .steeringAngle: "Steering Angle"
        case .steeringTorque: "Steering Torque"
        case .acCompressor: "A/C Compressor"
        case .checkEngine: "Check Engine"
        }
    }

    var unit: String {
        switch self {
        case .speed: "km/h"
        case .steeringAngle: "°"
        case .steeringTorque: "cts"
        case .acCompressor, .checkEngine: ""
        }
    }

    var symbol: String {
        switch self {
        case .speed: "speedometer"
        case .steeringAngle: "steeringwheel"
        case .steeringTorque: "arrow.clockwise.circle"
        case .acCompressor: "snowflake"
        case .checkEngine: "engine.combustion"
        }
    }

    /// Booleans get an indicator lamp; no range or gauge applies to them.
    var isBoolean: Bool {
        switch self {
        case .acCompressor, .checkEngine: true
        default: false
        }
    }

    /// Signed quantities are centred on zero, so a bar renders from the middle.
    var isBipolar: Bool {
        switch self {
        case .steeringAngle, .steeringTorque: true
        default: false
        }
    }

    func value(from frame: TelemetryFrame) -> Double {
        switch self {
        case .speed: frame.speedKph
        case .steeringAngle: frame.steeringAngleDeg
        case .steeringTorque: frame.steeringTorque
        case .acCompressor: frame.acCompressorOn ? 1 : 0
        case .checkEngine: frame.milOn ? 1 : 0
        }
    }

    /// Full-scale defaults, taken from the vehicle's actual limits documented in
    /// docs/04-signal-reference.md - steering is +-460 deg lock to lock, torque
    /// clamps hard at +-10000 counts.
    var defaultRange: ClosedRange<Double> {
        switch self {
        case .speed: 0...180
        case .steeringAngle: -460...460
        case .steeringTorque: -10000...10000
        case .acCompressor, .checkEngine: 0...1
        }
    }

    var defaultStyle: GaugeStyleKind {
        switch self {
        case .speed: .circular
        case .steeringAngle: .linear
        case .steeringTorque: .linear
        case .acCompressor, .checkEngine: .indicator
        }
    }

    /// Where "too much" begins by default. Nil where the concept doesn't apply.
    var defaultRedline: Double? {
        switch self {
        case .speed: 110          // national expressway limit
        case .steeringTorque: 7000
        case .steeringAngle: nil  // full lock is not a fault
        case .acCompressor, .checkEngine: nil
        }
    }

    /// Decimal places for display. Torque is a raw count, so no fraction.
    var fractionDigits: Int {
        switch self {
        case .speed: 0
        case .steeringAngle: 1
        case .steeringTorque: 0
        case .acCompressor, .checkEngine: 0
        }
    }

    func format(_ value: Double) -> String {
        if isBoolean { return value > 0.5 ? "ON" : "OFF" }
        return value.formatted(
            .number.precision(.fractionLength(fractionDigits))
        )
    }
}

//  TelemetryWire.swift
//  The wire contract with the Radxa appliance.
//
//  This file is the Swift mirror of ../../../appliance/wire.py. Both sides must
//  change in the same commit; the `wireVersion` reported by the status
//  characteristic exists so a mismatch is detectable rather than silently wrong.
//
//  WIRE VERSION 3. The signal set is deliberately maximal: every Mode 01 PID this
//  vehicle supports, plus the MDPS steering pair, HVAC compressor, MIL state and
//  the cluster's odometer and fuel quantity.

import Foundation
import CoreBluetooth

enum Wire {
    static let service = CBUUID(string: "6E1A0001-8B2F-4D3A-9C47-2F5B7A1E9D00")
    static let telemetry = CBUUID(string: "6E1A0002-8B2F-4D3A-9C47-2F5B7A1E9D00")
    static let status = CBUUID(string: "6E1A0003-8B2F-4D3A-9C47-2F5B7A1E9D00")

    /// The appliance advertises this local name by default (`--name` overrides it).
    static let defaultLocalName = "CasperCAN"

    /// Wire version this app understands. Compared against the status characteristic.
    static let supportedVersion = 3

    /// A 78-byte notification needs an ATT MTU of at least 81. iOS negotiates 185,
    /// so this fits - but if a frame ever arrives truncated, `TelemetryFrame.init`
    /// rejects it on length and the app surfaces a malformed-frame warning rather
    /// than decoding shifted garbage.
    static let frameLength = 78
}

/// One decoded telemetry sample. Field offsets mirror `wire.py`; see that file for
/// the authoritative table.
struct TelemetryFrame: Equatable {
    var uptimeMilliseconds: UInt32 = 0

    /// Which signals the board actually got an answer for. Without this the app
    /// cannot tell "0 km/h, stationary" from "no answer, assume zero" — the most
    /// important distinction in the whole frame.
    var validity: UInt32 = 0

    /// Cumulative failed polls on the board. A rising count with the ignition on
    /// means the bus or the adapter needs attention.
    var pollErrors: UInt16 = 0

    var acCompressorOn = false
    var milOn = false

    // Signed group.
    var coolantC: Double = 0
    var intakeAirC: Double = 0
    var ambientC: Double = 0
    var timingDeg: Double = 0
    var shortTrimPct: Double = 0
    var longTrimPct: Double = 0
    var steeringAngleDeg: Double = 0
    var steeringTorque: Double = 0

    // Unsigned group.
    var speedKph: Double = 0
    var rpm: Double = 0
    var engineLoadPct: Double = 0
    var absLoadPct: Double = 0
    var throttlePct: Double = 0
    var relThrottlePct: Double = 0
    var absThrottleBPct: Double = 0
    var accelDPct: Double = 0
    var accelEPct: Double = 0
    var cmdThrottlePct: Double = 0
    var fuelLevelPct: Double = 0
    var mapKpa: Double = 0
    var baroKpa: Double = 0
    var voltageV: Double = 0
    var equivRatio: Double = 0
    var fuelRailKpa: Double = 0
    var runTimeS: Double = 0
    var warmups: Double = 0
    var distMilKm: Double = 0
    var timeMilMin: Double = 0
    var distClearKm: Double = 0
    var dtcCount: Double = 0
    var odometerKm: Double = 0
    var fuelLitres: Double = 0

    /// Wall-clock arrival time, for staleness display. Not from the wire — the
    /// board sends its own monotonic uptime, which cannot be compared to ours.
    var receivedAt: Date = .now

    private enum Flags {
        static let acCompressor: UInt16 = 1 << 0
        static let mil: UInt16 = 1 << 1
    }

    init() {}

    /// Decode a notification payload. Returns nil on a wrong-length frame rather
    /// than trapping — a malformed packet should drop one sample, not the
    /// connection.
    init?(payload: Data) {
        guard payload.count == Wire.frameLength else { return nil }

        // Copy into an array before loading: `Data`'s backing store carries no
        // alignment guarantee, and a sliced instance can be misaligned.
        let b = [UInt8](payload)

        func u16(_ o: Int) -> UInt16 { UInt16(b[o]) | (UInt16(b[o + 1]) << 8) }
        func i16(_ o: Int) -> Int16 { Int16(bitPattern: u16(o)) }
        func u32(_ o: Int) -> UInt32 {
            UInt32(b[o]) | (UInt32(b[o + 1]) << 8)
                | (UInt32(b[o + 2]) << 16) | (UInt32(b[o + 3]) << 24)
        }
        func scaled(_ o: Int, _ divisor: Double) -> Double { Double(u16(o)) / divisor }
        func signedScaled(_ o: Int, _ divisor: Double) -> Double { Double(i16(o)) / divisor }

        uptimeMilliseconds = u32(0)
        validity = u32(4)
        let flags = u16(8)
        pollErrors = u16(10)

        acCompressorOn = flags & Flags.acCompressor != 0
        milOn = flags & Flags.mil != 0

        coolantC = signedScaled(12, 1)
        intakeAirC = signedScaled(14, 1)
        ambientC = signedScaled(16, 1)
        timingDeg = signedScaled(18, 10)
        shortTrimPct = signedScaled(20, 10)
        longTrimPct = signedScaled(22, 10)
        steeringAngleDeg = signedScaled(24, 10)
        steeringTorque = signedScaled(26, 1)

        speedKph = scaled(28, 100)
        rpm = scaled(30, 1)
        engineLoadPct = scaled(32, 10)
        absLoadPct = scaled(34, 10)
        throttlePct = scaled(36, 10)
        relThrottlePct = scaled(38, 10)
        absThrottleBPct = scaled(40, 10)
        accelDPct = scaled(42, 10)
        accelEPct = scaled(44, 10)
        cmdThrottlePct = scaled(46, 10)
        fuelLevelPct = scaled(48, 10)
        mapKpa = scaled(50, 1)
        baroKpa = scaled(52, 1)
        voltageV = scaled(54, 1000)
        equivRatio = scaled(56, 1000)
        // Carried in units of 10 kPa to fit uint16.
        fuelRailKpa = scaled(58, 1) * 10
        runTimeS = scaled(60, 1)
        warmups = scaled(62, 1)
        distMilKm = scaled(64, 1)
        timeMilMin = scaled(66, 1)
        distClearKm = scaled(68, 1)
        dtcCount = scaled(70, 1)
        odometerKm = Double(u32(72))
        fuelLitres = scaled(76, 100)
    }

    /// Placeholder shown before the first sample arrives.
    /// Validity is zero: nothing here has been confirmed by the vehicle.
    static let zero = TelemetryFrame()

    /// Plausible values with everything marked valid, for SwiftUI previews.
    static func preview() -> TelemetryFrame {
        var f = TelemetryFrame()
        f.validity = 0x7FFF_FFFF
        f.speedKph = 62; f.rpm = 2300; f.throttlePct = 21.4; f.relThrottlePct = 9.2
        f.absThrottleBPct = 22.6; f.accelDPct = 24.1; f.accelEPct = 12.3
        f.cmdThrottlePct = 11.8; f.engineLoadPct = 44.2; f.absLoadPct = 33.1
        f.coolantC = 89; f.intakeAirC = 32; f.ambientC = 26; f.timingDeg = 12.5
        f.shortTrimPct = -1.6; f.longTrimPct = 0.8; f.mapKpa = 96; f.baroKpa = 101
        f.voltageV = 14.32; f.equivRatio = 0.998; f.fuelRailKpa = 14500
        f.fuelLevelPct = 63.5; f.fuelLitres = 22.4; f.odometerKm = 8429
        f.runTimeS = 931; f.warmups = 41; f.distClearKm = 8437
        f.steeringAngleDeg = -87.5; f.steeringTorque = -1480
        f.acCompressorOn = true
        return f
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
    var valid: String?
    var pollErrors: Int?

    enum CodingKeys: String, CodingKey {
        case service
        case wireVersion = "wire_version"
        case source
        case telemetryLen = "telemetry_len"
        case notifyIntervalS = "notify_interval_s"
        case notificationsSent = "notifications_sent"
        case valid
        case pollErrors = "poll_errors"
    }

    /// True when the board is serving made-up data. Worth surfacing prominently —
    /// otherwise a convincing synthetic sweep reads as a working CAN connection.
    var isSynthetic: Bool { source == "synthetic" }

    var isCompatible: Bool { wireVersion == Wire.supportedVersion }
}

// MARK: - Metrics

/// Everything the appliance can report, and how to present it.
///
/// Named `VehicleMetric`, not `Measurement`: the latter shadows Foundation's
/// generic `Measurement<UnitType>` and produces baffling errors.
///
/// Adding a signal means a case here, entries in the switches below, and a
/// validity bit matching `wire.py`. `MetricGroup` only affects how the picker
/// organises them.
enum VehicleMetric: String, CaseIterable, Codable, Identifiable {
    // Motion and driver input
    case speed, rpm, throttle, relThrottle, absThrottleB
    case accelPedalD, accelPedalE, cmdThrottle
    case engineLoad, absLoad
    // Steering
    case steeringAngle, steeringTorque
    // Temperatures
    case coolant, intakeAir, ambient
    // Fuelling and air
    case map, baro, timingAdvance, shortTrim, longTrim, equivRatio, fuelRail
    // Fuel and distance
    case fuelLevel, fuelLitres, odometer, distClear, runTime, warmups
    // Electrical and faults
    case voltage, dtcCount, distMil, timeMil
    case acCompressor, checkEngine

    var id: String { rawValue }

    var title: String {
        switch self {
        case .speed: "Speed"
        case .rpm: "Engine Speed"
        case .throttle: "Throttle"
        case .relThrottle: "Rel. Throttle"
        case .absThrottleB: "Throttle B"
        case .accelPedalD: "Accel Pedal D"
        case .accelPedalE: "Accel Pedal E"
        case .cmdThrottle: "Cmd Throttle"
        case .engineLoad: "Engine Load"
        case .absLoad: "Absolute Load"
        case .steeringAngle: "Steering Angle"
        case .steeringTorque: "Steering Torque"
        case .coolant: "Coolant"
        case .intakeAir: "Intake Air"
        case .ambient: "Ambient Air"
        case .map: "Intake MAP"
        case .baro: "Barometric"
        case .timingAdvance: "Timing Advance"
        case .shortTrim: "Short Fuel Trim"
        case .longTrim: "Long Fuel Trim"
        case .equivRatio: "Equiv. Ratio"
        case .fuelRail: "Fuel Rail Press."
        case .fuelLevel: "Fuel Level"
        case .fuelLitres: "Fuel Quantity"
        case .odometer: "Odometer"
        case .distClear: "Dist. Since Clear"
        case .runTime: "Run Time"
        case .warmups: "Warm-ups"
        case .voltage: "Module Voltage"
        case .dtcCount: "Stored Faults"
        case .distMil: "Dist. With MIL"
        case .timeMil: "Time With MIL"
        case .acCompressor: "A/C Compressor"
        case .checkEngine: "Check Engine"
        }
    }

    var unit: String {
        switch self {
        case .speed: "km/h"
        case .rpm: "rpm"
        case .throttle, .relThrottle, .absThrottleB, .accelPedalD, .accelPedalE,
             .cmdThrottle, .engineLoad, .absLoad, .fuelLevel: "%"
        case .shortTrim, .longTrim: "%"
        case .steeringAngle, .timingAdvance: "°"
        case .steeringTorque: "cts"
        case .coolant, .intakeAir, .ambient: "°C"
        case .map, .baro: "kPa"
        case .fuelRail: "kPa"
        case .equivRatio: "λ"
        case .fuelLitres: "L"
        case .odometer, .distClear, .distMil: "km"
        case .runTime: "s"
        case .timeMil: "min"
        case .warmups, .dtcCount: ""
        case .voltage: "V"
        case .acCompressor, .checkEngine: ""
        }
    }

    var symbol: String {
        switch self {
        case .speed: "speedometer"
        case .rpm: "gauge.with.dots.needle.67percent"
        case .throttle, .relThrottle, .absThrottleB, .cmdThrottle: "pedal.accelerator"
        case .accelPedalD, .accelPedalE: "pedal.accelerator"
        case .engineLoad, .absLoad: "chart.line.uptrend.xyaxis"
        case .steeringAngle: "steeringwheel"
        case .steeringTorque: "arrow.clockwise.circle"
        case .coolant: "thermometer.medium"
        case .intakeAir: "wind"
        case .ambient: "thermometer.sun"
        case .map, .baro: "barometer"
        case .timingAdvance: "timer"
        case .shortTrim, .longTrim: "slider.horizontal.below.square.filled.and.square"
        case .equivRatio: "atom"
        case .fuelRail: "gauge.open.with.lines.needle.33percent"
        case .fuelLevel, .fuelLitres: "fuelpump"
        case .odometer, .distClear, .distMil: "road.lanes"
        case .runTime, .timeMil: "clock"
        case .warmups: "flame"
        case .voltage: "bolt"
        case .dtcCount: "exclamationmark.triangle"
        case .acCompressor: "snowflake"
        case .checkEngine: "engine.combustion"
        }
    }

    /// The validity bit for this metric. Mirrors `VALID_*` in wire.py — signals
    /// that arrive from one request share a bit.
    var validityBit: UInt32 {
        switch self {
        case .speed: 1 << 0
        case .rpm: 1 << 1
        case .coolant: 1 << 2
        case .engineLoad: 1 << 3
        case .throttle: 1 << 4
        case .fuelLevel: 1 << 5
        case .steeringAngle, .steeringTorque: 1 << 6
        case .acCompressor: 1 << 7
        case .checkEngine, .dtcCount: 1 << 8
        case .intakeAir: 1 << 9
        case .ambient: 1 << 10
        case .timingAdvance: 1 << 11
        case .shortTrim: 1 << 12
        case .longTrim: 1 << 13
        case .absLoad: 1 << 14
        case .relThrottle: 1 << 15
        case .absThrottleB: 1 << 16
        case .accelPedalD: 1 << 17
        case .accelPedalE: 1 << 18
        case .cmdThrottle: 1 << 19
        case .map: 1 << 20
        case .baro: 1 << 21
        case .voltage: 1 << 22
        case .equivRatio: 1 << 23
        case .fuelRail: 1 << 24
        case .runTime: 1 << 25
        case .warmups: 1 << 26
        case .distMil: 1 << 27
        case .timeMil: 1 << 28
        case .distClear: 1 << 29
        case .odometer, .fuelLitres: 1 << 30
        }
    }

    /// Booleans get an indicator lamp; no range or gauge applies.
    var isBoolean: Bool {
        switch self {
        case .acCompressor, .checkEngine: true
        default: false
        }
    }

    /// Signed quantities are centred on zero, so a bar renders from the middle.
    var isBipolar: Bool {
        switch self {
        case .steeringAngle, .steeringTorque, .shortTrim, .longTrim, .timingAdvance: true
        default: false
        }
    }

    func value(from f: TelemetryFrame) -> Double {
        switch self {
        case .speed: f.speedKph
        case .rpm: f.rpm
        case .throttle: f.throttlePct
        case .relThrottle: f.relThrottlePct
        case .absThrottleB: f.absThrottleBPct
        case .accelPedalD: f.accelDPct
        case .accelPedalE: f.accelEPct
        case .cmdThrottle: f.cmdThrottlePct
        case .engineLoad: f.engineLoadPct
        case .absLoad: f.absLoadPct
        case .steeringAngle: f.steeringAngleDeg
        case .steeringTorque: f.steeringTorque
        case .coolant: f.coolantC
        case .intakeAir: f.intakeAirC
        case .ambient: f.ambientC
        case .map: f.mapKpa
        case .baro: f.baroKpa
        case .timingAdvance: f.timingDeg
        case .shortTrim: f.shortTrimPct
        case .longTrim: f.longTrimPct
        case .equivRatio: f.equivRatio
        case .fuelRail: f.fuelRailKpa
        case .fuelLevel: f.fuelLevelPct
        case .fuelLitres: f.fuelLitres
        case .odometer: f.odometerKm
        case .distClear: f.distClearKm
        case .runTime: f.runTimeS
        case .warmups: f.warmups
        case .voltage: f.voltageV
        case .dtcCount: f.dtcCount
        case .distMil: f.distMilKm
        case .timeMil: f.timeMilMin
        case .acCompressor: f.acCompressorOn ? 1 : 0
        case .checkEngine: f.milOn ? 1 : 0
        }
    }

    func isValid(in frame: TelemetryFrame) -> Bool {
        frame.validity & validityBit != 0
    }

    /// Full-scale defaults from this vehicle's documented limits — steering is
    /// ±460° lock to lock and torque clamps at ±10000 counts
    /// (see docs/04-signal-reference.md).
    var defaultRange: ClosedRange<Double> {
        switch self {
        case .speed: 0...180
        case .rpm: 0...6500
        case .throttle, .relThrottle, .absThrottleB, .accelPedalD, .accelPedalE,
             .cmdThrottle, .engineLoad, .absLoad, .fuelLevel: 0...100
        case .shortTrim, .longTrim: -25...25
        case .steeringAngle: -460...460
        case .steeringTorque: -10000...10000
        case .coolant: 0...130
        case .intakeAir: -20...80
        case .ambient: -20...60
        case .map: 0...255
        case .baro: 80...110
        case .timingAdvance: -20...60
        case .equivRatio: 0.7...1.3
        case .fuelRail: 0...25000
        case .fuelLitres: 0...36        // ~36 L tank per the car's spec
        case .odometer: 0...300000
        case .distClear, .distMil: 0...65535
        case .runTime: 0...7200
        case .timeMil: 0...1000
        case .warmups: 0...255
        case .voltage: 8...16
        case .dtcCount: 0...16
        case .acCompressor, .checkEngine: 0...1
        }
    }

    var defaultStyle: GaugeStyleKind {
        switch self {
        case .speed, .rpm, .engineLoad, .absLoad: .circular
        case .throttle, .relThrottle, .absThrottleB, .accelPedalD, .accelPedalE,
             .cmdThrottle, .fuelLevel, .steeringAngle, .steeringTorque,
             .shortTrim, .longTrim, .timingAdvance, .map, .equivRatio: .linear
        case .coolant, .intakeAir, .ambient, .baro, .voltage, .fuelRail,
             .fuelLitres, .odometer, .distClear, .runTime, .warmups,
             .dtcCount, .distMil, .timeMil: .number
        case .acCompressor, .checkEngine: .indicator
        }
    }

    /// Where "too much" begins by default. Nil where the concept doesn't apply —
    /// most counters and totals have no meaningful ceiling.
    var defaultRedline: Double? {
        switch self {
        case .speed: 110            // national expressway limit
        case .rpm: 5500
        case .coolant: 105          // above normal operating range
        case .steeringTorque: 7000
        case .shortTrim, .longTrim: 10   // sustained large trim indicates a fault
        case .intakeAir: 60
        case .dtcCount: 1           // any stored fault is worth flagging
        case .distMil, .timeMil: 1  // MIL having been on at all matters
        case .voltage: nil          // both extremes matter; a ceiling would mislead
        default: nil
        }
    }

    var fractionDigits: Int {
        switch self {
        case .equivRatio: 3
        case .voltage: 2
        case .steeringAngle, .timingAdvance, .shortTrim, .longTrim, .fuelLitres: 1
        default: 0
        }
    }

    func format(_ value: Double) -> String {
        if isBoolean { return value > 0.5 ? "ON" : "OFF" }
        return value.formatted(.number.precision(.fractionLength(fractionDigits)))
    }

    /// Picker grouping only; has no effect on decoding or display.
    var group: MetricGroup {
        switch self {
        case .speed, .rpm, .throttle, .relThrottle, .absThrottleB, .accelPedalD,
             .accelPedalE, .cmdThrottle, .engineLoad, .absLoad: .motion
        case .steeringAngle, .steeringTorque: .steering
        case .coolant, .intakeAir, .ambient: .temperature
        case .map, .baro, .timingAdvance, .shortTrim, .longTrim, .equivRatio,
             .fuelRail: .fuelling
        case .fuelLevel, .fuelLitres, .odometer, .distClear, .runTime, .warmups: .trip
        case .voltage, .dtcCount, .distMil, .timeMil, .acCompressor, .checkEngine: .status
        }
    }
}

enum MetricGroup: String, CaseIterable, Identifiable {
    case motion = "Motion & Driver Input"
    case steering = "Steering"
    case temperature = "Temperatures"
    case fuelling = "Fuelling & Air"
    case trip = "Fuel, Distance & Time"
    case status = "Electrical & Faults"

    var id: String { rawValue }

    var metrics: [VehicleMetric] { VehicleMetric.allCases.filter { $0.group == self } }
}

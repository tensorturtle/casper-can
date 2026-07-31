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

    // Rates of change. Not on the wire: they need two frames, so `BLEClient`
    // stamps them when it decodes a new frame against the previous one. Kept on
    // the frame so `VehicleMetric.value(from:)` stays a pure function.
    var accelMps2: Double = 0
    var steeringRateDegPerS: Double = 0

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


/// Constants for the derived quantities that need an engine model.
///
/// These are the assumptions that make `estMaf` and everything downstream of it an
/// **estimate** rather than a measurement. Displacement is this car's; volumetric
/// efficiency is a flat guess, and the single largest source of error.
enum EngineModel {
    /// Casper 1.0 T-GDI, 998 cc.
    static let displacementLitres = 0.998

    /// Flat volumetric efficiency. A real VE varies with rpm and load across
    /// roughly 0.7–1.0; using one number trades accuracy for not needing a map we
    /// do not have. Errors here scale air and fuel estimates proportionally.
    static let volumetricEfficiency = 0.90

    /// Specific gas constant for dry air, J/(kg·K).
    static let airGasConstant = 287.05

    /// Stoichiometric air-fuel ratio for petrol, by mass.
    static let stoichAfr = 14.7

    /// Petrol density, g/L. Varies with blend and temperature; ±3% is normal.
    static let fuelDensityGPerLitre = 745.0

    static let kpaToPsi = 0.1450377
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
    // Derived — computed here from the signals above, never sent on the wire.
    // See `isEstimate` for the ones that rest on modelling assumptions.
    case boost, boostBar, intakeAirRise, totalTrim, chargeAirDensity
    case estMaf, estFuelRate, estEconomy, estRange
    case speedPerThousandRpm, throttleVsPedal
    case acceleration, steeringRate

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
        case .boost: "Boost"
        case .boostBar: "Boost (bar)"
        case .intakeAirRise: "Intake Rise"
        case .totalTrim: "Total Fuel Trim"
        case .chargeAirDensity: "Charge Density"
        case .estMaf: "Air Flow (est.)"
        case .estFuelRate: "Fuel Rate (est.)"
        case .estEconomy: "Economy (est.)"
        case .estRange: "Range (est.)"
        case .speedPerThousandRpm: "Speed / 1000 rpm"
        case .throttleVsPedal: "Throttle vs Pedal"
        case .acceleration: "Acceleration"
        case .steeringRate: "Steering Rate"
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
        case .boost: "psi"
        case .boostBar: "bar"
        case .intakeAirRise: "°C"
        case .totalTrim: "%"
        case .chargeAirDensity: "g/L"
        case .estMaf: "g/s"
        case .estFuelRate: "L/h"
        case .estEconomy: "L/100km"
        case .estRange: "km"
        case .speedPerThousandRpm: "km/h"
        case .throttleVsPedal: "%"
        case .acceleration: "m/s²"
        case .steeringRate: "°/s"
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
        case .boost, .boostBar: "gauge.open.with.lines.needle.84percent.exclamation"
        case .intakeAirRise: "thermometer.variable"
        case .totalTrim: "plusminus"
        case .chargeAirDensity: "aqi.medium"
        case .estMaf: "wind"
        case .estFuelRate: "drop"
        case .estEconomy: "leaf"
        case .estRange: "point.topleft.down.to.point.bottomright.curvepath"
        case .speedPerThousandRpm: "figure.walk.motion"
        case .throttleVsPedal: "arrow.left.arrow.right"
        case .acceleration: "arrow.up.forward"
        case .steeringRate: "arrow.triangle.turn.up.right.diamond"
        }
    }

    /// Which validity bits this metric needs. A base signal needs exactly one;
    /// a derived one needs every input it is computed from, so it reads "no data"
    /// unless *all* of them answered. Mirrors `VALID_*` in wire.py — signals that
    /// arrive from one request share a bit.
    var requiredValidity: UInt32 {
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

        // Derived: the union of their inputs' bits.
        case .boost, .boostBar, .chargeAirDensity:
            VehicleMetric.map.requiredValidity | VehicleMetric.baro.requiredValidity
                | (self == .chargeAirDensity ? VehicleMetric.intakeAir.requiredValidity : 0)
        case .intakeAirRise:
            VehicleMetric.intakeAir.requiredValidity | VehicleMetric.ambient.requiredValidity
        case .totalTrim:
            VehicleMetric.shortTrim.requiredValidity | VehicleMetric.longTrim.requiredValidity
        case .estMaf:
            VehicleMetric.rpm.requiredValidity | VehicleMetric.map.requiredValidity
                | VehicleMetric.intakeAir.requiredValidity
        case .estFuelRate:
            VehicleMetric.estMaf.requiredValidity | VehicleMetric.equivRatio.requiredValidity
        case .estEconomy:
            VehicleMetric.estFuelRate.requiredValidity | VehicleMetric.speed.requiredValidity
        case .estRange:
            VehicleMetric.estEconomy.requiredValidity | VehicleMetric.fuelLitres.requiredValidity
        case .speedPerThousandRpm:
            VehicleMetric.speed.requiredValidity | VehicleMetric.rpm.requiredValidity
        case .throttleVsPedal:
            VehicleMetric.cmdThrottle.requiredValidity | VehicleMetric.accelPedalD.requiredValidity
        case .acceleration: VehicleMetric.speed.requiredValidity
        case .steeringRate: VehicleMetric.steeringAngle.requiredValidity
        }
    }

    /// True for values that rest on modelling assumptions rather than being a
    /// measured signal. Surfaced in the UI, because docs/04 §2.1 records that this
    /// vehicle publishes **no** instantaneous fuel-flow signal — these are a
    /// speed-density model, not a reading, and must never be cited as a finding.
    var isEstimate: Bool {
        switch self {
        case .estMaf, .estFuelRate, .estEconomy, .estRange: true
        default: false
        }
    }

    /// True for anything computed in the app rather than carried on the wire.
    var isDerived: Bool {
        switch self {
        case .boost, .boostBar, .intakeAirRise, .totalTrim, .chargeAirDensity,
             .estMaf, .estFuelRate, .estEconomy, .estRange,
             .speedPerThousandRpm, .throttleVsPedal, .acceleration, .steeringRate: true
        default: false
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
        case .steeringAngle, .steeringTorque, .shortTrim, .longTrim, .timingAdvance,
             .boost, .boostBar, .totalTrim, .throttleVsPedal, .acceleration,
             .steeringRate, .intakeAirRise: true
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

        // Gauge boost: both PIDs are ABSOLUTE pressure, so the difference is
        // pressure relative to ambient. Negative is manifold vacuum, which is the
        // normal off-throttle state — hence a bipolar gauge.
        case .boost: (f.mapKpa - f.baroKpa) * EngineModel.kpaToPsi
        case .boostBar: (f.mapKpa - f.baroKpa) / 100.0

        /// How much the intake charge is above ambient — heat soak and, on a turbo,
        /// how much work the charge cooling is not doing.
        case .intakeAirRise: f.intakeAirC - f.ambientC

        /// Short + long trim. The conventional diagnostic reading: sustained large
        /// total trim points at a metering or air-leak fault.
        case .totalTrim: f.shortTrimPct + f.longTrimPct

        /// Charge air density from the ideal gas law, ρ = P / (R·T), in g/L.
        /// Absolute MAP and intake temperature, so this is the density of what is
        /// actually entering the cylinders.
        case .chargeAirDensity:
            f.intakeAirC > -273 ? (f.mapKpa * 1000)
                / (EngineModel.airGasConstant * (f.intakeAirC + 273.15)) : 0

        /// Speed-density mass air flow, g/s. This car has no MAF sensor
        /// (docs/04 §2.1), so this is modelled: volumetric flow at the manifold,
        /// times charge density, times an assumed VE. A four-stroke fills its
        /// displacement once per two crank revolutions, hence rpm/120 in rev/s.
        case .estMaf:
            VehicleMetric.chargeAirDensity.value(from: f) / 1000.0        // kg/m³
                * (f.rpm / 120.0)                                        // fill events/s
                * (EngineModel.displacementLitres / 1000.0)              // m³ per fill
                * EngineModel.volumetricEfficiency
                * 1000.0                                                 // kg -> g

        /// Fuel mass flow from air flow and commanded lambda, converted to L/h.
        /// Uses commanded equivalence ratio rather than assuming stoichiometric,
        /// so enrichment under load is reflected.
        case .estFuelRate:
            f.equivRatio > 0.1
                ? VehicleMetric.estMaf.value(from: f)
                    / (EngineModel.stoichAfr * f.equivRatio)              // g/s fuel
                    / EngineModel.fuelDensityGPerLitre * 3600.0           // -> L/h
                : 0

        /// Instantaneous consumption. Undefined at rest — at 0 km/h the car is
        /// burning fuel per unit time but covering no distance, so this reports 0
        /// rather than infinity, and the tile should be read with that in mind.
        case .estEconomy:
            f.speedKph > 1
                ? VehicleMetric.estFuelRate.value(from: f) / f.speedKph * 100.0
                : 0

        /// Remaining range from the cluster's fuel quantity and current economy.
        /// Doubly approximate: the economy is modelled, and the fuel level sloshes
        /// (docs/04 §4.2 measured a 3.6-point swing during one drive).
        case .estRange:
            {
                let economy = VehicleMetric.estEconomy.value(from: f)
                return economy > 0.1 ? f.fuelLitres / economy * 100.0 : 0
            }()

        /// Road speed per 1000 rpm — a direct proxy for the current overall gear
        /// ratio. Rising in steps as the transmission shifts. Not converted to a
        /// gear number: that needs ratio data this project has not measured.
        case .speedPerThousandRpm: f.rpm > 200 ? f.speedKph / f.rpm * 1000.0 : 0

        /// Commanded throttle minus pedal. A persistent negative gap means the ECM
        /// is giving less throttle than asked — torque limiting, traction control,
        /// or a protection mode.
        case .throttleVsPedal: f.cmdThrottlePct - f.accelDPct

        // Rates, stamped by BLEClient from consecutive frames.
        case .acceleration: f.accelMps2
        case .steeringRate: f.steeringRateDegPerS
        }
    }

    func isValid(in frame: TelemetryFrame) -> Bool {
        let mask = requiredValidity
        // ALL required bits, not any: a derived value from a half-answered set
        // would be quietly wrong, which is worse than showing "no data".
        return mask != 0 && frame.validity & mask == mask
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
        // 1.0 T-GDI runs roughly 1 bar of boost, so ±15 psi covers vacuum to peak.
        case .boost: -15...15
        case .boostBar: -1...1.2
        case .intakeAirRise: -10...60
        case .totalTrim: -25...25
        case .chargeAirDensity: 0...3000
        case .estMaf: 0...120
        case .estFuelRate: 0...25
        case .estEconomy: 0...30
        case .estRange: 0...700
        case .speedPerThousandRpm: 0...60
        case .throttleVsPedal: -50...50
        case .acceleration: -6...6
        case .steeringRate: -400...400
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
        case .boost, .boostBar, .throttleVsPedal, .acceleration, .steeringRate,
             .totalTrim, .intakeAirRise: .linear
        case .estMaf, .estFuelRate, .estEconomy, .estRange, .chargeAirDensity,
             .speedPerThousandRpm: .number
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
        case .boost: 14            // ~1 bar; above this is beyond stock boost
        case .boostBar: 1.0
        case .intakeAirRise: 40    // sustained charge heat soak
        case .totalTrim: 10        // same threshold as the individual trims
        default: nil
        }
    }

    var fractionDigits: Int {
        switch self {
        case .equivRatio: 3
        case .voltage, .boostBar, .acceleration: 2
        case .boost, .estFuelRate, .estEconomy, .speedPerThousandRpm,
             .intakeAirRise, .totalTrim, .throttleVsPedal: 1
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
        case .boost, .boostBar, .intakeAirRise, .totalTrim, .chargeAirDensity,
             .estMaf, .estFuelRate, .estEconomy, .estRange,
             .speedPerThousandRpm, .throttleVsPedal, .acceleration, .steeringRate: .derived
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
    case derived = "Derived & Estimated"

    var id: String { rawValue }

    var metrics: [VehicleMetric] { VehicleMetric.allCases.filter { $0.group == self } }
}

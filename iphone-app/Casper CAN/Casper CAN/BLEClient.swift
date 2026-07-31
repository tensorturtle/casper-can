//  BLEClient.swift
//  CoreBluetooth central that talks to the Radxa appliance.
//
//  Scans by service UUID rather than by local name, so renaming the board with
//  `--name` does not break discovery.

import Foundation
import CoreBluetooth
import Observation

@Observable
final class BLEClient: NSObject {
    enum State: Equatable {
        case unknown
        case unauthorized
        case poweredOff
        case scanning
        case connecting(String)
        case connected(String)
        case disconnected(reason: String?)

        var label: String {
            switch self {
            case .unknown: "Starting up"
            case .unauthorized: "Bluetooth access needed"
            case .poweredOff: "Bluetooth is off"
            case .scanning: "Looking for \(Wire.defaultLocalName)"
            case .connecting(let name): "Connecting to \(name)"
            case .connected(let name): "Connected to \(name)"
            // A drop is followed immediately by another scan, so describing it as
            // "searching again" is both accurate and less alarming than the raw
            // CoreBluetooth reason, which is usually "peer removed pairing".
            case .disconnected: "Reconnecting…"
            }
        }

        var isConnected: Bool {
            if case .connected = self { return true }
            return false
        }
    }

    private(set) var state: State = .unknown
    private(set) var frame: TelemetryFrame = .zero
    private(set) var status: ApplianceStatus?

    /// Set when the board's wire version doesn't match ours. Surfaced in the UI
    /// instead of decoding garbage into plausible-looking numbers.
    private(set) var incompatibleVersion: Int?

    /// Rolling notification rate, for judging whether BLE throughput is adequate.
    private(set) var samplesPerSecond: Double = 0

    /// Frames that failed to decode — a wrong-length payload, i.e. a wire
    /// mismatch. Non-zero means the numbers on screen cannot be trusted.
    private(set) var malformedFrames = 0

    /// True once any frame has been decoded. Gates the waiting screen: before the
    /// first frame a grid of empty tiles reads as broken, but after one has arrived
    /// the tiles are worth keeping on screen through a drop, dimmed, because the
    /// last known readings beat being told there are none.
    private(set) var hasReceivedFrame = false

    /// Optional sink for every decoded frame. Set by the dashboard so a recording
    /// captures samples as they arrive rather than at screen-refresh rate.
    var onFrame: ((TelemetryFrame) -> Void)?

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var telemetryChar: CBCharacteristic?

    private var recentArrivals: [Date] = []

    /// Recent samples, for computing rates across a window rather than between
    /// consecutive frames. See `stampRates`.
    private var history: [(uptimeMs: Double, speedKph: Double, angleDeg: Double)] = []

    /// Target span to differentiate over. The speed PID reports whole km/h, so at
    /// 20-30 Hz a frame-to-frame difference is either 0 or a 1 km/h jump - which
    /// differentiates to an 8 m/s² spike. Half a second of window turns that
    /// quantisation into a usable reading, at the cost of a little lag.
    private static let rateWindowSeconds = 0.5

    /// Kept so rates of change can be stamped onto each new frame.
    private var previousFrame: TelemetryFrame?

    override init() {
        super.init()
        // Delegate callbacks land on the main queue so the @Observable mutations
        // below are already on the actor SwiftUI observes.
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func startScan() {
        guard central.state == .poweredOn else { return }
        state = .scanning
        central.scanForPeripherals(withServices: [Wire.service])
    }

    func disconnect() {
        if let peripheral { central.cancelPeripheralConnection(peripheral) }
    }

    /// Drop the link and look again. Useful after moving the phone out of range,
    /// where iOS may otherwise sit on a stale connection.
    ///
    /// Also clears the app-side counters, because they describe the *previous*
    /// session: carrying a malformed-frame count across a deliberate reset would
    /// keep warning about a problem the user has just acted on.
    func reconnect() {
        malformedFrames = 0
        incompatibleVersion = nil
        frame = .zero
        previousFrame = nil
        history.removeAll()
        // A deliberate reset should start from a clean slate, waiting screen and
        // all - unlike an incidental drop, which keeps the last readings visible.
        hasReceivedFrame = false
        disconnect()
        startScan()
    }

    /// Fill in the derivative fields from the previous frame.
    ///
    /// Uses the board's own monotonic uptime for the interval, not arrival times:
    /// BLE delivery jitter would otherwise show up as phantom acceleration. At the
    /// default 1 Hz notification rate these are coarse — raise `--interval` on the
    /// appliance if you need finer resolution.
    private func stampRates(on frame: inout TelemetryFrame, previous: TelemetryFrame?) {
        let now = Double(frame.uptimeMilliseconds) / 1000

        // A backwards clock means the board restarted; start the window again
        // rather than differentiating across the discontinuity.
        if let last = history.last, now < last.uptimeMs {
            history.removeAll()
        }

        history.append((now, frame.speedKph, frame.steeringAngleDeg))
        // Keep a little more than the window so there is always a sample old
        // enough to use.
        history.removeAll { now - $0.uptimeMs > Self.rateWindowSeconds * 2 }

        // The oldest sample at least a window old; failing that, the oldest we
        // have. Before the window fills this yields a shorter span, which is why
        // the first half-second reads near zero rather than wrong.
        guard let reference = history.first(where: { now - $0.uptimeMs >= Self.rateWindowSeconds })
                ?? history.first,
              case let dt = now - reference.uptimeMs,
              dt > 0.05
        else { return }

        if VehicleMetric.speed.isValid(in: frame) {
            // km/h -> m/s before differentiating.
            frame.accelMps2 = ((frame.speedKph - reference.speedKph) / 3.6) / dt
        }
        if VehicleMetric.steeringAngle.isValid(in: frame) {
            frame.steeringRateDegPerS = (frame.steeringAngleDeg - reference.angleDeg) / dt
        }
    }

    private func noteArrival() {
        let now = Date.now
        recentArrivals.append(now)
        recentArrivals.removeAll { now.timeIntervalSince($0) > 3 }
        // Divide by the observed window rather than a constant 3 s, so the rate
        // is meaningful immediately instead of ramping up over the first window.
        if let first = recentArrivals.first, recentArrivals.count > 1 {
            let span = now.timeIntervalSince(first)
            samplesPerSecond = span > 0 ? Double(recentArrivals.count - 1) / span : 0
        }
    }
}

extension BLEClient: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn: startScan()
        case .poweredOff: state = .poweredOff
        case .unauthorized: state = .unauthorized
        default: state = .unknown
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        central.stopScan()
        self.peripheral = peripheral
        peripheral.delegate = self
        let name = peripheral.name ?? Wire.defaultLocalName
        state = .connecting(name)
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        state = .connected(peripheral.name ?? Wire.defaultLocalName)
        peripheral.discoverServices([Wire.service])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        state = .disconnected(reason: error?.localizedDescription)
        startScan()
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        telemetryChar = nil
        status = nil
        previousFrame = nil
        history.removeAll()
        samplesPerSecond = 0
        recentArrivals.removeAll()
        state = .disconnected(reason: error?.localizedDescription)
        // The appliance is a fixed installation in the car, so an unexpected drop
        // is almost always range or a board restart. Scanning again immediately
        // is the right default.
        startScan()
    }
}

extension BLEClient: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let service = peripheral.services?.first(where: { $0.uuid == Wire.service }) else {
            return
        }
        peripheral.discoverCharacteristics([Wire.telemetry, Wire.status], for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        for char in service.characteristics ?? [] {
            switch char.uuid {
            case Wire.telemetry:
                telemetryChar = char
                // Read once so the dashboard renders immediately, rather than
                // showing zeroes until the first notification lands.
                peripheral.readValue(for: char)
                peripheral.setNotifyValue(true, for: char)
            case Wire.status:
                peripheral.readValue(for: char)
            default:
                break
            }
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        guard error == nil, let data = characteristic.value else { return }

        switch characteristic.uuid {
        case Wire.telemetry:
            guard var decoded = TelemetryFrame(payload: data) else {
                // Wrong length almost always means a wire-version mismatch the
                // status read has not surfaced yet. Count it rather than
                // silently ignoring it.
                malformedFrames += 1
                return
            }
            stampRates(on: &decoded, previous: previousFrame)
            previousFrame = decoded
            hasReceivedFrame = true
            frame = decoded
            noteArrival()
            onFrame?(decoded)

        case Wire.status:
            guard let decoded = try? JSONDecoder().decode(ApplianceStatus.self, from: data) else {
                return
            }
            status = decoded
            incompatibleVersion = decoded.isCompatible ? nil : decoded.wireVersion

        default:
            break
        }
    }
}

//  Recorder.swift
//  Records received frames to a CSV file, so a drive produces evidence.
//
//  The column set deliberately matches the fields of the wire frame rather than
//  whatever is on screen: a recording should capture everything the board sent,
//  not the subset the dashboard happened to be showing.
//
//  Files land in the app's Documents directory and are exportable with the share
//  sheet, which is how they get off the phone and next to
//  ../../../experimentation/captures/journeys/ for comparison against the Mac
//  tools' own recordings.

import Foundation
import Observation

@Observable
final class Recorder {
    private(set) var isRecording = false
    private(set) var sampleCount = 0
    private(set) var startedAt: Date?
    private(set) var currentURL: URL?

    /// Set when a write fails. Surfaced in the UI — a recording that silently
    /// stopped is worse than one that never started.
    private(set) var lastError: String?

    private var handle: FileHandle?

    /// Frames arrive about once a second, so buffering keeps this off the
    /// notification path without risking much data on a crash.
    private var buffer = Data()
    private static let flushThreshold = 8 * 1024

    private static let header =
        "iso_time,uptime_ms,speed_kph,rpm,steer_angle_deg,steer_torque,coolant_c,"
        + "engine_load_pct,throttle_pct,fuel_level_pct,ac_on,mil_on,validity,poll_errors\n"

    static var documentsDirectory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    /// Recordings on disk, newest first.
    static func existingRecordings() -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: documentsDirectory,
            includingPropertiesForKeys: [.contentModificationDateKey]
        )) ?? []
        return files
            .filter { $0.pathExtension == "csv" }
            .sorted {
                let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]))?
                    .contentModificationDate ?? .distantPast
                let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]))?
                    .contentModificationDate ?? .distantPast
                return a > b
            }
    }

    func start() {
        guard !isRecording else { return }
        lastError = nil

        // Colons are legal in a POSIX filename but awkward everywhere else, so
        // the timestamp is filesystem-safe rather than strictly ISO 8601. Built
        // from components rather than a format string: sortable, locale-proof,
        // and matching the journey_YYYYMMDD_HHMMSS convention the Mac tools use
        // in experimentation/captures/journeys/.
        let parts = Calendar.current.dateComponents(
            [.year, .month, .day, .hour, .minute, .second], from: .now
        )
        let stamp = String(
            format: "%04d%02d%02d_%02d%02d%02d",
            parts.year ?? 0, parts.month ?? 0, parts.day ?? 0,
            parts.hour ?? 0, parts.minute ?? 0, parts.second ?? 0
        )
        let url = Self.documentsDirectory.appending(path: "casper_\(stamp).csv")

        guard FileManager.default.createFile(atPath: url.path, contents: nil) else {
            lastError = "could not create \(url.lastPathComponent)"
            return
        }
        guard let handle = try? FileHandle(forWritingTo: url) else {
            lastError = "could not open \(url.lastPathComponent) for writing"
            return
        }

        self.handle = handle
        currentURL = url
        buffer = Data(Self.header.utf8)
        sampleCount = 0
        startedAt = .now
        isRecording = true
    }

    func stop() {
        guard isRecording else { return }
        flush()
        try? handle?.close()
        handle = nil
        isRecording = false
    }

    func toggle() {
        isRecording ? stop() : start()
    }

    /// Append one frame. Called from the BLE notification path, so it must be cheap.
    func record(_ frame: TelemetryFrame) {
        guard isRecording else { return }

        let row = [
            frame.receivedAt.formatted(.iso8601),
            String(frame.uptimeMilliseconds),
            fmt(frame.speedKph, 2),
            fmt(frame.rpm, 0),
            fmt(frame.steeringAngleDeg, 1),
            fmt(frame.steeringTorque, 0),
            fmt(frame.coolantC, 0),
            fmt(frame.engineLoadPct, 0),
            fmt(frame.throttlePct, 0),
            fmt(frame.fuelLevelPct, 2),
            frame.acCompressorOn ? "1" : "0",
            frame.milOn ? "1" : "0",
            // Hex so a validity set is readable at a glance against wire.py's bits.
            "0x" + String(frame.validity, radix: 16),
            String(frame.pollErrors),
        ].joined(separator: ",") + "\n"

        buffer.append(contentsOf: row.utf8)
        sampleCount += 1

        if buffer.count >= Self.flushThreshold { flush() }
    }

    private func flush() {
        guard !buffer.isEmpty, let handle else { return }
        do {
            try handle.write(contentsOf: buffer)
            buffer.removeAll(keepingCapacity: true)
        } catch {
            lastError = error.localizedDescription
            // Stop rather than spin on a failing write — a disk-full recording
            // that keeps "recording" is a trap.
            isRecording = false
        }
    }

    private func fmt(_ value: Double, _ digits: Int) -> String {
        String(format: "%.\(digits)f", value)
    }

    var elapsedDescription: String {
        guard let startedAt else { return "—" }
        let seconds = Int(Date.now.timeIntervalSince(startedAt))
        return String(format: "%d:%02d", seconds / 60, seconds % 60)
    }
}

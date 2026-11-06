//
//  JeepAlerts.swift
//  Casper CAN
//
//  The Jeep low-range notification, and the app-lifetime objects it needs.
//
//  The alert has to work with the app closed and the phone locked, which shapes
//  everything here. iOS relaunches the app in the background when the board
//  connects (state restoration + `bluetooth-central`), but a background launch
//  never draws a view - so nothing the alert depends on may live in a view's
//  @State. The Bluetooth client, the recorder and the fill-up log are created
//  once, at launch, in `AppServices`, and the views borrow them.

import Foundation
import UIKit
import UserNotifications

/// Objects that must exist from launch, whether or not any screen is drawn.
final class AppServices {
    static let shared = AppServices()

    let ble = BLEClient()
    let recorder = Recorder()
    let fuelLog = FuelLog()
    let alerter: RangeAlerter

    private init() {
        alerter = RangeAlerter(log: fuelLog)
        // Every frame, as it arrives - in the foreground or the background.
        ble.onFrame = { [recorder, alerter] frame in
            recorder.record(frame)
            alerter.observe(frame)
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Create the Bluetooth client now: state restoration delivers its event
        // to the central manager that exists at launch, and to no other.
        _ = AppServices.shared
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    /// Show the alert even with the app open - it may be on the dash, on the Jeep
    /// screen, and a banner with sound is the point.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}

/// Posts a notification when the estimated range left drops past a threshold.
///
/// At most once per drive per level, so a drive that starts already low does
/// not repeat itself at every frame. A "drive" begins when the odometer becomes
/// readable after more than `newDriveAfter` without it - true whether the board
/// is powered with the ignition (the usual case) or stays up with the car off.
final class RangeAlerter {
    enum Level: Int, Comparable, CaseIterable {
        case low = 1, veryLow, past

        static func < (a: Level, b: Level) -> Bool { a.rawValue < b.rawValue }
    }

    let log: FuelLog
    private var alerted: Set<Level> = []
    private var lastOdometerAt: Date?
    private static let newDriveAfter: TimeInterval = 5 * 60

    init(log: FuelLog) {
        self.log = log
    }

    func observe(_ frame: TelemetryFrame) {
        let mode = UserDefaults.standard.string(forKey: VehicleMode.storageKey)
        guard mode == VehicleMode.jeep.rawValue,
              VehicleMetric.odometer.isValid(in: frame) else { return }

        let km = Int(frame.odometerKm)
        let now = Date.now
        if let last = lastOdometerAt, now.timeIntervalSince(last) < Self.newDriveAfter {
            // Same drive.
        } else {
            alerted.removeAll()
        }
        lastOdometerAt = now
        log.observe(odometerKm: km)

        guard log.alertsEnabled,
              let left = log.remainingKm(currentKm: km),
              let level = level(forRemaining: left),
              !alerted.contains(level) else { return }

        // Mark every level up to this one: starting a drive already very low
        // should say so once, not also announce "low" afterwards.
        for l in Level.allCases where l <= level { alerted.insert(l) }
        post(level, remainingKm: left, sinceFillUpKm: log.kmSinceFillUp(currentKm: km) ?? 0)
    }

    private func level(forRemaining left: Int) -> Level? {
        let threshold = log.alertThresholdKm
        if left <= 0 { return .past }
        if left <= threshold / 2 { return .veryLow }
        if left <= threshold { return .low }
        return nil
    }

    private func post(_ level: Level, remainingKm left: Int, sinceFillUpKm since: Int) {
        let content = UNMutableNotificationContent()
        switch level {
        case .low:
            content.title = String(localized: "Jeep: fill up soon")
            content.body = String(localized: "About \(left) km left on your range estimate.")
        case .veryLow:
            content.title = String(localized: "Jeep: fuel very low")
            content.body = String(localized: "About \(left) km left on your range estimate. Fill up now.")
        case .past:
            content.title = String(localized: "Jeep: past your range estimate")
            content.body = String(localized: "\(since) km driven since filling up. Fill up now.")
        }
        content.sound = .default
        // One identifier, so a newer alert replaces an older one rather than
        // stacking up in Notification Centre.
        let request = UNNotificationRequest(identifier: "jeep-range", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    /// Ask once. iOS shows its prompt only the first time; later calls are
    /// silent and harmless.
    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }
}

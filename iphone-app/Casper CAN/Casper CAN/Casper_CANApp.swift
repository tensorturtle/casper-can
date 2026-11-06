//
//  Casper_CANApp.swift
//  Casper CAN
//
//  Created by tensorturtle on 7/31/26.
//

import SwiftUI

@main
struct Casper_CANApp: App {
    // Creates AppServices at launch, so a background relaunch by Bluetooth state
    // restoration has a central manager to deliver to. See JeepAlerts.swift.
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

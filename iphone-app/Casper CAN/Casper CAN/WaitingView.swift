//  WaitingView.swift
//  Shown before the first frame ever arrives, instead of a grid of dead tiles.
//
//  A dashboard of 34 question marks reads as "broken". It is almost never broken:
//  the usual cases are the appliance not powered yet, the phone out of range, or
//  the ignition off. So this state is presented as *waiting* rather than failing —
//  calm colours, a slow ripple, and a sentence explaining what will happen next.
//
//  Once a frame has arrived the tiles take over for good. A later drop keeps the
//  last values on screen, dimmed, rather than returning here: seeing the readings
//  you had a moment ago is more useful than being told you have none.

import SwiftUI

struct WaitingView: View {
    @Environment(\.appearance) private var appearance
    let state: BLEClient.State
    let onOpenSettings: () -> Void

    /// Drives the ripple. Flipped once on appear; `repeatForever` does the rest.
    @State private var rippling = false

    private var needsSettings: Bool {
        switch state {
        case .poweredOff, .unauthorized: true
        default: false
        }
    }

    private var symbol: String {
        switch state {
        case .poweredOff, .unauthorized: "bolt.horizontal.circle"
        default: "car.side.and.exclamationmark"
        }
    }

    private var title: String {
        switch state {
        case .poweredOff: "Bluetooth is off"
        case .unauthorized: "Bluetooth access needed"
        case .connecting: "Connecting…"
        default: "Looking for \(Wire.defaultLocalName)"
        }
    }

    private var detail: String {
        switch state {
        case .poweredOff:
            "Turn Bluetooth on and this will connect on its own."
        case .unauthorized:
            "Allow Bluetooth for this app in Settings, then come back."
        default:
            """
            The appliance advertises by itself as soon as it has power — nothing \
            to press. The ignition doesn't need to be on either; signals will \
            read “no data” until the car is awake.
            """
        }
    }

    /// Calm rather than alarming: searching is the normal state on startup, so it
    /// uses the accent colour. Orange is reserved for something actually wrong.
    private var tint: Color {
        needsSettings ? .orange : appearance.accent
    }

    var body: some View {
        VStack(spacing: 16) {
            ripple

            Text(title)
                .font(.title3.weight(.semibold))
                .fontDesign(appearance.typeface.design)

            Text(detail)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 290)

            if needsSettings {
                Button("Open Settings", action: onOpenSettings)
                    .buttonStyle(.bordered)
                    .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 48)
        .padding(.bottom, 24)
        .onAppear { rippling = true }
    }

    /// Three expanding rings on a stagger, so the pulse never fully empties. Slow
    /// and low-contrast on purpose — this sits on screen for as long as it takes,
    /// and anything brisker would read as urgency.
    private var ripple: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .stroke(tint.opacity(0.4), lineWidth: 1.5)
                    .frame(width: 92, height: 92)
                    .scaleEffect(rippling ? 1.9 : 0.55)
                    .opacity(rippling ? 0 : 0.9)
                    .animation(
                        .easeOut(duration: 2.6)
                            .repeatForever(autoreverses: false)
                            .delay(Double(index) * 0.85),
                        value: rippling
                    )
            }

            Circle()
                .fill(tint.opacity(0.12))
                .frame(width: 92, height: 92)

            Image(systemName: symbol)
                .font(.system(size: 32, weight: .light))
                .foregroundStyle(tint)
        }
        .frame(height: 180)
        // Decorative; the title and detail carry the meaning.
        .accessibilityHidden(true)
    }
}

#Preview("Searching") {
    WaitingView(state: .scanning) {}
}

#Preview("Bluetooth off") {
    WaitingView(state: .poweredOff) {}
}

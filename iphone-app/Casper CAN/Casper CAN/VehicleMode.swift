//
//  VehicleMode.swift
//  Casper CAN
//
//  Which car the app is for, and which icon it wears.
//
//  The mode is the user's choice, set at the top of Settings. The board also
//  reports which car it is decoding (`ApplianceStatus.vehicle`); when the two
//  disagree the dashboard says so and offers to switch, rather than switching
//  silently underneath the driver.

import SwiftUI
import UIKit

enum VehicleMode: String, CaseIterable, Identifiable {
    case casper, jeep

    var id: String { rawValue }

    /// Persisted with @AppStorage under this key.
    static let storageKey = "vehicleMode"

    var title: LocalizedStringKey {
        switch self {
        case .casper: "Casper"
        case .jeep: "Jeep"
        }
    }

    /// The mode matching what a board reports. Boards older than wire v4 report
    /// no vehicle, and only ever served the Casper.
    init(boardVehicle: String?) {
        self = VehicleMode(rawValue: boardVehicle ?? "casper") ?? .casper
    }
}

/// The selectable home-screen icons. Generated from committed prompts by
/// `iphone-app/icons/generate_icons.py`; each has an `.appiconset` for the icon
/// and an `IconPreview-*.imageset`, because an app cannot load its own
/// alternate icons as images.
enum AppIconChoice: String, CaseIterable, Identifiable {
    case obdPlug, gauge, waveform, fuel, grille

    var id: String { rawValue }

    /// nil is the primary icon, `AppIcon`.
    var alternateName: String? {
        switch self {
        case .obdPlug: nil
        case .gauge: "AppIcon-Gauge"
        case .waveform: "AppIcon-Waveform"
        case .fuel: "AppIcon-Fuel"
        case .grille: "AppIcon-Grille"
        }
    }

    var previewImage: String {
        switch self {
        case .obdPlug: "IconPreview-obd-plug"
        case .gauge: "IconPreview-gauge"
        case .waveform: "IconPreview-waveform-road"
        case .fuel: "IconPreview-fuel"
        case .grille: "IconPreview-grille"
        }
    }

    var title: LocalizedStringKey {
        switch self {
        case .obdPlug: "Diagnostic Plug"
        case .gauge: "Gauge"
        case .waveform: "Signal Road"
        case .fuel: "Fuel"
        case .grille: "Grille"
        }
    }

    static var current: AppIconChoice {
        let name = UIApplication.shared.alternateIconName
        return allCases.first { $0.alternateName == name } ?? .obdPlug
    }
}

struct AppIconView: View {
    @Environment(\.appearance) private var appearance
    @State private var selected = AppIconChoice.current
    @State private var failure: String?

    private let columns = [GridItem(.adaptive(minimum: 96), spacing: 16)]

    var body: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 20) {
                ForEach(AppIconChoice.allCases) { choice in
                    Button {
                        apply(choice)
                    } label: {
                        VStack(spacing: 8) {
                            Image(choice.previewImage)
                                .resizable()
                                .scaledToFit()
                                .frame(width: 80, height: 80)
                                // Approximates the home-screen mask.
                                .clipShape(.rect(cornerRadius: 18, style: .continuous))
                                .overlay {
                                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                                        .strokeBorder(appearance.accent,
                                                      lineWidth: selected == choice ? 3 : 0)
                                        .padding(-5)
                                }
                            Text(choice.title)
                                .font(.caption)
                                .foregroundStyle(selected == choice ? .primary : .secondary)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding()

            if let failure {
                Text(failure)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .padding(.horizontal)
            }
        }
        .navigationTitle("App Icon")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func apply(_ choice: AppIconChoice) {
        guard choice != selected else { return }
        failure = nil
        UIApplication.shared.setAlternateIconName(choice.alternateName) { error in
            Task { @MainActor in
                if let error {
                    failure = error.localizedDescription
                } else {
                    selected = choice
                }
            }
        }
    }
}

#Preview {
    NavigationStack { AppIconView() }
}

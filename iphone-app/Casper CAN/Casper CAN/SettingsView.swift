//  SettingsView.swift
//  One sheet: which car, then what is shown and how it looks.
//
//  The dashboard has a single settings button rather than one per area. The top
//  strip is competing directly with the gauges for height, so one slightly larger
//  and easier-to-hit target beats two tiny ones — and the split lives here, where
//  space is free.

import SwiftUI

struct SettingsView: View {
    let config: DashboardConfig
    @Environment(\.appearance) private var appearance
    @Environment(\.dismiss) private var dismiss
    @AppStorage(VehicleMode.storageKey) private var mode = VehicleMode.casper

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Vehicle", selection: $mode) {
                        ForEach(VehicleMode.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("Vehicle")
                } footer: {
                    Text(mode == .casper
                         ? String(localized: "The live dashboard of measurement tiles.")
                         : String(localized: "Distance since the last fill-up, from the Jeep's odometer."))
                }

                Section {
                    // Tiles are the Casper dashboard; Jeep mode has a fixed screen.
                    if mode == .casper {
                        NavigationLink {
                            MetricPickerView(config: config)
                        } label: {
                            row(
                                String(localized: "Metrics"),
                                detail: config.heroMetric.map {
                                    String(localized: "\(config.tiles.count) shown, hero: \($0.title)")
                                } ?? String(localized: "\(config.tiles.count) shown"),
                                symbol: "slider.horizontal.3"
                            )
                        }
                    }

                    NavigationLink {
                        AppearanceView()
                    } label: {
                        row(
                            String(localized: "Appearance"),
                            detail: "\(appearance.typeface.title)"
                                + " · \(appearance.palette.title)",
                            symbol: "paintbrush"
                        )
                    }

                    NavigationLink {
                        AppIconView()
                    } label: {
                        row(String(localized: "App Icon"), detail: "", symbol: "app.badge")
                    }
                } footer: {
                    if mode == .casper {
                        Text("""
                            Metrics chooses what is displayed and how each tile is \
                            drawn. Appearance sets the typeface and colours for all \
                            of them.
                            """)
                    }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    /// Each row carries a summary of its current state, so the sheet answers
    /// "what is set?" without having to open both pages.
    private func row(_ title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.title3)
                .frame(width: 28)
                .foregroundStyle(appearance.accent)

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 2)
    }
}

#Preview {
    SettingsView(config: DashboardConfig())
}

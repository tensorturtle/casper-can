//  MetricPickerView.swift
//  Choose which measurements appear on the dashboard, and in what order.

import SwiftUI

struct MetricPickerView: View {
    let config: DashboardConfig
    @Environment(\.dismiss) private var dismiss
    @State private var editMode: EditMode = .inactive

    /// Measurements not currently on the dashboard.
    private var available: [VehicleMetric] {
        VehicleMetric.allCases.filter { !config.isEnabled($0) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(config.tiles) { tile in
                        NavigationLink {
                            if let binding = config.binding(for: tile.measurement) {
                                MetricSettingsView(config: binding)
                            }
                        } label: {
                            row(for: tile)
                        }
                    }
                    .onDelete { offsets in
                        config.tiles.remove(atOffsets: offsets)
                    }
                    .onMove { from, to in
                        config.tiles.move(fromOffsets: from, toOffset: to)
                    }
                } header: {
                    Text("On dashboard")
                } footer: {
                    Text("Drag to reorder. Tap to change the display style, range, and redline.")
                }

                if !available.isEmpty {
                    Section("Available") {
                        ForEach(available) { measurement in
                            Button {
                                config.setEnabled(measurement, true)
                            } label: {
                                HStack {
                                    Label(measurement.title, systemImage: measurement.symbol)
                                    Spacer()
                                    Image(systemName: "plus.circle.fill")
                                        .foregroundStyle(.tint)
                                }
                            }
                            .tint(.primary)
                        }
                    }
                }

                Section {
                    Button("Reset to defaults", role: .destructive) {
                        config.resetToDefaults()
                    }
                }
            }
            .navigationTitle("Measurements")
            .environment(\.editMode, $editMode)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { EditButton() }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func row(for tile: MetricConfig) -> some View {
        HStack {
            Label(tile.measurement.title, systemImage: tile.measurement.symbol)
            Spacer()
            // Style shown inline so the list doubles as a summary of the layout.
            Image(systemName: tile.style.symbol)
                .foregroundStyle(.secondary)
                .font(.caption)
        }
    }
}

#Preview {
    MetricPickerView(config: DashboardConfig())
}

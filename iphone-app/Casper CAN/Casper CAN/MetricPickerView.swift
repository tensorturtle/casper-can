//  MetricPickerView.swift
//  Choose which metrics appear, in what order, and which one is the hero.
//
//  34 metrics is too many for a flat list, so the available ones are grouped by
//  subject. The enabled list stays flat and reorderable, because display order is
//  the user's arrangement of their dashboard, not a taxonomy.

import SwiftUI

struct MetricPickerView: View {
    let config: DashboardConfig
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                heroSection

                Section {
                    ForEach(config.tiles) { tile in
                        NavigationLink {
                            if let binding = config.binding(for: tile.metric) {
                                MetricSettingsView(config: binding)
                            }
                        } label: {
                            row(for: tile)
                        }
                    }
                    .onDelete { offsets in
                        let removed = offsets.map { config.tiles[$0].metric }
                        config.tiles.remove(atOffsets: offsets)
                        // A hero that is no longer displayed would leave a gap.
                        if let hero = config.heroMetric, removed.contains(hero) {
                            config.heroMetric = nil
                        }
                    }
                    .onMove { from, to in
                        config.tiles.move(fromOffsets: from, toOffset: to)
                    }
                } header: {
                    Text("On dashboard (\(config.tiles.count))")
                } footer: {
                    Text(
                        "Press and hold the ≡ handle to reorder. Swipe left to "
                        + "remove. Tap for display style, range and redline."
                    )
                }

                availableSections

                Section {
                    Button {
                        config.enableAll()
                    } label: {
                        Label("Add every metric", systemImage: "square.grid.3x3.fill")
                    }
                    Button("Reset to defaults", role: .destructive) {
                        config.resetToDefaults()
                    }
                }
            }
            .navigationTitle("Metrics")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    /// The hero can only be something already on the dashboard, so this offers the
    /// enabled set rather than everything.
    private var heroSection: some View {
        Section {
            Picker("Large tile", selection: heroBinding) {
                Text("None").tag(nil as VehicleMetric?)
                ForEach(config.tiles) { tile in
                    Text(tile.metric.title).tag(tile.metric as VehicleMetric?)
                }
            }
        } header: {
            Text("Hero")
        } footer: {
            Text("Shown at double size, filling a 2×2 block at the top.")
        }
    }

    private var heroBinding: Binding<VehicleMetric?> {
        Binding(get: { config.heroMetric }, set: { config.heroMetric = $0 })
    }

    @ViewBuilder
    private var availableSections: some View {
        ForEach(MetricGroup.allCases) { group in
            let available = group.metrics.filter { !config.isEnabled($0) }
            if !available.isEmpty {
                Section {
                    ForEach(available) { metric in
                        Button {
                            config.setEnabled(metric, true)
                        } label: {
                            HStack {
                                Label(metric.title, systemImage: metric.symbol)
                                Spacer()
                                if !metric.unit.isEmpty {
                                    Text(metric.unit)
                                        .font(.caption)
                                        .foregroundStyle(.tertiary)
                                }
                                Image(systemName: "plus.circle.fill")
                                    .foregroundStyle(.tint)
                            }
                        }
                        .tint(.primary)
                    }
                } header: {
                    Text(group.rawValue)
                } footer: {
                    if group == .derived {
                        Text(
                            "Computed on the phone from the signals above. Items "
                            + "marked (est.) rest on an engine model — assumed "
                            + "volumetric efficiency and fuel density — not on a "
                            + "measured signal. This car publishes no air-flow or "
                            + "fuel-flow PID at all."
                        )
                    }
                }
            }
        }
    }

    private func row(for tile: MetricConfig) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "line.3.horizontal")
                .font(.footnote)
                .foregroundStyle(.tertiary)
                .accessibilityLabel("Reorder handle")

            Label(tile.metric.title, systemImage: tile.metric.symbol)
            if config.heroMetric == tile.metric {
                Image(systemName: "rectangle.expand.vertical")
                    .font(.caption2)
                    .foregroundStyle(.tint)
            }
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

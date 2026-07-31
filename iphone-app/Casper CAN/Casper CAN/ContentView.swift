//
//  ContentView.swift
//  Casper CAN
//
//  Created by tensorturtle on 7/31/26.
//
//  The dashboard: connection state, then a grid of the chosen measurements.

import SwiftUI

struct ContentView: View {
    @State private var ble = BLEClient()
    @State private var config = DashboardConfig()
    @State private var showingPicker = false

    /// Ticks so staleness is re-evaluated even when no frame arrives. Without it a
    /// frozen link keeps looking live, because nothing triggers a redraw.
    @State private var now = Date.now

    /// Adaptive columns: two per row on a phone in portrait, more on an iPad or
    /// in landscape. A glanceable dashboard should not need scrolling for 4-5 items.
    private let columns = [GridItem(.adaptive(minimum: 150), spacing: 12)]

    /// No fresh frame for over 3 s means the link has gone quiet. The board
    /// notifies once a second by default, so this tolerates two missed samples.
    private var isStale: Bool {
        guard ble.state.isConnected else { return true }
        return now.timeIntervalSince(ble.frame.receivedAt) > 3
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    ConnectionBanner(ble: ble)

                    if config.tiles.isEmpty {
                        ContentUnavailableView {
                            Label(
                                "No measurements",
                                systemImage: "gauge.with.dots.needle.bottom.50percent"
                            )
                        } description: {
                            Text("Choose what to display.")
                        } actions: {
                            Button("Choose measurements") { showingPicker = true }
                                .buttonStyle(.borderedProminent)
                        }
                        .padding(.top, 40)
                    } else {
                        LazyVGrid(columns: columns, spacing: 12) {
                            ForEach(config.tiles) { tile in
                                MetricTile(
                                    config: tile,
                                    value: tile.measurement.value(from: ble.frame),
                                    isStale: isStale
                                )
                            }
                        }
                    }
                }
                .padding()
            }
            .animation(.default, value: config.tiles)
            .navigationTitle("Casper CAN")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showingPicker = true
                    } label: {
                        Label("Measurements", systemImage: "slider.horizontal.3")
                    }
                }
            }
            .sheet(isPresented: $showingPicker) {
                MetricPickerView(config: config)
            }
            .task {
                // 1 s cadence is enough to notice a stall within the 3 s window.
                // A plain sleep loop rather than a Combine timer - no extra import,
                // and it is cancelled automatically with the view.
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(1))
                    now = .now
                }
            }
        }
    }
}

/// Connection state, plus the two conditions that would otherwise let the user
/// trust the numbers wrongly: a synthetic source, and a wire-version mismatch.
struct ConnectionBanner: View {
    let ble: BLEClient

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                Circle()
                    .fill(ble.state.isConnected ? .green : .orange)
                    .frame(width: 9, height: 9)

                Text(ble.state.label)
                    .font(.subheadline)

                Spacer()

                if ble.state.isConnected {
                    Text("\(ble.samplesPerSecond, specifier: "%.1f")/s")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                } else {
                    Button("Retry") { ble.reconnect() }
                        .font(.caption)
                        .buttonStyle(.bordered)
                }
            }

            if let version = ble.incompatibleVersion {
                notice(
                    "Appliance speaks wire version \(version); this app expects "
                    + "\(Wire.supportedVersion). Readings may be wrong.",
                    systemImage: "exclamationmark.triangle.fill",
                    tint: .red
                )
            }

            if let status = ble.status, status.isSynthetic {
                notice(
                    "Showing synthetic demo data — the appliance is not reading CAN.",
                    systemImage: "waveform.path",
                    tint: .orange
                )
            }

            if case .unauthorized = ble.state {
                notice(
                    "Allow Bluetooth for this app in Settings to connect.",
                    systemImage: "gear",
                    tint: .red
                )
            }
        }
        .padding(12)
        .background(.background.secondary, in: .rect(cornerRadius: 12))
    }

    private func notice(_ text: String, systemImage: String, tint: Color) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: systemImage)
            Text(text)
            Spacer(minLength: 0)
        }
        .font(.caption)
        .foregroundStyle(tint)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#Preview {
    ContentView()
}

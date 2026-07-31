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
    @State private var recorder = Recorder()
    @State private var showingPicker = false
    @State private var showingRecordings = false

    /// Ticks so staleness and elapsed time are re-evaluated even when no frame
    /// arrives. Without it a frozen link keeps looking live, because nothing
    /// triggers a redraw.
    @State private var now = Date.now

    /// Exactly two columns, always. That is what makes the tiles uniform squares
    /// and lets the hero be precisely 2x2: a full-width square equals two cells
    /// plus the gutter between them.
    private let columns = [GridItem(.flexible()), GridItem(.flexible())]
    private static let gutter: CGFloat = 12

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

                    if recorder.isRecording || recorder.lastError != nil {
                        RecordingBanner(recorder: recorder, now: now)
                    }

                    if config.tiles.isEmpty {
                        ContentUnavailableView {
                            Label(
                                "No metrics",
                                systemImage: "gauge.with.dots.needle.bottom.50percent"
                            )
                        } description: {
                            Text("Choose what to display.")
                        } actions: {
                            Button("Choose metrics") { showingPicker = true }
                                .buttonStyle(.borderedProminent)
                        }
                        .padding(.top, 40)
                    } else {
                        VStack(spacing: Self.gutter) {
                            if let hero = config.heroConfig {
                                MetricTile(
                                    config: hero,
                                    value: hero.metric.value(from: ble.frame),
                                    isStale: isStale,
                                    isValid: hero.metric.isValid(in: ble.frame),
                                    size: .hero
                                )
                            }

                            LazyVGrid(columns: columns, spacing: Self.gutter) {
                                ForEach(config.gridTiles) { tile in
                                    MetricTile(
                                        config: tile,
                                        value: tile.metric.value(from: ble.frame),
                                        isStale: isStale,
                                        // Before any frame arrives, validity is 0
                                        // and every tile correctly reads "no data".
                                        isValid: tile.metric.isValid(in: ble.frame)
                                    )
                                }
                            }
                        }
                    }
                }
                .padding()
            }
            .animation(.default, value: config.tiles)
            .animation(.default, value: config.heroMetric)
            .navigationTitle("Casper CAN")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        recorder.toggle()
                    } label: {
                        Label(
                            recorder.isRecording ? "Stop recording" : "Record",
                            systemImage: recorder.isRecording
                                ? "stop.circle.fill" : "record.circle"
                        )
                    }
                    .tint(recorder.isRecording ? .red : .accentColor)
                    // Recording with no link would produce an empty file.
                    .disabled(!ble.state.isConnected && !recorder.isRecording)
                }

                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        showingRecordings = true
                    } label: {
                        Label("Recordings", systemImage: "folder")
                    }

                    Button {
                        showingPicker = true
                    } label: {
                        Label("Metrics", systemImage: "slider.horizontal.3")
                    }
                }
            }
            .sheet(isPresented: $showingPicker) {
                MetricPickerView(config: config)
            }
            .sheet(isPresented: $showingRecordings) {
                RecordingsView(recorder: recorder)
            }
            .task {
                // Frames are recorded from the BLE callback, not from the view, so
                // the recording rate is the notification rate rather than the
                // screen refresh rate.
                ble.onFrame = { [recorder] frame in recorder.record(frame) }

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

/// Connection state, plus the conditions that would otherwise let the user trust
/// the numbers wrongly: synthetic data, a wire mismatch, or a car that is not
/// answering.
struct ConnectionBanner: View {
    let ble: BLEClient

    /// The board counts its own failed polls. A climbing count with the ignition
    /// on points at the adapter or the bus, not at the app.
    private var pollErrors: UInt16 { ble.frame.pollErrors }

    /// True once connected but with nothing the vehicle actually answered.
    private var noVehicleData: Bool {
        ble.state.isConnected && ble.frame.validity == 0
    }

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

            if ble.malformedFrames > 0 {
                notice(
                    "\(ble.malformedFrames) frame(s) had the wrong length — the "
                    + "appliance and app wire formats disagree.",
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

            if noVehicleData {
                notice(
                    "Connected, but the car is not answering any signal. "
                    + "Ignition off, or the CAN adapter is unplugged.",
                    systemImage: "car.side",
                    tint: .orange
                )
            }

            if pollErrors > 0 {
                notice(
                    "Appliance reports \(pollErrors) failed poll(s).",
                    systemImage: "antenna.radiowaves.left.and.right.slash",
                    tint: .secondary
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

/// Recording progress. Separate from the connection banner so it is unmissable —
/// a recording the user forgot about is how you lose a drive's worth of data.
struct RecordingBanner: View {
    let recorder: Recorder
    let now: Date

    var body: some View {
        HStack(spacing: 8) {
            if recorder.isRecording {
                Circle()
                    .fill(.red)
                    .frame(width: 9, height: 9)
                    .symbolEffect(.pulse)
                Text("Recording \(recorder.elapsedDescription)")
                    .font(.subheadline.monospacedDigit())
                Spacer()
                Text("\(recorder.sampleCount) samples")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            if let error = recorder.lastError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .padding(12)
        .background(.background.secondary, in: .rect(cornerRadius: 12))
    }
}

#Preview {
    ContentView()
}

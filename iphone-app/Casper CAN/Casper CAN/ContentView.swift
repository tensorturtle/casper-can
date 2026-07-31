//
//  ContentView.swift
//  Casper CAN
//
//  Created by tensorturtle on 7/31/26.
//
//  The dashboard. Vertical space is the scarce resource here, so the layout is
//  deliberately lopsided:
//
//  - The navigation bar is hidden entirely. A large title costs ~96 pt and tells
//    the driver nothing they don't already know.
//  - The top carries one compact status strip, and warnings only when they exist.
//  - Everything the driver does not read at a glance - record, recordings, metric
//    selection, appearance - lives in a bottom bar, within thumb reach and out of
//    the way of the gauges.

import SwiftUI

struct ContentView: View {
    @State private var ble = BLEClient()
    @State private var config = DashboardConfig()
    @State private var recorder = Recorder()
    @State private var appearance = Appearance()
    @State private var showingPicker = false
    @State private var showingRecordings = false
    @State private var showingAppearance = false

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
                VStack(spacing: Self.gutter) {
                    StatusStrip(ble: ble)

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
                        tiles
                    }
                }
                .padding(.horizontal, Self.gutter)
                .padding(.top, 4)
                .padding(.bottom, Self.gutter)
            }
            .animation(.default, value: config.tiles)
            .animation(.default, value: config.heroMetric)
            // No navigation bar at all: the title is pure overhead on a display
            // meant to be read in a moving car.
            .toolbar(.hidden, for: .navigationBar)
            // A bottom inset rather than a scrolling footer, so the controls stay
            // reachable without scrolling to the end of a long dashboard.
            .safeAreaInset(edge: .bottom) {
                ControlBar(
                    recorder: recorder,
                    isConnected: ble.state.isConnected,
                    showingRecordings: $showingRecordings,
                    showingPicker: $showingPicker,
                    showingAppearance: $showingAppearance
                )
            }
            .sheet(isPresented: $showingPicker) {
                MetricPickerView(config: config)
            }
            .sheet(isPresented: $showingRecordings) {
                RecordingsView(recorder: recorder)
            }
            .sheet(isPresented: $showingAppearance) {
                AppearanceView()
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
        // One injection point for the whole hierarchy, including the sheets.
        .environment(\.appearance, appearance)
        .preferredColorScheme(appearance.colorScheme.scheme)
        // Recolour the standard controls too, so buttons and pickers match the
        // gauges rather than sitting at the system blue.
        .tint(appearance.accent)
    }

    private var tiles: some View {
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
                        // Before any frame arrives, validity is 0 and every tile
                        // correctly reads "no data".
                        isValid: tile.metric.isValid(in: ble.frame)
                    )
                }
            }
        }
    }
}

// MARK: - Status

/// One line of connection state, plus warning chips only when something is wrong.
///
/// Compressed to a single row because in the normal case there is nothing to say
/// beyond "connected". The warnings are the exception and earn their space: each
/// one exists because the situation would otherwise be mistaken for real vehicle
/// data.
struct StatusStrip: View {
    @Environment(\.appearance) private var appearance
    let ble: BLEClient

    private var noVehicleData: Bool {
        ble.state.isConnected && ble.frame.validity == 0
    }

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 6) {
                Circle()
                    .fill(ble.state.isConnected ? .green : .orange)
                    .frame(width: 7, height: 7)

                Text(ble.state.label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                Spacer(minLength: 4)

                if ble.state.isConnected {
                    Text("\(ble.samplesPerSecond, specifier: "%.1f")/s")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                } else {
                    Button("Retry") { ble.reconnect() }
                        .font(.caption2)
                        .buttonStyle(.plain)
                        .foregroundStyle(appearance.accent)
                }
            }

            if !warnings.isEmpty {
                // Chips wrap, so several warnings do not each cost a full row.
                FlowLayout(spacing: 4) {
                    ForEach(warnings, id: \.text) { warning in
                        chip(warning)
                    }
                }
            }
        }
    }

    private struct Warning {
        let text: String
        let symbol: String
        let tint: Color
    }

    private var warnings: [Warning] {
        var result: [Warning] = []

        if let version = ble.incompatibleVersion {
            result.append(.init(
                text: "wire v\(version) ≠ v\(Wire.supportedVersion)",
                symbol: "exclamationmark.triangle.fill", tint: appearance.hot
            ))
        }
        if ble.malformedFrames > 0 {
            result.append(.init(
                text: "\(ble.malformedFrames) bad frames",
                symbol: "exclamationmark.triangle.fill", tint: appearance.hot
            ))
        }
        if let status = ble.status, status.isSynthetic {
            result.append(.init(
                text: "synthetic data", symbol: "waveform.path", tint: .orange
            ))
        }
        if noVehicleData {
            result.append(.init(
                text: "car not answering", symbol: "car.side", tint: .orange
            ))
        }
        if ble.frame.pollErrors > 0 {
            result.append(.init(
                text: "\(ble.frame.pollErrors) poll errors",
                symbol: "antenna.radiowaves.left.and.right.slash", tint: .secondary
            ))
        }
        if case .unauthorized = ble.state {
            result.append(.init(
                text: "allow Bluetooth in Settings", symbol: "gear", tint: appearance.hot
            ))
        }
        return result
    }

    private func chip(_ warning: Warning) -> some View {
        HStack(spacing: 3) {
            Image(systemName: warning.symbol)
            Text(warning.text)
        }
        .font(.caption2)
        .foregroundStyle(warning.tint)
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(warning.tint.opacity(0.12), in: .capsule)
    }
}

/// Wraps its children onto as many rows as needed. Used for the warning chips so a
/// handful of them cost one or two compact rows instead of one row each.
struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        var total = CGSize.zero

        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if rowWidth > 0, rowWidth + spacing + size.width > width {
                total.width = max(total.width, rowWidth)
                total.height += rowHeight + spacing
                rowWidth = size.width
                rowHeight = size.height
            } else {
                rowWidth += (rowWidth > 0 ? spacing : 0) + size.width
                rowHeight = max(rowHeight, size.height)
            }
        }
        total.width = max(total.width, rowWidth)
        total.height += rowHeight
        return total
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
    ) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0

        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

// MARK: - Controls

/// Recording and configuration, pinned to the bottom.
///
/// None of this is read while driving, so it sits below the gauges rather than
/// above them, and the recording state lives here too - visible, but not occupying
/// space the numbers could use.
struct ControlBar: View {
    @Environment(\.appearance) private var appearance
    let recorder: Recorder
    let isConnected: Bool
    @Binding var showingRecordings: Bool
    @Binding var showingPicker: Bool
    @Binding var showingAppearance: Bool

    var body: some View {
        VStack(spacing: 0) {
            if let error = recorder.lastError {
                // A recording that stopped itself must not do so silently.
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(appearance.hot)
                    .padding(.horizontal, 12)
                    .padding(.top, 6)
            }

            HStack(spacing: 16) {
                Button {
                    recorder.toggle()
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: recorder.isRecording
                              ? "stop.circle.fill" : "record.circle")
                            .font(.title3)
                        if recorder.isRecording {
                            Text(recorder.elapsedDescription)
                                .font(.caption.monospacedDigit())
                        }
                    }
                    .foregroundStyle(recorder.isRecording ? appearance.hot : appearance.accent)
                }
                // Recording with no link would produce an empty file.
                .disabled(!isConnected && !recorder.isRecording)

                if recorder.isRecording {
                    Text("\(recorder.sampleCount)")
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button { showingRecordings = true } label: {
                    Image(systemName: "folder").font(.body)
                }
                Button { showingPicker = true } label: {
                    Image(systemName: "slider.horizontal.3").font(.body)
                }
                Button { showingAppearance = true } label: {
                    Image(systemName: "paintbrush").font(.body)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
        }
        .background(.bar)
    }
}

#Preview {
    ContentView()
}

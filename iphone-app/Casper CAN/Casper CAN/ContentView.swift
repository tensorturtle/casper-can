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
//  - The top is one compact strip: connection state, plus tiny icon buttons for
//    the two things worth reaching quickly. Warnings appear there only when they
//    exist.
//  - Recording lives at the very END of the scrolled content, not in a pinned bar.
//    A sticky bar costs its own height on every screen forever; scrolling to reach
//    a control used twice a drive costs nothing.

import SwiftUI

struct ContentView: View {
    @State private var ble = BLEClient()
    @State private var config = DashboardConfig()
    @State private var recorder = Recorder()
    @State private var appearance = Appearance()
    @State private var showingSettings = false
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

    /// Smoothing for arc and bar fills, scaled to the rate frames actually arrive.
    ///
    /// The appliance can be run anywhere from 1 Hz to tens of Hz, and the right
    /// answer differs completely across that span:
    ///
    /// - Slow (~1 Hz): an un-animated fill jumps in obvious steps, so interpolate
    ///   across most of the interval.
    /// - Fast (above `snapAboveHz`): the stream is already smoother than any
    ///   interpolation would make it, and animating each step would leave the fill
    ///   several updates behind while burning CPU on 34 tiles. Snap instead.
    ///
    /// Derived from the *measured* rate rather than a configured one, so it adapts
    /// to what the link is really delivering rather than what was requested.
    private var fillAnimation: Animation? {
        let snapAboveHz = 7.0
        let rate = ble.samplesPerSecond

        // No measurement yet (fewer than two frames): assume slow and smooth.
        guard rate > 0.2 else { return .linear(duration: 0.25) }
        guard rate < snapAboveHz else { return nil }

        // Settle just inside the interval so the fill has arrived before the next
        // reading does, and never crawl for a very slow link.
        return .linear(duration: min(0.25, 0.9 / rate))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Self.gutter) {
                    StatusStrip(ble: ble, showingSettings: $showingSettings)

                    if config.tiles.isEmpty {
                        ContentUnavailableView {
                            Label(
                                "No metrics",
                                systemImage: "gauge.with.dots.needle.bottom.50percent"
                            )
                        } description: {
                            Text("Choose what to display.")
                        } actions: {
                            Button("Choose metrics") { showingSettings = true }
                                .buttonStyle(.borderedProminent)
                        }
                        .padding(.top, 40)
                    } else {
                        tiles
                    }

                    RecordingControls(
                        recorder: recorder,
                        isConnected: ble.state.isConnected,
                        showingRecordings: $showingRecordings
                    )
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
            .sheet(isPresented: $showingSettings) {
                SettingsView(config: config)
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
        // One injection point for the whole hierarchy, including the sheets.
        .environment(\.appearance, appearance)
        .environment(\.fillAnimation, fillAnimation)
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
    @Binding var showingSettings: Bool

    private var noVehicleData: Bool {
        ble.state.isConnected && ble.frame.validity == 0
    }

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 6) {
                Circle()
                    .fill(ble.state.isConnected ? .green : .orange)
                    .frame(width: 7, height: 7)

                // Its own foregroundStyle, so the accent applied to the whole strip
                // below reaches only the buttons that inherit it.
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

                // One target rather than two: the strip competes directly with the
                // gauges for height, so a single button can afford to be big enough
                // to hit reliably. It splits into Metrics and Appearance inside.
                //
                // A tinted disc rather than a bare glyph: on a strip of muted grey
                // status text, an unadorned icon does not read as tappable. The
                // filled circle costs a few points of height and removes the
                // ambiguity.
                Button { showingSettings = true } label: {
                    Image(systemName: "gearshape.fill")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(appearance.accent)
                        .frame(width: 32, height: 32)
                        .background(appearance.accent.opacity(0.15), in: .circle)
                        .overlay {
                            Circle().strokeBorder(appearance.accent.opacity(0.35), lineWidth: 1)
                        }
                        .contentShape(.circle)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Settings")
            }
            .font(.caption2)

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

/// Recording, at the end of the scrolled content.
///
/// Not a pinned bar: a sticky footer costs its own height on every screen for the
/// whole drive, while a control touched twice per drive can afford to be scrolled
/// to. Recording state is still unmissable while active, because the tiles above
/// dim nothing and this row gains a live elapsed time.
struct RecordingControls: View {
    @Environment(\.appearance) private var appearance
    let recorder: Recorder
    let isConnected: Bool
    @Binding var showingRecordings: Bool

    var body: some View {
        VStack(spacing: 6) {
            if let error = recorder.lastError {
                // A recording that stopped itself must not do so silently.
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(appearance.hot)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            HStack(spacing: 12) {
                Button {
                    recorder.toggle()
                } label: {
                    Label(
                        recorder.isRecording ? "Stop" : "Record",
                        systemImage: recorder.isRecording
                            ? "stop.circle.fill" : "record.circle"
                    )
                    .font(.subheadline)
                }
                .buttonStyle(.bordered)
                .tint(recorder.isRecording ? appearance.hot : appearance.accent)
                // Recording with no link would produce an empty file.
                .disabled(!isConnected && !recorder.isRecording)

                if recorder.isRecording {
                    Text("\(recorder.elapsedDescription) · \(recorder.sampleCount)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button { showingRecordings = true } label: {
                    Label("Recordings", systemImage: "folder")
                        .font(.subheadline)
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(.top, 4)
    }
}

#Preview {
    ContentView()
}

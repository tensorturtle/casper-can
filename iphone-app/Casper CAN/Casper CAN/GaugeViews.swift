//  GaugeViews.swift
//  The four ways a measurement can be drawn, plus the tile that dispatches.
//
//  Colour carries one meaning only: red means past the redline. Nothing else in
//  a tile is red, so a glance at the dashboard answers "is anything wrong?"
//  without reading a single number.

import SwiftUI

/// Shared accent for a value that has crossed its redline.
private let hotColor = Color.red
private let normalColor = Color.accentColor

// MARK: - Tile

/// One dashboard cell: title, the chosen gauge, and units.
struct MetricTile: View {
    let config: MetricConfig
    let value: Double
    /// Dims the whole tile when no fresh data is arriving, so a frozen number is
    /// visibly frozen rather than quietly wrong.
    let isStale: Bool

    private var hot: Bool { config.isHot(value) }

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: config.measurement.symbol)
                Text(config.measurement.title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            gauge
                .frame(maxWidth: .infinity)
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 16))
        .overlay {
            // A hairline border rather than a filled background, so the redline
            // state reads clearly in both light and dark appearance.
            RoundedRectangle(cornerRadius: 16)
                .strokeBorder(hot ? hotColor : .clear, lineWidth: 2)
        }
        .opacity(isStale ? 0.45 : 1)
        .animation(.easeOut(duration: 0.2), value: hot)
    }

    @ViewBuilder
    private var gauge: some View {
        switch config.style {
        case .number:
            NumberGauge(config: config, value: value)
        case .circular:
            CircularGauge(config: config, value: value)
        case .linear:
            LinearGauge(config: config, value: value)
        case .indicator:
            IndicatorLamp(config: config, value: value)
        }
    }
}

// MARK: - Number

struct NumberGauge: View {
    let config: MetricConfig
    let value: Double

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text(config.measurement.format(value))
                .font(.system(size: 44, weight: .semibold, design: .rounded))
                // Monospaced digits stop the layout jittering as values change.
                .monospacedDigit()
                .contentTransition(.numericText())
                .foregroundStyle(config.isHot(value) ? hotColor : .primary)
            if !config.measurement.unit.isEmpty {
                Text(config.measurement.unit)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .animation(.easeOut(duration: 0.15), value: value)
    }
}

// MARK: - Circular

struct CircularGauge: View {
    let config: MetricConfig
    let value: Double

    /// Leaves a gap at the bottom so the sweep reads as a dial, not a ring.
    private let sweep = 0.75

    private var fraction: Double { config.fraction(of: value) }

    private var redlineFraction: Double? {
        guard let redline = config.redline, !config.mirrorRedline else { return nil }
        return config.fraction(of: redline)
    }

    /// Rotation that puts the gap at the bottom, centred. Applied to the arcs
    /// only - rotating the whole stack would take the readout with it.
    private var arcRotation: Angle { .degrees(90 + 360 * (1 - sweep) / 2) }

    var body: some View {
        ZStack {
            arcs
                .rotationEffect(arcRotation)

            VStack(spacing: 0) {
                Text(config.measurement.format(value))
                    .font(.system(size: 28, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                if !config.measurement.unit.isEmpty {
                    Text(config.measurement.unit)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(height: 120)
        .animation(.easeOut(duration: 0.2), value: value)
    }

    private var arcs: some View {
        ZStack {
            Circle()
                .trim(from: 0, to: sweep)
                .stroke(.quaternary, style: .init(lineWidth: 12, lineCap: .round))

            // The redline zone, drawn under the value arc so the value wins where
            // they overlap.
            if let start = redlineFraction {
                Circle()
                    .trim(from: sweep * start, to: sweep)
                    .stroke(hotColor.opacity(0.28), style: .init(lineWidth: 12, lineCap: .butt))
            }

            Circle()
                .trim(from: 0, to: sweep * fraction)
                .stroke(
                    config.isHot(value) ? hotColor : normalColor,
                    style: .init(lineWidth: 12, lineCap: .round)
                )
        }
    }
}

// MARK: - Linear

struct LinearGauge: View {
    let config: MetricConfig
    let value: Double

    /// A signed quantity fills outward from the centre, so left and right are
    /// immediately distinguishable. An unsigned one fills from the left edge.
    private var bipolar: Bool { config.measurement.isBipolar }

    var body: some View {
        VStack(spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(config.measurement.format(value))
                    .font(.system(size: 30, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .foregroundStyle(config.isHot(value) ? hotColor : .primary)
                if !config.measurement.unit.isEmpty {
                    Text(config.measurement.unit)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            GeometryReader { geo in
                let width = geo.size.width
                let fraction = config.fraction(of: value)
                let color = config.isHot(value) ? hotColor : normalColor

                ZStack(alignment: .leading) {
                    Capsule().fill(.quaternary)

                    if bipolar {
                        // Measured from the midpoint; the bar grows left or right.
                        let mid = width / 2
                        let extent = (fraction - 0.5) * width
                        Capsule()
                            .fill(color)
                            .frame(width: abs(extent))
                            .offset(x: extent < 0 ? mid - abs(extent) : mid)
                    } else {
                        Capsule()
                            .fill(color)
                            .frame(width: width * fraction)
                    }

                    if let redline = config.redline {
                        // Tick at the threshold, so the number has context even
                        // before it is crossed.
                        ForEach(tickFractions(for: redline), id: \.self) { t in
                            Rectangle()
                                .fill(hotColor)
                                .frame(width: 2)
                                .offset(x: width * t - 1)
                        }
                    }
                }
            }
            .frame(height: 14)

            HStack {
                Text(config.measurement.format(config.range.lowerBound))
                Spacer()
                Text(config.measurement.format(config.range.upperBound))
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
            .monospacedDigit()
        }
        .animation(.easeOut(duration: 0.2), value: value)
    }

    private func tickFractions(for redline: Double) -> [Double] {
        var result = [config.fraction(of: redline)]
        if config.mirrorRedline { result.append(config.fraction(of: -redline)) }
        return result.filter { $0 > 0.001 && $0 < 0.999 }
    }
}

// MARK: - Indicator

struct IndicatorLamp: View {
    let config: MetricConfig
    let value: Double

    private var on: Bool { value > 0.5 }

    /// The check-engine lamp being lit is a fault; the A/C compressor being on is
    /// not. So "lit" alone cannot mean red - it depends on the measurement.
    private var litColor: Color {
        config.measurement == .checkEngine ? hotColor : normalColor
    }

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: config.measurement.symbol)
                .font(.system(size: 40))
                .foregroundStyle(on ? litColor : Color.secondary.opacity(0.3))
                .symbolEffect(.pulse, isActive: on && config.measurement == .checkEngine)

            Text(on ? "ON" : "OFF")
                .font(.caption.weight(.semibold))
                .foregroundStyle(on ? litColor : .secondary)
        }
        .frame(height: 90)
        .animation(.easeOut(duration: 0.2), value: on)
    }
}

/// Preview helper: a config with a non-default style. A named function rather
/// than an inline closure, which the result builder handles poorly.
private func previewConfig(_ metric: VehicleMetric, style: GaugeStyleKind) -> MetricConfig {
    var config = MetricConfig(metric)
    config.style = style
    return config
}

#Preview("Gauges") {
    ScrollView {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            MetricTile(config: MetricConfig(.speed), value: 132, isStale: false)
            MetricTile(config: MetricConfig(.steeringAngle), value: -180, isStale: false)
            MetricTile(config: MetricConfig(.steeringTorque), value: 8200, isStale: false)
            MetricTile(config: MetricConfig(.checkEngine), value: 1, isStale: false)
            MetricTile(config: MetricConfig(.acCompressor), value: 1, isStale: true)
            MetricTile(config: previewConfig(.speed, style: .number), value: 62, isStale: false)
        }
        .padding()
    }
}

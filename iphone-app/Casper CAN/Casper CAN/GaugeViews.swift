//  GaugeViews.swift
//  The four ways a metric can be drawn, plus the tile that dispatches.
//
//  Every tile is a SQUARE of identical size, so the dashboard tiles tightly with
//  no ragged edges. The hero tile is exactly 2x2 of a regular one: with a
//  two-column grid, a full-width square is precisely two cells wide and two cells
//  tall including the gutter, so the geometry works out without a custom layout.
//
//  Gauges therefore size themselves from the space they are given rather than
//  using fixed heights - the same view has to look right at both scales.
//
//  Colour carries one meaning only: red means past the redline. Nothing else in a
//  tile is red, so a glance answers "is anything wrong?" without reading a number.

import SwiftUI

private let hotColor = Color.red
private let normalColor = Color.accentColor

/// Regular or hero. Drives font sizes and stroke weights; the tile is square in
/// both cases, so only the scale differs.
enum TileSize {
    case regular
    case hero

    var valueFontSize: CGFloat { self == .hero ? 68 : 30 }
    var circularValueFontSize: CGFloat { self == .hero ? 60 : 24 }
    var unitFontSize: CGFloat { self == .hero ? 20 : 11 }
    var titleFont: Font { self == .hero ? .subheadline : .caption }
    var arcWidth: CGFloat { self == .hero ? 22 : 11 }
    var barHeight: CGFloat { self == .hero ? 26 : 12 }
    var lampSize: CGFloat { self == .hero ? 90 : 38 }
    var padding: CGFloat { self == .hero ? 20 : 12 }
    var cornerRadius: CGFloat { self == .hero ? 22 : 16 }
}

// MARK: - Tile

/// One dashboard cell: title, the chosen gauge, units. Always square.
struct MetricTile: View {
    let config: MetricConfig
    let value: Double
    /// Dims the whole tile when no fresh frame is arriving, so a frozen number is
    /// visibly frozen rather than quietly wrong.
    let isStale: Bool
    /// False when the board got no answer for this specific signal. Distinct from
    /// `isStale`, which is about the BLE link: with the ignition off the link is
    /// fine and every signal is invalid. Showing 0 in that case would be a lie.
    var isValid: Bool = true
    var size: TileSize = .regular

    private var hot: Bool { isValid && config.isHot(value) }

    var body: some View {
        VStack(spacing: size == .hero ? 12 : 6) {
            HStack(spacing: 4) {
                Image(systemName: config.metric.symbol)
                Text(config.metric.title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .font(size.titleFont)
            .foregroundStyle(.secondary)

            // The gauge takes whatever vertical space is left, which is what makes
            // one implementation work at both tile scales.
            gauge
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .padding(size.padding)
        // Square: with a 2-column grid this makes every tile identical, and the
        // hero exactly 2x2.
        .aspectRatio(1, contentMode: .fit)
        .background(.background.secondary, in: .rect(cornerRadius: size.cornerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: size.cornerRadius)
                .strokeBorder(hot ? hotColor : .clear, lineWidth: 2)
        }
        .opacity(isStale ? 0.45 : 1)
        .animation(.easeOut(duration: 0.2), value: hot)
    }

    @ViewBuilder
    private var gauge: some View {
        if !isValid {
            NoDataGauge(size: size)
        } else {
            switch config.style {
            case .number:
                NumberGauge(config: config, value: value, size: size)
            case .circular:
                CircularGauge(config: config, value: value, size: size)
            case .linear:
                LinearGauge(config: config, value: value, size: size)
            case .indicator:
                IndicatorLamp(config: config, value: value, size: size)
            }
        }
    }
}

/// Shown when the board reported no answer for this signal. Deliberately not a
/// zero-valued gauge: "the car did not answer" and "the value is zero" must not
/// look alike.
struct NoDataGauge: View {
    var size: TileSize = .regular

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: "questionmark.circle")
                .font(.system(size: size.lampSize * 0.7))
            Text("no data")
                .font(size == .hero ? .subheadline : .caption2)
        }
        .foregroundStyle(.tertiary)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Value + unit, shared by the number and circular gauges.
private struct ValueLabel: View {
    let config: MetricConfig
    let value: Double
    let fontSize: CGFloat
    let unitSize: CGFloat
    var hot: Bool

    var body: some View {
        VStack(spacing: 0) {
            Text(config.metric.format(value))
                .font(.system(size: fontSize, weight: .semibold, design: .rounded))
                // Monospaced digits stop the layout jittering as values change.
                .monospacedDigit()
                .contentTransition(.numericText())
                .minimumScaleFactor(0.4)
                .lineLimit(1)
                .foregroundStyle(hot ? hotColor : .primary)
            if !config.metric.unit.isEmpty {
                Text(config.metric.unit)
                    .font(.system(size: unitSize))
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Number

struct NumberGauge: View {
    let config: MetricConfig
    let value: Double
    var size: TileSize = .regular

    var body: some View {
        ValueLabel(
            config: config, value: value,
            fontSize: size.valueFontSize, unitSize: size.unitFontSize,
            hot: config.isHot(value)
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(.easeOut(duration: 0.15), value: value)
    }
}

// MARK: - Circular

struct CircularGauge: View {
    let config: MetricConfig
    let value: Double
    var size: TileSize = .regular

    /// Leaves a gap at the bottom so the sweep reads as a dial, not a ring.
    private let sweep = 0.75

    private var fraction: Double { config.fraction(of: value) }

    private var redlineFraction: Double? {
        guard let redline = config.redline, !config.mirrorRedline else { return nil }
        let f = config.fraction(of: redline)
        return (f > 0.001 && f < 0.999) ? f : nil
    }

    /// Rotation that puts the gap at the bottom, centred. Applied to the arcs
    /// only - rotating the whole stack would take the readout with it.
    private var arcRotation: Angle { .degrees(90 + 360 * (1 - sweep) / 2) }

    var body: some View {
        ZStack {
            arcs
                .rotationEffect(arcRotation)

            ValueLabel(
                config: config, value: value,
                fontSize: size.circularValueFontSize, unitSize: size.unitFontSize,
                hot: config.isHot(value)
            )
            // Keep the readout inside the ring rather than overlapping the arc.
            .padding(size == .hero ? 46 : 22)
        }
        .aspectRatio(1, contentMode: .fit)
        .animation(.easeOut(duration: 0.2), value: value)
    }

    private var arcs: some View {
        ZStack {
            Circle()
                .trim(from: 0, to: sweep)
                .stroke(.quaternary, style: .init(lineWidth: size.arcWidth, lineCap: .round))

            // The redline zone, drawn under the value arc so the value wins where
            // they overlap.
            if let start = redlineFraction {
                Circle()
                    .trim(from: sweep * start, to: sweep)
                    .stroke(
                        hotColor.opacity(0.28),
                        style: .init(lineWidth: size.arcWidth, lineCap: .butt)
                    )
            }

            Circle()
                .trim(from: 0, to: sweep * fraction)
                .stroke(
                    config.isHot(value) ? hotColor : normalColor,
                    style: .init(lineWidth: size.arcWidth, lineCap: .round)
                )
        }
        .padding(size.arcWidth / 2)
    }
}

// MARK: - Linear

struct LinearGauge: View {
    let config: MetricConfig
    let value: Double
    var size: TileSize = .regular

    /// A signed quantity fills outward from the centre, so left and right are
    /// immediately distinguishable. An unsigned one fills from the left edge.
    private var bipolar: Bool { config.metric.isBipolar }

    var body: some View {
        VStack(spacing: size == .hero ? 14 : 8) {
            Spacer(minLength: 0)

            ValueLabel(
                config: config, value: value,
                fontSize: size.valueFontSize * 0.8, unitSize: size.unitFontSize,
                hot: config.isHot(value)
            )

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
            .frame(height: size.barHeight)

            HStack {
                Text(config.metric.format(config.range.lowerBound))
                Spacer()
                Text(config.metric.format(config.range.upperBound))
            }
            .font(size == .hero ? .caption : .system(size: 9))
            .foregroundStyle(.tertiary)
            .monospacedDigit()

            Spacer(minLength: 0)
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
    var size: TileSize = .regular

    private var on: Bool { value > 0.5 }

    /// The check-engine lamp being lit is a fault; the A/C compressor being on is
    /// not. So "lit" alone cannot mean red — it depends on the metric.
    private var litColor: Color {
        config.metric == .checkEngine ? hotColor : normalColor
    }

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: config.metric.symbol)
                .font(.system(size: size.lampSize))
                .foregroundStyle(on ? litColor : Color.secondary.opacity(0.3))
                .symbolEffect(.pulse, isActive: on && config.metric == .checkEngine)

            Text(on ? "ON" : "OFF")
                .font(size == .hero ? .headline : .caption.weight(.semibold))
                .foregroundStyle(on ? litColor : .secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(.easeOut(duration: 0.2), value: on)
    }
}

#Preview("Tiles") {
    let frame = TelemetryFrame.preview()
    return ScrollView {
        VStack(spacing: 12) {
            MetricTile(
                config: MetricConfig(.speed), value: 132,
                isStale: false, isValid: true, size: .hero
            )
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                ForEach([VehicleMetric.rpm, .steeringAngle, .steeringTorque,
                         .coolant, .checkEngine, .acCompressor, .voltage, .shortTrim],
                        id: \.self) { metric in
                    MetricTile(
                        config: MetricConfig(metric),
                        value: metric.value(from: frame),
                        isStale: false,
                        isValid: metric != .voltage   // one tile showing "no data"
                    )
                }
            }
        }
        .padding()
    }
}

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
//
//  NUMBERS SNAP, GEOMETRY GLIDES. A numericText content transition cross-fades every
//  digit change into a blur at these update rates, so the text is deliberately not
//  animated. Arc and bar fills are the opposite case: an un-animated fill jumps in
//  visible steps once per notification, and a short interpolation reads as continuous
//  motion instead. The window is kept well under the notification interval so the
//  geometry still tracks the car rather than lagging it.

import SwiftUI

// Colours come from the user's palette via the environment rather than being
// constants here. "hot" still means exactly one thing - past the redline.

/// Smoothing for arc and bar fills only, never for the numbers. Supplied through the
/// environment because the right duration depends on the measured notification rate,
/// which only the dashboard knows. `nil` means snap.
///
/// Linear rather than eased: on a repeatedly stepped value, easing in and out of
/// every step reads as stuttering rather than flow.
struct FillAnimationKey: EnvironmentKey {
    static let defaultValue: Animation? = .linear(duration: 0.25)
}

extension EnvironmentValues {
    var fillAnimation: Animation? {
        get { self[FillAnimationKey.self] }
        set { self[FillAnimationKey.self] = newValue }
    }
}

/// Regular or hero. Drives font sizes and stroke weights; the tile is square in
/// both cases, so only the scale differs.
///
/// This is a driving display read at a glance, so the number is the point: sizes
/// here are deliberately aggressive, and `ValueLabel` shrinks text that would not
/// fit rather than the sizes being chosen conservatively for the worst case. A
/// five-digit odometer therefore shrinks; a two-digit speed stays huge.
enum TileSize {
    case regular
    case hero

    var valueFontSize: CGFloat { self == .hero ? 128 : 46 }
    var circularValueFontSize: CGFloat { self == .hero ? 104 : 38 }
    var unitFontSize: CGFloat { self == .hero ? 26 : 12 }
    var titleFont: Font { self == .hero ? .headline : .caption }
    /// Thinner arcs than before: the ring is context, the number is the reading,
    /// so the ring gives back space rather than competing for it.
    var arcWidth: CGFloat { self == .hero ? 18 : 9 }
    var barHeight: CGFloat { self == .hero ? 22 : 10 }
    var lampSize: CGFloat { self == .hero ? 130 : 44 }
    var padding: CGFloat { self == .hero ? 16 : 10 }
    var cornerRadius: CGFloat { self == .hero ? 22 : 16 }

    /// How far the readout is inset from the ring. Tight, because the usable width
    /// inside a 0.75-sweep dial is most of the diameter.
    var circularInset: CGFloat { self == .hero ? 30 : 15 }
}

// MARK: - Tile

/// One dashboard cell: title, the chosen gauge, units. Always square.
struct MetricTile: View {
    @Environment(\.appearance) private var appearance
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
        VStack(spacing: size == .hero ? 6 : 2) {
            HStack(spacing: 4) {
                Image(systemName: config.metric.symbol)
                Text(config.metric.title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .font(size.titleFont)
            .fontDesign(appearance.typeface.design)
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
                .strokeBorder(hot ? appearance.hot : .clear, lineWidth: 2)
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
    @Environment(\.appearance) private var appearance
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
    @Environment(\.appearance) private var appearance
    let config: MetricConfig
    let value: Double
    let fontSize: CGFloat
    let unitSize: CGFloat
    var hot: Bool

    var body: some View {
        VStack(spacing: -2) {
            Text(config.metric.format(value))
                // Typeface and weight are the user's choice; see Appearance.swift.
                .font(appearance.valueFont(size: fontSize))
                // Monospaced digits stop the layout jittering as values change.
                .monospacedDigit()
                // Aggressive floor: the base sizes are set for the common 2-3 digit
                // case, and long values shrink to fit rather than forcing every
                // tile down to the worst case.
                .minimumScaleFactor(0.25)
                .lineLimit(1)
                .foregroundStyle(hot ? appearance.hot : .primary)
            if !config.metric.unit.isEmpty {
                Text(config.metric.unit)
                    .font(appearance.labelFont(size: unitSize))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
            }
        }
        // Fill the space so the shrink-to-fit has the whole tile to work with.
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Number

struct NumberGauge: View {
    @Environment(\.appearance) private var appearance
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
    }
}

// MARK: - Circular

struct CircularGauge: View {
    @Environment(\.appearance) private var appearance
    @Environment(\.fillAnimation) private var fillAnimation
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
                // Only the arcs animate; the readout inside snaps.
                .animation(fillAnimation, value: fraction)

            ValueLabel(
                config: config, value: value,
                fontSize: size.circularValueFontSize, unitSize: size.unitFontSize,
                hot: config.isHot(value)
            )
            // Keep the readout inside the ring rather than overlapping the arc.
            .padding(size.circularInset)
        }
        .aspectRatio(1, contentMode: .fit)
    }

    private var arcs: some View {
        // GeometryReader for the radius: the redline zone has to overshoot the end
        // of the sweep by the track's round cap, and that overshoot is only
        // expressible in trim units once the circumference is known.
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height)
            // The stroke is centred on the path and the whole stack is inset by
            // half the line width, so this is the radius the arc is drawn at.
            let radius = max(1, (side - size.arcWidth) / 2)
            // A round cap extends half a line width beyond the path's end. In
            // trim units that is (arcWidth / 2) / circumference.
            let capOvershoot = (size.arcWidth / 2) / (2 * .pi * radius)
            // Never past the full circle, or the trim wraps around to the start.
            let redlineEnd = min(1.0, sweep + capOvershoot)

            ZStack {
                Circle()
                    .trim(from: 0, to: sweep)
                    .stroke(.quaternary, style: .init(lineWidth: size.arcWidth, lineCap: .round))

                // The redline zone, drawn under the value arc so the value wins
                // where they overlap. `.butt` at the start keeps the threshold
                // visually exact; the end overshoots so the track's rounded tip is
                // covered rather than left showing grey past the red.
                if let start = redlineFraction {
                    Circle()
                        .trim(from: sweep * start, to: redlineEnd)
                        .stroke(
                            appearance.hot.opacity(0.28),
                            style: .init(lineWidth: size.arcWidth, lineCap: .butt)
                        )
                }

                Circle()
                    .trim(from: 0, to: sweep * fraction)
                    .stroke(
                        config.isHot(value) ? appearance.hot : appearance.accent,
                        style: .init(lineWidth: size.arcWidth, lineCap: .round)
                    )
            }
        }
        .padding(size.arcWidth / 2)
    }
}

// MARK: - Linear

struct LinearGauge: View {
    @Environment(\.appearance) private var appearance
    @Environment(\.fillAnimation) private var fillAnimation
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
                fontSize: size.valueFontSize, unitSize: size.unitFontSize,
                hot: config.isHot(value)
            )

            GeometryReader { geo in
                let width = geo.size.width
                let fraction = config.fraction(of: value)
                let color = config.isHot(value) ? appearance.hot : appearance.accent

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
                                .fill(appearance.hot)
                                .frame(width: 2)
                                .offset(x: width * t - 1)
                        }
                    }
                }
            }
            .frame(height: size.barHeight)
            // Only the bar animates; the number above it snaps.
            .animation(fillAnimation, value: value)

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
    }

    private func tickFractions(for redline: Double) -> [Double] {
        var result = [config.fraction(of: redline)]
        if config.mirrorRedline { result.append(config.fraction(of: -redline)) }
        return result.filter { $0 > 0.001 && $0 < 0.999 }
    }
}

// MARK: - Indicator

struct IndicatorLamp: View {
    @Environment(\.appearance) private var appearance
    let config: MetricConfig
    let value: Double
    var size: TileSize = .regular

    private var on: Bool { value > 0.5 }

    /// The check-engine lamp being lit is a fault; the A/C compressor being on is
    /// not. So "lit" alone cannot mean red — it depends on the metric.
    private var litColor: Color {
        config.metric == .checkEngine ? appearance.hot : appearance.accent
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

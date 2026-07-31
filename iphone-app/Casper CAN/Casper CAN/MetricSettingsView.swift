//  MetricSettingsView.swift
//  Per-measurement customization: display style, range, redline.

import SwiftUI

struct MetricSettingsView: View {
    @Binding var config: MetricConfig

    /// Redline is optional, so the toggle and the value need separate state that
    /// writes back into the optional on change.
    @State private var redlineEnabled: Bool = false
    @State private var redlineValue: Double = 0

    private var measurement: VehicleMetric { config.measurement }

    /// Step size scaled to the magnitude of the signal - stepping torque by 1
    /// count across a +-10000 range would be unusable.
    private var step: Double {
        let span = config.maximum - config.minimum
        return switch span {
        case ..<10: 0.5
        case ..<100: 1
        case ..<1000: 10
        default: 100
        }
    }

    var body: some View {
        Form {
            Section("Display style") {
                Picker("Style", selection: $config.style) {
                    ForEach(config.availableStyles) { style in
                        Label(style.title, systemImage: style.symbol).tag(style)
                    }
                }
                .pickerStyle(.inline)
                .labelsHidden()
            }

            if !measurement.isBoolean {
                Section {
                    stepper("Minimum", value: $config.minimum)
                    stepper("Maximum", value: $config.maximum)
                } header: {
                    Text("Range")
                } footer: {
                    Text(
                        "Full scale for the gauge. Vehicle limit is "
                        + "\(measurement.format(measurement.defaultRange.lowerBound)) to "
                        + "\(measurement.format(measurement.defaultRange.upperBound)) "
                        + measurement.unit
                        + ". Narrowing the range magnifies small changes."
                    )
                }

                Section {
                    Toggle("Redline", isOn: $redlineEnabled)

                    if redlineEnabled {
                        stepper("Threshold", value: $redlineValue)

                        if measurement.isBipolar {
                            Toggle("Mirror to negative", isOn: $config.mirrorRedline)
                        }
                    }
                } header: {
                    Text("Warning")
                } footer: {
                    Text(
                        measurement.isBipolar
                        ? "Values at or beyond the threshold turn red. Mirroring also warns "
                          + "below the negative of it, so a hard input either way is flagged."
                        : "Values at or above the threshold turn red."
                    )
                }
            }

            Section {
                LabeledContent("Live preview") { EmptyView() }
                // Rendered at a value just past the threshold so the customization
                // being edited is actually visible.
                MetricTile(config: config, value: previewValue, isStale: false)
                    .frame(maxWidth: 220)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 4)
            }
        }
        .navigationTitle(measurement.title)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            redlineEnabled = config.redline != nil
            redlineValue = config.redline ?? defaultThreshold
        }
        .onChange(of: redlineEnabled) { _, enabled in
            config.redline = enabled ? redlineValue : nil
        }
        .onChange(of: redlineValue) { _, value in
            if redlineEnabled { config.redline = value }
        }
    }

    /// Two thirds up the range - a sane starting threshold when the measurement
    /// has no documented limit of its own.
    private var defaultThreshold: Double {
        measurement.defaultRedline
            ?? (config.minimum + (config.maximum - config.minimum) * 0.66)
    }

    private var previewValue: Double {
        if measurement.isBoolean { return 1 }
        if let redline = config.redline { return redline }
        return config.minimum + (config.maximum - config.minimum) * 0.6
    }

    private func stepper(_ label: String, value: Binding<Double>) -> some View {
        Stepper(value: value, step: step) {
            LabeledContent(label) {
                Text("\(measurement.format(value.wrappedValue)) \(measurement.unit)")
                    .monospacedDigit()
            }
        }
    }
}

#Preview {
    // No explicit `return` here - a #Preview body is a ViewBuilder closure, which
    // rejects one.
    @Previewable @State var config = MetricConfig(.speed)
    NavigationStack { MetricSettingsView(config: $config) }
}

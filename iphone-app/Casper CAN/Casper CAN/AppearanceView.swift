//  AppearanceView.swift
//  Typeface, weight, palette and light/dark override, with a live sample.
//
//  The sample is a real MetricTile rather than a mock, so what is previewed is
//  exactly what the dashboard will render.

import SwiftUI

struct AppearanceView: View {
    @Environment(\.appearance) private var appearance

    /// Shown in the sample. Speed at a redline-crossing value so both the accent
    /// and the warning colour are visible in one glance.
    private let sampleConfig = MetricConfig(.speed)

    var body: some View {
        Form {
            Section {
                // A hero-sized sample: the point of this screen is the big
                // numbers, so preview them at the size that matters.
                MetricTile(
                    config: sampleConfig, value: 118,
                    isStale: false, isValid: true, size: .hero
                )
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
            } header: {
                Text("Sample")
            } footer: {
                Text("118 km/h is past this tile's 110 redline, so the warning colour shows.")
            }

            Section("Typeface") {
                Picker("Typeface", selection: typefaceBinding) {
                    ForEach(ValueTypeface.allCases) { face in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(face.title)
                                // Each row is set in its own face, so the choice
                                // is legible from the list itself.
                                .fontDesign(face.design)
                            Text(face.subtitle)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .tag(face)
                    }
                }
                .pickerStyle(.inline)
                .labelsHidden()
            }

            Section {
                Picker("Weight", selection: weightBinding) {
                    ForEach(ValueWeight.allCases) { weight in
                        Text(weight.title)
                            .fontWeight(weight.font)
                            .tag(weight)
                    }
                }
            } header: {
                Text("Weight")
            } footer: {
                Text("Heavier is easier to catch at a glance; lighter reads more like an instrument panel.")
            }

            Section {
                Picker("Palette", selection: paletteBinding) {
                    ForEach(ThemePalette.allCases) { palette in
                        HStack(spacing: 8) {
                            Circle().fill(palette.accent).frame(width: 14, height: 14)
                            Circle().fill(palette.hot).frame(width: 14, height: 14)
                            Text(palette.title)
                        }
                        .tag(palette)
                    }
                }
                .pickerStyle(.inline)
                .labelsHidden()
            } header: {
                Text("Colours")
            } footer: {
                Text(
                    "The first swatch is the normal accent, the second is "
                    + "past-redline. Both are set per palette so they stay "
                    + "distinguishable from each other."
                )
            }

            Section {
                Picker("Appearance", selection: schemeBinding) {
                    ForEach(ColorSchemeChoice.allCases) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .pickerStyle(.segmented)
            } header: {
                Text("Light & dark")
            } footer: {
                Text("Dark is easier on the eyes at night; System follows the phone.")
            }

            Section {
                Button("Reset appearance", role: .destructive) { appearance.reset() }
            }
        }
        .navigationTitle("Appearance")
    }

    // Bindings rather than $-syntax: `appearance` comes from the environment, which
    // is not a projected-value property wrapper.
    private var typefaceBinding: Binding<ValueTypeface> {
        Binding(get: { appearance.typeface }, set: { appearance.typeface = $0 })
    }
    private var weightBinding: Binding<ValueWeight> {
        Binding(get: { appearance.weight }, set: { appearance.weight = $0 })
    }
    private var paletteBinding: Binding<ThemePalette> {
        Binding(get: { appearance.palette }, set: { appearance.palette = $0 })
    }
    private var schemeBinding: Binding<ColorSchemeChoice> {
        Binding(get: { appearance.colorScheme }, set: { appearance.colorScheme = $0 })
    }
}

#Preview {
    NavigationStack { AppearanceView() }
}

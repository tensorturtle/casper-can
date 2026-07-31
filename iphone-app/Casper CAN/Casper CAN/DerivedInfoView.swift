//  DerivedInfoView.swift
//  Explains a derived metric before it can be added.
//
//  Derived values are not readings — some are arithmetic on measured signals, and
//  four are an engine model with assumptions baked in. Adding one with a single tap
//  would put a number on the dashboard that looks exactly as authoritative as
//  measured speed. So tapping a derived metric explains it first, and adding is a
//  second, deliberate step.

import SwiftUI

struct DerivedInfoView: View {
    let metric: VehicleMetric
    let onAdd: () -> Void

    @Environment(\.appearance) private var appearance
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if metric.isEstimate {
                    Section {
                        Label {
                            Text(
                                "This is an **estimate from a model**, not a "
                                + "measurement. The car does not report this value."
                            )
                        } icon: {
                            Image(systemName: "exclamationmark.triangle.fill")
                        }
                        .foregroundStyle(.orange)
                    }
                }

                if let formula = metric.formulaText {
                    Section("How it is calculated") {
                        Text(formula)
                            // Monospaced so the arithmetic reads as arithmetic.
                            .font(.system(.footnote, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }

                if let explanation = metric.explanationText {
                    Section("What it means") {
                        Text(explanation)
                            .font(.callout)
                    }
                }

                if !metric.derivedInputs.isEmpty {
                    Section {
                        ForEach(metric.derivedInputs) { input in
                            Label(input.title, systemImage: input.symbol)
                                .font(.callout)
                        }
                    } header: {
                        Text("Signals it needs")
                    } footer: {
                        Text(
                            "All of them must be answering, or the tile shows "
                            + "“no data” rather than a number computed from a "
                            + "partial set."
                        )
                    }
                }

                if !metric.caveats.isEmpty {
                    Section("Assumptions and limits") {
                        ForEach(metric.caveats, id: \.self) { caveat in
                            HStack(alignment: .top, spacing: 8) {
                                Image(systemName: "circle.fill")
                                    .font(.system(size: 4))
                                    .padding(.top, 6)
                                Text(caveat)
                            }
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        }
                    }
                }

                Section {
                    Button {
                        onAdd()
                        dismiss()
                    } label: {
                        Label("Add to dashboard", systemImage: "plus.circle.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)

                    Button("Cancel", role: .cancel) { dismiss() }
                        .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle(metric.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    // A unit reminder is more useful here than a second Done button.
                    if !metric.unit.isEmpty {
                        Text(metric.unit)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

#Preview("Estimate") {
    DerivedInfoView(metric: .estEconomy) {}
}

#Preview("Plain derived") {
    DerivedInfoView(metric: .boost) {}
}

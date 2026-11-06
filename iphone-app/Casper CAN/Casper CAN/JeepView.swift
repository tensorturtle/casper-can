//
//  JeepView.swift
//  Casper CAN
//
//  Jeep mode. Shown instead of the tile dashboard when the board's status says
//  it is decoding the Jeep Cherokee KL.
//
//  The Jeep's fuel gauge is broken - the module that reports tank level went
//  silent (jeep-kl/README.md §3.4) - so this screen is a stand-in for it: km
//  driven since the last fill-up, read off the car's own odometer broadcast.
//
//  Logging is one button. Every fill-up is presumed to fill the tank, so there
//  is nothing to type: pressing "Filled up" records the odometer, and the
//  distance between two fill-ups is what one tank lasted. That history is what
//  turns "km since fill-up" into a rough "km left".

import SwiftUI

// MARK: - Model

/// One full tank. `odometerKm` is nil until the car has reported an odometer
/// since the button was pressed - see `FuelLog.fillUp`.
struct FillUp: Identifiable, Codable, Equatable {
    var id = UUID()
    var date: Date
    var odometerKm: Int?
}

/// The fill-up history plus the last odometer the car reported, persisted to
/// UserDefaults as JSON - the same approach as `DashboardConfig`.
@Observable
final class FuelLog {
    private(set) var fillUps: [FillUp] = []

    /// Kept so the screen still answers with the car off and the board asleep,
    /// marked with when it was true.
    private(set) var lastOdometerKm: Int?
    private(set) var lastOdometerAt: Date?

    /// The driver's own estimate of km per full tank. Preferred over the logged
    /// history because it is a deliberate, conservative figure; the history is
    /// the fallback until one is entered.
    var rangePerTankKm: Int? {
        didSet {
            if let rangePerTankKm {
                UserDefaults.standard.set(rangePerTankKm, forKey: Self.rangeKey)
            } else {
                UserDefaults.standard.removeObject(forKey: Self.rangeKey)
            }
        }
    }

    /// Low-range notification: on/off, and the km-left threshold. A second alert
    /// fires at half of it, and a third past the estimate. See `RangeAlerter`.
    var alertsEnabled: Bool {
        didSet { UserDefaults.standard.set(alertsEnabled, forKey: Self.alertsKey) }
    }
    var alertThresholdKm: Int {
        didSet { UserDefaults.standard.set(alertThresholdKm, forKey: Self.thresholdKey) }
    }

    private static let fillUpsKey = "jeep.fillUps"
    private static let rangeKey = "jeep.rangePerTankKm"
    private static let alertsKey = "jeep.alertsEnabled"
    private static let thresholdKey = "jeep.alertThresholdKm"
    private static let odometerKey = "jeep.lastOdometerKm"
    private static let odometerAtKey = "jeep.lastOdometerAt"

    init() {
        let defaults = UserDefaults.standard
        alertsEnabled = defaults.object(forKey: Self.alertsKey) as? Bool ?? true
        alertThresholdKm = defaults.object(forKey: Self.thresholdKey) as? Int ?? 100
        if let data = defaults.data(forKey: Self.fillUpsKey),
           let saved = try? JSONDecoder().decode([FillUp].self, from: data) {
            fillUps = saved
        }
        if defaults.object(forKey: Self.odometerKey) != nil {
            lastOdometerKm = defaults.integer(forKey: Self.odometerKey)
            lastOdometerAt = defaults.object(forKey: Self.odometerAtKey) as? Date
        }
        if defaults.object(forKey: Self.rangeKey) != nil {
            rangePerTankKm = defaults.integer(forKey: Self.rangeKey)
        }
    }

    /// Record a full tank now.
    ///
    /// At the pump the ignition is usually off and the bus silent, so there may
    /// be no live odometer. Then the fill-up is left pending and takes the next
    /// odometer the car reports - exact, because the car cannot have moved
    /// before it is switched back on.
    func fillUp(liveOdometerKm: Int?) {
        fillUps.append(FillUp(date: .now, odometerKm: liveOdometerKm))
        save()
    }

    /// Feed every valid odometer reading here.
    func observe(odometerKm: Int) {
        var changed = false
        for i in fillUps.indices where fillUps[i].odometerKm == nil {
            fillUps[i].odometerKm = odometerKm
            changed = true
        }
        if changed { save() }
        if odometerKm != lastOdometerKm {
            lastOdometerKm = odometerKm
            lastOdometerAt = .now
            UserDefaults.standard.set(odometerKm, forKey: Self.odometerKey)
            UserDefaults.standard.set(lastOdometerAt, forKey: Self.odometerAtKey)
        }
    }

    func delete(_ fillUp: FillUp) {
        fillUps.removeAll { $0.id == fillUp.id }
        save()
    }

    /// Replace a fill-up after editing. Re-sorted by date, because the distance
    /// each tank went is computed between neighbours.
    func update(_ fillUp: FillUp) {
        guard let i = fillUps.firstIndex(where: { $0.id == fillUp.id }) else { return }
        fillUps[i] = fillUp
        fillUps.sort { $0.date < $1.date }
        save()
    }

    var lastFillUp: FillUp? { fillUps.last }

    /// km driven since the last fill-up, or nil if either end is unknown.
    func kmSinceFillUp(currentKm: Int?) -> Int? {
        guard let start = lastFillUp?.odometerKm, let now = currentKm ?? lastOdometerKm
        else { return nil }
        return max(0, now - start)
    }

    /// How far each completed tank went, newest first. Only intervals with an
    /// odometer at both ends count.
    var tankDistances: [Int] {
        let known = fillUps.compactMap(\.odometerKm)
        guard known.count >= 2 else { return [] }
        return zip(known.dropFirst(), known).map { $0 - $1 }.filter { $0 > 0 }.reversed()
    }

    /// Typical km per tank: the median of the last five, so one short top-up
    /// that was logged as full cannot drag it far.
    var typicalTankKm: Int? {
        let recent = Array(tankDistances.prefix(5)).sorted()
        guard !recent.isEmpty else { return nil }
        return recent[recent.count / 2]
    }

    /// What the gauge is scaled to: the driver's estimate, else the history.
    var effectiveRangeKm: Int? { rangePerTankKm ?? typicalTankKm }

    /// Estimated km left, or nil without a range or a known fill-up.
    func remainingKm(currentKm: Int?) -> Int? {
        guard let range = effectiveRangeKm, let since = kmSinceFillUp(currentKm: currentKm)
        else { return nil }
        return range - since
    }

    private func save() {
        if let data = try? JSONEncoder().encode(fillUps) {
            UserDefaults.standard.set(data, forKey: Self.fillUpsKey)
        }
    }
}

// MARK: - View

struct JeepView: View {
    @Environment(\.appearance) private var appearance
    let frame: TelemetryFrame
    let isStale: Bool

    /// Shared with the background alerter, so it is owned by `AppServices`, not
    /// by this view - see JeepAlerts.swift.
    let log: FuelLog

    @State private var confirmingFillUp = false
    @State private var editingRange = false
    @State private var editingFillUp: FillUp?
    @State private var deletingFillUp: FillUp?

    /// Valid and fresh, or nil. Never a 0 standing in for "no answer".
    private var liveOdometer: Int? {
        guard !isStale, VehicleMetric.odometer.isValid(in: frame) else { return nil }
        return Int(frame.odometerKm)
    }

    private var kmSince: Int? { log.kmSinceFillUp(currentKm: liveOdometer) }

    var body: some View {
        VStack(spacing: 12) {
            sinceFillUpCard
            fillUpButton
            liveRow
            if !log.fillUps.isEmpty { history }
        }
        .task {
            if log.alertsEnabled { RangeAlerter.requestPermission() }
        }
        .sheet(isPresented: $editingRange) {
            RangeEntrySheet(log: log)
        }
        .sheet(item: $editingFillUp) { fill in
            EditFillUpSheet(log: log, fillUp: fill)
        }
        // Deleting is two deliberate steps: the row's menu, then this.
        .confirmationDialog(
            "Delete this fill-up?",
            isPresented: Binding(
                get: { deletingFillUp != nil },
                set: { if !$0 { deletingFillUp = nil } }
            ),
            titleVisibility: .visible,
            presenting: deletingFillUp
        ) { fill in
            Button("Delete", role: .destructive) { log.delete(fill) }
        } message: { fill in
            Text("The record from \(fill.date.formatted(date: .abbreviated, time: .shortened)) will be removed. This can't be undone.")
        }
        .confirmationDialog(
            "Record a full tank?",
            isPresented: $confirmingFillUp,
            titleVisibility: .visible
        ) {
            Button("Filled up") { log.fillUp(liveOdometerKm: liveOdometer) }
        } message: {
            if let km = liveOdometer {
                Text("At \(km.formatted()) km. Only press this after filling the tank completely.")
            } else {
                Text("The car isn't reporting its odometer right now. The next reading it sends will be used; it can't have moved before then. Only press this after filling the tank completely.")
            }
        }
    }

    // MARK: Since fill-up

    private var sinceFillUpCard: some View {
        VStack(spacing: 6) {
            Text("SINCE FILL-UP")
                .font(appearance.labelFont(size: 13))
                .foregroundStyle(.secondary)

            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(kmSince.map { $0.formatted() } ?? "—")
                    .font(appearance.valueFont(size: 72))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .animation(.default, value: kmSince)
                if kmSince != nil {
                    Text("km")
                        .font(appearance.valueFont(size: 28))
                        .foregroundStyle(.secondary)
                }
            }

            Text(caption)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            rangeSection
                .padding(.top, 8)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
        .padding(.horizontal, 16)
        .background(.fill.tertiary, in: .rect(cornerRadius: 20))
    }

    // MARK: Range and simulated gauge

    @ViewBuilder
    private var rangeSection: some View {
        if let range = log.effectiveRangeKm {
            let left = kmSince.map { range - $0 }
            VStack(spacing: 6) {
                SimulatedFuelGauge(
                    fraction: kmSince.map { 1 - Double($0) / Double(range) },
                    accent: appearance.accent,
                    hot: appearance.hot
                )
                .frame(height: 96)

                if let left, log.alertsEnabled, left <= log.alertThresholdKm {
                    Label(left > 0 ? String(localized: "Fill up soon") : String(localized: "Fill up now"),
                          systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(appearance.hot, in: .capsule)
                }

                if let left {
                    Text(left > 0
                         ? String(localized: "≈ \(left.formatted()) km left")
                         : String(localized: "Past your range estimate"))
                        .font(.headline)
                        .foregroundStyle(left > range / 8 ? appearance.accent : appearance.hot)
                }

                Button {
                    editingRange = true
                } label: {
                    Text(log.rangePerTankKm == nil
                         ? String(localized: "Range from your fill-up history: \(range.formatted()) km · Set your own")
                         : String(localized: "Range per tank: \(range.formatted()) km · Edit"))
                        .font(.caption)
                }

                // Said plainly, because a convincing gauge invites trust it has
                // not earned: nothing here measures fuel.
                Text("Simulated from distance driven. Not a fuel measurement.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        } else {
            Button {
                editingRange = true
            } label: {
                Label("Set range per tank for a fuel gauge", systemImage: "gauge.with.dots.needle.33percent")
                    .font(.subheadline.weight(.semibold))
            }
            .buttonStyle(.bordered)
        }
    }

    private var caption: String {
        guard let last = log.lastFillUp else {
            return String(localized: "Press Filled up next time you fill the tank.")
        }
        if last.odometerKm == nil {
            return String(localized: "Filled up \(Self.daysAgo(last.date)) · waiting for the car to report its odometer")
        }
        if liveOdometer == nil, let at = log.lastOdometerAt {
            return String(localized: "Car not reporting · as of \(at.formatted(.relative(presentation: .named)))")
        }
        return String(localized: "Filled up \(Self.daysAgo(last.date))")
    }

    /// "today", "yesterday", "3 days ago" (오늘, 어제, 3일 전): whole calendar
    /// days, because a fill-up's age in minutes is noise.
    private static func daysAgo(_ date: Date) -> String {
        let calendar = Calendar.current
        let days = calendar.dateComponents(
            [.day], from: calendar.startOfDay(for: date), to: calendar.startOfDay(for: .now)
        ).day ?? 0
        let formatter = RelativeDateTimeFormatter()
        formatter.dateTimeStyle = .named
        formatter.unitsStyle = .full
        return formatter.localizedString(from: DateComponents(day: -max(0, days)))
    }

    // MARK: Button

    private var fillUpButton: some View {
        Button {
            confirmingFillUp = true
        } label: {
            Label("Filled up", systemImage: "fuelpump.fill")
                .font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
    }

    // MARK: Live values

    private var liveRow: some View {
        HStack(spacing: 12) {
            liveCell(String(localized: "Odometer"), VehicleMetric.odometer, "%.0f", "km")
            liveCell(String(localized: "Speed"), VehicleMetric.speed, "%.0f", "km/h")
            liveCell(String(localized: "Engine"), VehicleMetric.rpm, "%.0f", "rpm")
        }
    }

    private func liveCell(_ title: String, _ metric: VehicleMetric,
                          _ format: String, _ unit: String) -> some View {
        let valid = !isStale && metric.isValid(in: frame)
        return VStack(spacing: 2) {
            Text(title.uppercased())
                .font(appearance.labelFont(size: 11))
                .foregroundStyle(.secondary)
            Text(valid ? String(format: format, metric.value(from: frame)) : "—")
                .font(appearance.valueFont(size: 22))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(unit)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .background(.fill.tertiary, in: .rect(cornerRadius: 14))
    }

    // MARK: History

    private var history: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("FILL-UPS")
                .font(appearance.labelFont(size: 13))
                .foregroundStyle(.secondary)
                .padding(.bottom, 8)

            // Newest first. Each row shows how far the tank it started went.
            let rows = Array(log.fillUps.enumerated()).reversed()
            ForEach(rows, id: \.element.id) { index, fill in
                let next = index + 1 < log.fillUps.count ? log.fillUps[index + 1] : nil
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(fill.date.formatted(date: .abbreviated, time: .shortened))
                        Text(fill.odometerKm.map { "\($0.formatted()) km" }
                             ?? String(localized: "odometer pending"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let start = fill.odometerKm, let end = next?.odometerKm {
                        Text("\((end - start).formatted()) km")
                            .monospacedDigit()
                    } else if next == nil {
                        Text("current")
                            .foregroundStyle(.secondary)
                    }
                    Menu {
                        Button("Edit", systemImage: "pencil") {
                            editingFillUp = fill
                        }
                        Button("Delete", systemImage: "trash", role: .destructive) {
                            deletingFillUp = fill
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                            .frame(width: 32, height: 32)
                            .contentShape(.rect)
                    }
                    .foregroundStyle(.secondary)
                }
                .padding(.vertical, 8)
                Divider()
            }
        }
        .padding(16)
        .background(.fill.tertiary, in: .rect(cornerRadius: 20))
    }
}

// MARK: - Simulated gauge

/// A half-dial fuel gauge, E to F, driven by `fraction` (1 = full). Not a
/// measurement: it is km since fill-up against a range estimate. nil draws an
/// empty dial with no needle - unknown, never shown as empty.
struct SimulatedFuelGauge: View {
    let fraction: Double?
    let accent: Color
    let hot: Color

    private var clamped: Double? { fraction.map { min(1, max(0, $0)) } }

    private var colour: Color {
        guard let f = clamped else { return .secondary }
        return f > 0.25 ? accent : (f > 0.1 ? .orange : hot)
    }

    var body: some View {
        GeometryReader { geo in
            let lineWidth: CGFloat = 12
            let radius = min(geo.size.width / 2, geo.size.height) - lineWidth
            let centre = CGPoint(x: geo.size.width / 2, y: geo.size.height - 4)
            ZStack {
                arc(centre, radius, to: 1)
                    .stroke(.fill.secondary, style: .init(lineWidth: lineWidth, lineCap: .round))
                if let f = clamped {
                    arc(centre, radius, to: f)
                        .stroke(colour, style: .init(lineWidth: lineWidth, lineCap: .round))
                        .animation(.easeInOut, value: f)
                    needle(centre, radius - lineWidth, f)
                        .stroke(.primary, style: .init(lineWidth: 3, lineCap: .round))
                        .animation(.easeInOut, value: f)
                }
                Circle().fill(.primary).frame(width: 10, height: 10).position(centre)
                Text("E").font(.caption.bold())
                    .foregroundStyle(hot)
                    .position(x: centre.x - radius, y: centre.y + 2)
                    .offset(y: -lineWidth * 1.6)
                Text("F").font(.caption.bold())
                    .position(x: centre.x + radius, y: centre.y + 2)
                    .offset(y: -lineWidth * 1.6)
                Image(systemName: "fuelpump.fill")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .position(x: centre.x, y: centre.y - radius * 0.45)
            }
        }
        .accessibilityElement()
        .accessibilityLabel("Simulated fuel gauge")
        .accessibilityValue(clamped.map { String(localized: "\(Int($0 * 100)) percent") }
                            ?? String(localized: "unknown"))
    }

    /// From E (180 deg) clockwise over the top toward F (360 deg), `to` of the way.
    private func arc(_ c: CGPoint, _ r: CGFloat, to f: Double) -> Path {
        Path { p in
            p.addArc(center: c, radius: r, startAngle: .degrees(180),
                     endAngle: .degrees(180 + 180 * f), clockwise: false)
        }
    }

    private func needle(_ c: CGPoint, _ length: CGFloat, _ f: Double) -> Path {
        let angle = Angle.degrees(180 + 180 * f).radians
        return Path { p in
            p.move(to: c)
            p.addLine(to: CGPoint(x: c.x + length * cos(angle), y: c.y + length * sin(angle)))
        }
    }
}

// MARK: - Range entry

struct RangeEntrySheet: View {
    let log: FuelLog
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @FocusState private var focused: Bool

    private var value: Int? { Int(text.trimmingCharacters(in: .whitespaces)).flatMap { $0 > 0 ? $0 : nil } }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        TextField("e.g. 450", text: $text)
                            .keyboardType(.numberPad)
                            .focused($focused)
                            .font(.title2.monospacedDigit())
                        Text("km")
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Range per full tank")
                } footer: {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("**Be conservative.** Enter a distance you are sure a full tank covers, well under your best tank. The gauge is only distance against this number. Set it too high and it will read fuel you don't have, and running dry costs far more than stopping early.")
                        if let typical = log.typicalTankKm {
                            Text("Your logged tanks went \(typical.formatted()) km (median). Consider entering less than that.")
                        }
                    }
                }

                if log.rangePerTankKm != nil {
                    Section {
                        Button("Use fill-up history instead", role: .destructive) {
                            log.rangePerTankKm = nil
                            dismiss()
                        }
                    }
                }
            }
            .navigationTitle("Range per Tank")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        log.rangePerTankKm = value
                        dismiss()
                    }
                    .disabled(value == nil)
                }
            }
            .onAppear {
                text = log.rangePerTankKm.map(String.init) ?? ""
                focused = true
            }
        }
        .presentationDetents([.medium])
    }
}

// MARK: - Edit fill-up

struct EditFillUpSheet: View {
    let log: FuelLog
    let fillUp: FillUp
    @Environment(\.dismiss) private var dismiss
    @State private var date = Date.now
    @State private var odometerText = ""
    @State private var confirmingSave = false

    private var odometer: Int? {
        Int(odometerText.trimmingCharacters(in: .whitespaces)).flatMap { $0 > 0 ? $0 : nil }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    DatePicker("Date", selection: $date, in: ...Date.now)
                    HStack {
                        TextField("Odometer", text: $odometerText)
                            .keyboardType(.numberPad)
                            .monospacedDigit()
                        Text("km").foregroundStyle(.secondary)
                    }
                } footer: {
                    Text("Use the odometer reading at the moment the tank was filled. Leave it empty to take the next reading the car reports.")
                }
            }
            .navigationTitle("Edit Fill-up")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { confirmingSave = true }
                        .disabled(!odometerText.isEmpty && odometer == nil)
                }
            }
            .confirmationDialog("Save changes to this fill-up?",
                                isPresented: $confirmingSave, titleVisibility: .visible) {
                Button("Save") {
                    var edited = fillUp
                    edited.date = date
                    edited.odometerKm = odometer
                    log.update(edited)
                    dismiss()
                }
            }
            .onAppear {
                date = fillUp.date
                odometerText = fillUp.odometerKm.map(String.init) ?? ""
            }
        }
        .presentationDetents([.medium])
    }
}

#Preview {
    JeepView(frame: .preview(), isStale: false, log: FuelLog())
        .padding()
}

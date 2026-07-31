# iPhone app — BLE central

Area 3 of three; see [repository layout](../README.md#repository-layout).

The app connects to the [appliance](../appliance/README.md) as a **BLE central**,
subscribes to the telemetry characteristic, and renders live vehicle signals.

## Structure

Xcode project at `Casper CAN/`, SwiftUI, iOS 26.5 deployment target. Files are in
a filesystem-synchronized group, so adding a `.swift` file to
`Casper CAN/Casper CAN/` puts it in the target automatically — no project-file
edit needed.

| File | Role |
|---|---|
| `TelemetryWire.swift` | Wire contract v3: UUIDs, 78-byte frame decode, 34-metric catalogue |
| `BLEClient.swift` | CoreBluetooth central — scan, connect, subscribe, decode |
| `DashboardConfig.swift` | Which tiles are shown, in what order, drawn how; persisted |
| `GaugeViews.swift` | The four gauge styles, the no-data state, the dashboard tile |
| `ContentView.swift` | Dashboard grid, connection banner, recording banner |
| `MetricPickerView.swift` | Add/remove/reorder measurements |
| `MetricSettingsView.swift` | Per-measurement style, range, redline |
| `Recorder.swift` | Writes received frames to CSV in Documents |
| `RecordingsView.swift` | Browse, share and delete recordings |
| `Appearance.swift` | Typeface, weight, palette, light/dark; persisted separately from the dashboard |
| `AppearanceView.swift` | Appearance settings with a live hero-sized sample |
| `DerivedInfoView.swift` | Explains a derived metric — formula, inputs, assumptions — before it can be added |
| `SettingsView.swift` | One sheet, two areas: Metrics and Appearance |

`INFOPLIST_KEY_NSBluetoothAlwaysUsageDescription` is set in build settings for
both configurations. Without it the app crashes the moment it scans.

### Build traps already hit here

- **A synchronized group can classify a `.swift` file as a bundle resource
  instead of a source file.** This happened to `Telemetry.swift`: Xcode ran
  `Copy Telemetry.swift` into the `.app` and never emitted a `SwiftCompile` task
  for it, so every type it declared was missing and the errors all appeared in
  *other* files (`cannot find type 'TelemetryFrame' in scope`). Worse, the
  shadowed name `Measurement` silently resolved to Foundation's generic
  `Measurement<UnitType>`, producing misleading errors like
  `Type 'Measurement<Unit>' has no member 'allCases'` that pointed at the
  innocent file. **Renaming the file** (to `TelemetryWire.swift`) made Xcode
  reclassify it correctly.

  Diagnose it from Xcode's own build log rather than by reading code — the
  discrepancy is invisible in the source and in `project.pbxproj`:

  ```
  L=$(ls -t ~/Library/Developer/Xcode/DerivedData/<Proj>-*/Logs/Build/*.xcactivitylog | head -1)
  gunzip -c "$L" | tr -d '\000' | grep -aoE "SwiftCompile.*YourFile\.swift"   # want >= 1
  gunzip -c "$L" | tr -d '\000' | grep -aoE "Copy YourFile\.swift"            # want 0
  find <built .app> -name '*.swift'    # want none: a copied source ships in the bundle
  ```

- **`xcodebuild` succeeding does not mean Xcode will build.** The two disagreed
  for exactly the reason above — the CLI compiled the file, Xcode copied it.
  Trust Xcode's Issue navigator or its build log, not a green CLI run.

- **Avoid the type name `Measurement`** regardless. Shadowing
  `Foundation.Measurement<UnitType>` turns a missing-file problem into a
  confusing generics error. The catalogue is `VehicleMetric`.
- **This project sets `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`** and
  `SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY = YES`. So every type is
  main-actor isolated unless stated otherwise — passing an initializer as a bare
  function reference (`map(MetricConfig.init)`) crosses isolation and warns,
  while calling it inside a non-escaping closure (`map { MetricConfig($0) }`)
  inherits the caller's isolation. Member-import visibility also means a symbol
  needs its defining module imported *in that file*, which is what made a
  `Timer.publish` chain fail without `import Combine`.

## Behaviour

- Scans by **service UUID**, not local name, so `--name` on the board doesn't
  break discovery. Auto-reconnects on drop.
- Reads telemetry once on connect so the dashboard renders immediately, then
  subscribes for notifications.
- **34 metrics** — every signal the appliance can report. The picker groups the
  available ones by subject (motion & driver input, steering, temperatures,
  fuelling & air, fuel/distance/time, electrical & faults) with an "add every
  metric" button. The dashboard starts with a curated ten, because showing all 34
  on first launch would bury the ones that matter.
- **Layout favours the gauges.** The navigation bar is hidden entirely — a large
  title costs ~96 pt and tells the driver nothing. The top is one compact strip:
  connection state, notification rate, and a single settings button (which splits
  into Metrics and Appearance inside, since space is free there and scarce in the
  strip). Warnings appear there as wrapping chips only when they exist.
  Recording and the recordings list sit at the **end of the scrolled content**,
  not in a pinned bar — a sticky footer costs its own height on every screen for
  the whole drive, whereas a control touched twice per drive can afford to be
  scrolled to.
- **Appearance is configurable**: four typefaces (Rounded, Neutral, Technical,
  Serif), five weights, six colour palettes, and a light/dark override. Each
  palette defines *both* the accent and the past-redline colour, because a warm
  accent needs a different warning colour to stay separable. Defaults are Neutral
  / Semibold / Blue — the rounded bold original read as toy-like.
- **Uniform square tiles** in a fixed two-column grid, so the dashboard tiles
  tightly with no ragged edges, plus one optional **hero** tile at exactly 2×2.
  A full-width square is precisely two cells wide and two tall including the
  gutter, so the hero needs no custom layout. Gauges size themselves from the
  space they are given rather than using fixed heights — the same view has to look
  right at both scales.
- Four display styles: **number**, **circular gauge**, **linear bar**, and
  **indicator lamp**. Per-metric range and redline are user-editable, with a live
  preview in the settings screen.
- Signed quantities (steering angle, torque) fill a linear bar outward from the
  centre and can mirror their redline to the negative side.
- Red means one thing only — past the redline — so the dashboard answers "is
  anything wrong?" without reading a number.
- **Numbers snap, geometry glides.** The digits are not animated — a numeric
  content transition cross-fades every change into a blur at these update rates.
  Arc and bar *fills* are the opposite case: un-animated they jump in visible steps
  at a slow rate, so they get a short linear interpolation. That window is
  **rate-adaptive** — derived from the measured notification rate, capped at 0.25 s,
  and switched off entirely above ~7 Hz, where the stream is already smoother than
  any interpolation and animating would leave the fill several updates behind while
  burning CPU across 34 tiles. Boolean state (redline border, indicator lamp)
  animates regardless, where a hard flip would strobe.
- **Per-signal "no data"**, driven by the frame's validity bits. A metric the car
  did not answer shows a question mark, never a zero. This is distinct from
  link staleness: with the ignition off the BLE link is healthy and every signal
  is invalid.
- Warns explicitly when the board is serving **synthetic data**, when no signal
  at all is valid ("ignition off, or adapter unplugged"), when the board reports
  **failed polls**, and when a frame arrives with the **wrong length** — each of
  which would otherwise be mistaken for real vehicle data.
- **Recording** to CSV, started from the dashboard. Rows are written from the BLE
  callback, so the recorded rate is the notification rate rather than the screen
  refresh rate, and the column set is the whole frame — including validity as
  hex — rather than whatever happened to be on screen. Export with the share
  sheet from the recordings list.

## Derived metrics

Computed **on the phone** from signals already in the frame — no wire change, no
extra bus traffic, no new PIDs. A derived metric requires *every* input to be
valid, so it reads "no data" rather than being quietly wrong when the car answered
only part of a request.

| Metric | Formula | Notes |
|---|---|---|
| Boost (psi / bar) | `MAP − barometric` | Both PIDs are **absolute** kPa, so the difference is gauge pressure. Negative is manifold vacuum — normal off throttle, hence a bipolar gauge |
| Intake Rise | `intake air − ambient` | Charge heat soak; on a turbo, how much work the charge cooling is not doing |
| Total Fuel Trim | `short + long` | The conventional diagnostic reading |
| Charge Density | `ρ = P / (R·T)`, g/L | Ideal gas law on absolute MAP and intake temperature |
| Speed / 1000 rpm | `speed ÷ rpm × 1000` | Direct proxy for overall gear ratio; steps as the transmission shifts |
| Throttle vs Pedal | `commanded throttle − pedal D` | A persistent negative gap means the ECM is giving less than asked: torque limiting, traction control, or a protection mode |
| Acceleration | `Δspeed ÷ Δt` | Differentiated on the board's **monotonic uptime**, not arrival time, so BLE jitter cannot show up as phantom acceleration |
| Steering Rate | `Δangle ÷ Δt` | Same |

### The estimates, and why they are labelled

`Air Flow (est.)`, `Fuel Rate (est.)`, `Economy (est.)` and `Range (est.)` are a
**speed-density engine model**, not measurements. This car has **no MAF sensor and
no fuel-rate PID** ([docs/04 §2.1](../docs/04-signal-reference.md)), so there is
nothing to read:

```
MAF  (g/s) = (rpm / 120) × displacement × VE × charge density
fuel (g/s) = MAF / (14.7 × λ)
L/h        = fuel ÷ fuel density × 3600
L/100km    = L/h ÷ speed × 100
```

`rpm / 120` because a four-stroke fills its displacement once per two crank
revolutions. Constants live in `EngineModel`: 998 cc for this 1.0 T-GDI, a **flat
volumetric efficiency of 0.90**, 14.7:1 stoichiometric, 745 g/L fuel density.
Commanded equivalence ratio is read from the car rather than assumed, so
enrichment under load is reflected.

The flat VE is the largest error source — a real VE varies roughly 0.7–1.0 with
rpm and load, and errors scale air and fuel proportionally. Range compounds that
with a fuel level that sloshes (docs/04 §4.2 measured a 3.6-point swing during one
drive). Sanity check at idle: 764 rpm, 35 kPa MAP, 32 °C intake gives ~2.3 g/s air
and ~0.75 L/h, which is the right order for a 1.0 L engine.

**These must never be cited as findings.** Under this repository's confidence
scale they are not measurements at any level — every title carries `(est.)`.

Adding a derived metric is therefore a **two-step action**. Tapping one in the
picker opens `DerivedInfoView`, which shows the formula, the signals it needs, what
the number means, and its assumptions and limits — with a prominent
"this is an estimate, not a measurement" banner for the four modelled ones. Only
then can it be added. A single-tap add would put a modelled number on the dashboard
looking exactly as authoritative as measured speed, which is the failure this whole
design guards against. Measured metrics still add with one tap.

## What the app implements

The wire contract is defined by the appliance and documented in full at
[appliance/README.md § Wire contract](../appliance/README.md#wire-contract).
In brief:

- Scan for local name `CasperCAN` (or filter on the service UUID
  `6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00`).
- Subscribe to telemetry `6e1a0002-…` for notifications; **read** it once on
  connect to render immediately rather than waiting for the first notification.
- Decode the fixed **78-byte little-endian** frame (wire version 3). Little-endian is deliberate —
  it matches the iPhone's native byte order, so the struct maps directly with no
  byteswap.
- Read status `6e1a0003-…` (JSON) to confirm wire version and which source the
  board is running — synthetic or real CAN.

Keep the UUIDs and the struct layout in a single Swift file mirroring
`../appliance/wire.py`. When the layout changes, both sides must change in the
same commit and `WIRE_VERSION` must be bumped; the `wire_version` field in status
exists to make a mismatch detectable rather than silently wrong.
`uv run appliance/selftest.py` checks the Python half against that contract
without needing a car, an adapter or a phone.

## Development notes

- The board runs the peripheral with a **synthetic data source by default**, so
  the app can be developed anywhere — no car, no CAN adapter, no ignition.
- Before the app can scan, validate the peripheral with **nRF Connect** or
  **LightBlue** on the phone. If those cannot see it, the problem is the board,
  not the app.
- In-car development uses the **iPhone's own hotspot** for the Mac↔board SSH
  link. The phone is therefore hotspot and BLE central simultaneously — fine,
  they are separate radios on the phone side.
- Pairing is PIN-less (`NoIoAgent` on the board), since the board has no input
  device in the car.

## Undecided

- Whether the recording CSV should be converted to the JSONL + summary shape
  that `../experimentation/plot_journey.py` reads, so the same plots work for
  phone-recorded and Mac-recorded drives. Currently the columns are close but not
  identical.
- Whether the app ever writes to the vehicle. Everything in this repository is
  read-only today, and [docs/00-safety.md](../docs/00-safety.md) is normative
  about why.
- Whether to keep the connection alive in the background, which would let a
  recording survive the screen locking mid-drive. Needs the
  `bluetooth-central` background mode and careful thought about battery.

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
| `TelemetryWire.swift` | Wire contract: UUIDs, 12-byte frame decode, `VehicleMetric` catalogue |
| `BLEClient.swift` | CoreBluetooth central — scan, connect, subscribe, decode |
| `DashboardConfig.swift` | Which tiles are shown, in what order, drawn how; persisted |
| `GaugeViews.swift` | The four gauge styles plus the dashboard tile |
| `ContentView.swift` | Dashboard grid and connection banner |
| `MetricPickerView.swift` | Add/remove/reorder measurements |
| `MetricSettingsView.swift` | Per-measurement style, range, redline |

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
- Four display styles: **number**, **circular gauge**, **linear bar**, and
  **indicator lamp**. Per-measurement range and redline are user-editable, with
  a live preview in the settings screen.
- Signed quantities (steering angle, torque) fill a linear bar outward from the
  centre and can mirror their redline to the negative side.
- Red means one thing only — past the redline — so the dashboard answers "is
  anything wrong?" without reading a number.
- Warns explicitly when the board is serving **synthetic data** or reports a
  **mismatched wire version**, since either would otherwise look like real
  vehicle data. Tiles dim when frames stop arriving.

## What the app implements

The wire contract is defined by the appliance and documented in full at
[appliance/README.md § Wire contract](../appliance/README.md#wire-contract).
In brief:

- Scan for local name `CasperCAN` (or filter on the service UUID
  `6e1a0001-8b2f-4d3a-9c47-2f5b7a1e9d00`).
- Subscribe to telemetry `6e1a0002-…` for notifications; **read** it once on
  connect to render immediately rather than waiting for the first notification.
- Decode the fixed **12-byte little-endian** frame. Little-endian is deliberate —
  it matches the iPhone's native byte order, so the struct maps directly with no
  byteswap.
- Read status `6e1a0003-…` (JSON) to confirm wire version and which source the
  board is running — synthetic or real CAN.

Keep the UUIDs and the struct layout in a single Swift file mirroring the
`TELEMETRY_STRUCT` definition in `../appliance/ble_peripheral.py`. When the
layout changes, both sides must change together; the `wire_version` field in
status exists to make a mismatch detectable rather than silently wrong.

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

Not yet chosen — worth deciding before the first real commit here:

- Native SwiftUI + CoreBluetooth, or a cross-platform framework. CoreBluetooth
  is the natural fit for a BLE-centric app.
- Whether the app logs telemetry to disk, and if so whether that log format
  should match `../experimentation/captures/journeys/` so the existing
  `plot_journey.py` can read it.
- Whether the app ever writes to the vehicle. Everything in this repository is
  read-only today, and [docs/00-safety.md](../docs/00-safety.md) is normative
  about why.

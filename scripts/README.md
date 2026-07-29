# Scripts guide

Everything runs via [`uv`](https://github.com/astral-sh/uv) with PEP 723 inline
dependencies - no venv to manage:

```
uv run scripts/<name>.py
```

**Python 3.14+.** All scripts declare `requires-python = ">=3.14"`. This matters:
the floor used to be `>=3.9`, and because uv satisfies a floor with the *oldest*
qualifying interpreter it finds, every script was silently running on macOS's
system Python **3.9.6** despite 3.14 being installed. Raising the floor is what
actually moves them onto a modern interpreter. Verified on 3.14.3 with `gs_usb`,
`pyusb` and `matplotlib` (3.11.1), including live USB device enumeration.

`libusb` is also needed for the CAN scripts: `brew install libusb`.

**If you just want to use the car, you need five scripts.** The rest are
reverse-engineering instruments or records of past investigations. Start here:

| I want to... | Run |
|---|---|
| Watch live data while driving | `dash.py` |
| Record a drive for later analysis | `journey_log.py`, then `plot_journey.py` |
| Check for fault codes | `read_dtcs.py` |
| Read odometer / maintenance / build info | `vehicle_info.py` |

## Safety - read once

Two rules, both learned the hard way (see the Safety Note in the root
`README.md`):

1. **Never send Diagnostic Session Control (`0x10`), DTC clearing (`0x14`),
   writes (`0x2E`) or actuation (`0x2F`) to ABS/ESC (`0x7D1`) or MDPS (`0x7D4`)
   while the vehicle is moving.** Forcing an extended session on this car
   reliably produces brake/ABS/traction warning lights for ~4 seconds.
2. Only **one** script can use the USB adapter at a time. A second one will see
   a silent bus and report "no PIDs supported" - which looks exactly like the
   ignition being off. If a script claims the car isn't answering, check nothing
   else is already running.

Every script below is **read-only** except `full_uds_scan.py`, which is the sole
script that sends session control. It is marked accordingly.

---

## Library

### `canbus.py` — shared plumbing (not run directly)

The gs_usb device wrapper, ISO-TP request/response, and the decode tables
(Mode 01 PIDs, DTC codes, negative-response codes, known ECU map). Day-2
scripts import it; day-1 scripts each carry their own older copy, deliberately
left alone so they still reflect the state they were run in.

Two things worth knowing if you extend it:

- **CAN reads must use a non-zero timeout.** libusb treats `timeout_ms=0` as
  "block forever", and because this car never broadcasts, there is never a frame
  to return. This hung the first version of `drain()` indefinitely.
- **Requests must be padded to DLC=8** (ISO 15765-4, with `0xAA`). This car's
  ECUs silently ignore short frames, which is indistinguishable from a sleeping
  gateway.

---

## Everyday tools

### `dash.py` — live dashboard

Curses TUI: block-digit speed, RPM bar, live **odometer and fuel litres** read
from the cluster, and every other supported value with magnitude bars. `q` quits.

Colour-coded by severity, matching `read_dtcs.py`: green normal, yellow worth
noticing, red act on it. Thresholds are coolant >=102/110 C, control-module
voltage outside 12.2-15.0 / 11.5-15.5 V, fuel <=15/8 %, RPM >=5200/6200. Colour
is always an accent on a labelled number, never the only signal, and it degrades
cleanly on a terminal without colour.

Because nothing broadcasts, every value is actively polled, so refresh rate is a
budget. Speed/RPM/throttle/load/pedal are polled every cycle; the remaining ~21
rotate one per cycle (~1s for a full rotation). A row dims only when its ECU
genuinely stops answering — the threshold is derived from the measured rotation
period, never a fixed number, or healthy rows grey out in a rolling band while
merely awaiting their turn. Header shows live Hz and the rotation period.

### `journey_log.py` — record a drive

```
uv run scripts/journey_log.py                # until Ctrl-C
uv run scripts/journey_log.py --duration 600
```

Ctrl-C ends a journey cleanly and still writes everything, so just hit it when
you park. Writes three files to `journeys/`:

- `.jsonl` — lossless event log; line 1 is metadata (VIN, PID list with units)
- `.csv` — wide, one row per second, forward-filled; for plotting
- `.summary.json` — duration, **exact odometer distance**, **litres burned and
  km/L**, max/avg speed, max RPM, moving vs idle split, DTCs present at start

Distance and fuel come from the cluster (`0xB002`) read at both ends of the trip,
so they're exact rather than integrated — the speed-integrated figure is kept
alongside as `distance_km` for comparison, and undercounts by a few percent.
`fuel_used_litres_est` (MAF-derived) is always `null` on this car, which has no
MAF sensor.

Caveat: fuel level sloshes with tank attitude, so `fuel_used_litres` is
meaningful over a decent distance and unreliable on a short hop. If the reading
appears to *rise*, the summary reports `null` rather than a negative economy.

### `plot_journey.py` — plot a journey (no adapter needed)

```
uv run scripts/plot_journey.py               # newest journey
uv run scripts/plot_journey.py --list        # show available columns
uv run scripts/plot_journey.py --columns Speed RPM "Engine Load"
```

Stacked small multiples, one measure per panel on a shared time axis —
deliberately *not* a twin-axis speed-vs-RPM overlay, which invents correlations
the data doesn't contain. Runs at home from the CSV.

### `read_dtcs.py` — fault codes

Three layers: the emissions/OBD-II layer on the ECM (MIL lamp, readiness
monitors, Modes 03/07/0A), UDS `0x19` across all 15 known ECUs, and a DTC-count
cross-check. Decodes to `P0123` / `P0123-87` form with ISO 14229-1 status flags
spelled out.

**Read the status flags, not just the code list.** On this car four DTCs are
present but only one has `confirmedDTC` set; the others have no failure bits at
all. A tool that printed only codes would report four faults on a car with one.

Cannot clear codes. That is deliberate.

### `vehicle_info.py` — maintenance, build record, odometer

```
uv run scripts/vehicle_info.py
uv run scripts/vehicle_info.py --find-value odo=8429.8 range=389   # dash values
uv run scripts/vehicle_info.py --odo-scan-wide                     # wider hunt

# The strongest technique - diff across a drive:
uv run scripts/vehicle_info.py --snapshot before.json
#   ...drive...
uv run scripts/vehicle_info.py --snapshot after.json --like before.json
uv run scripts/vehicle_info.py --diff before.json after.json      # no adapter
```

Maintenance-relevant Mode 01 values, the standard identification DID block
(`0xF186`-`0xF1A0`) on every ECU — part numbers, serials, HW/SW versions — plus
an odometer hunt.

**`--snapshot` / `--diff` is the strongest tool here.** Snapshot the cluster
before a drive, again after, then diff: it reports every numeric field that moved
and by how much, in both directions (a service countdown *falls*). A field that
advances +14 while you drive 14 km is causal. This is what confirmed the odometer
increments and identified the fuel field. Prefer it whenever the value can be
made to change. `--like` makes the second snapshot a fast re-read of only the
DIDs that responded the first time.

`--find-value N` searches every collected payload for a big-endian encoding of
`N` (1/2/3/4 bytes, 1x/10x/0.1x scaling) and is how the odometer was first
located. It rates each hit's confidence — **treat anything under ~100 as noise.**
An earlier version confidently "found" a 0.5 km trip meter inside an ECU serial
number; static build-record DIDs (`0xF180`-`0xF1FF`) are now excluded by default
and small/1-byte matches are rated LOW. Hits report their delta, so a field that
*truncates* (whole km against a displayed 8429.8) is visibly distinct from an
exact match.

---

## Reverse-engineering instruments

Reach for these when hunting a signal that isn't already decoded.

### `full_uds_scan.py` — ECU discovery ⚠️ **ONLY SCRIPT THAT SENDS SESSION CONTROL**

Scans `0x700`-`0x7FF` with Tester Present to find every responding ECU (14 on
this car), then queries identification DIDs and DTCs on each.

**Sends Diagnostic Session Control (extended session) to every ECU it finds,
including ABS/ESC and MDPS.** Parked, in P, parking brake + foot brake only.
Expect a transient "Check ESC" light. For routine work, `vehicle_info.py` and
`read_dtcs.py` get the same identification and DTC data in the *default* session,
with no warning lights — prefer them unless you specifically need rediscovery.

### `uds_cli.py` — interactive UDS shell

Read-only exploration: `list`, `scan`, `read <ecu> <did>`, `dtc`, `services`,
`raw`, plus in-memory `snapshot`/`diff`. Best for poking at one ECU
interactively. The built-in snapshots are in-memory and lost on exit — use the
two scripts below when you need them on disk.

### `snapshot_did.py` + `diff_did.py` — snapshot-diff method

```
uv run scripts/snapshot_did.py unlocked 7d0 0100 01ff
# physically change one thing
uv run scripts/snapshot_did.py locked   7d0 0100 01ff
uv run scripts/diff_did.py snapshot_unlocked.json snapshot_locked.json
```

Scans a DID range and persists positive responses as JSON, then diffs two
snapshots. This is the method that found door lock state and the AC compressor.

**Always take a control snapshot** (rescan with nothing changed) before trusting
a diff, and **always round-trip** back to the original state. Three separate
"clean" candidates have died on round-trip validation — some bytes are
slow-drifting counters that a quick back-to-back control test won't catch. Use it
for hidden binary states; use `vehicle_info.py --find-value` for anything shown
as a number.

---

## Situational

Not useful on the OBD port — kept because each is the right tool for a specific
job that hasn't happened yet.

### `can_sniff.py` — passive bitrate-sweeping sniffer

Sweeps common bitrates logging any received frame, reconnects if the adapter
drops out from vibration, and prints a countdown so it needs no interaction while
driving.

Returns **zero frames** on the OBD-II port, permanently — that gateway is
strictly request/response. But this is exactly the tool for the **next physical
milestone**: after splicing into the camera or MDPS harness, this is what you run
at the new tap point to find its bitrate and confirm traffic exists. Note that if
that bus is CAN FD, this adapter (STM32F072, classic CAN only) cannot see it at
all, and a silent result there would be ambiguous.

### `live_log_hda.py` — HDA engagement research log

Polls camera (`0x7C4`) and MDPS (`0x7D4`) DIDs plus ECM speed during a drive,
to hunt for an HDA engagement flag. Read-only, no session control.

Day-1 result was inconclusive: camera DIDs were completely static, and the only
near-discrete MDPS byte turned out to be a rolling alive-counter. Only the narrow
`0x0100`-`0x01FF` range was scanned, so this is "not found yet", not a hard
negative. Superseded by `journey_log.py` for general logging — keep it for
resuming this specific hunt over a wider DID range.

---

## Archive (`archive/`)

Superseded by day-2 tools. Kept, not deleted: they document the exact state the
day-1 findings were produced in.

| Script | Superseded by |
|---|---|
| `obd_isotp.py` — VIN / ECU name / DTCs on `0x7E0`+`0x7E1` | `vehicle_info.py` (VIN, identification) and `read_dtcs.py` (DTCs, all 15 ECUs) |
| `live_log.py` — 4-PID drive log to CSV | `journey_log.py` (26 PIDs, JSONL + CSV + summary, clean Ctrl-C) |

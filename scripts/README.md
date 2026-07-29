# 08 — Tool Reference

Reference for every tool in this repository. For the constraints governing their
use, see [Safety and Operating Precautions](../docs/00-safety.md).

---

## 1. Invocation

All tools run via [`uv`](https://github.com/astral-sh/uv) with PEP 723 inline
dependencies. No virtual environment is required.

```
uv run scripts/<name>.py
```

Requirements: **Python 3.14+**, and `libusb` for any tool that opens the adapter
(`brew install libusb` on macOS). See
[01 §5](../docs/01-physical-interface.md) for the full host software
specification.

## 2. Tool index

### 2.1 Operational tools

Four tools cover all routine use of the vehicle.

| Objective | Tool |
|---|---|
| Observe live data while driving | [`dash.py`](#dashpy) |
| Record a drive for later analysis | [`journey_log.py`](#journey_logpy), then [`plot_journey.py`](#plot_journeypy) |
| Read fault codes | [`read_dtcs.py`](#read_dtcspy) |
| Read odometer, maintenance values, build record | [`vehicle_info.py`](#vehicle_infopy) |

### 2.2 Investigation instruments

| Tool | Purpose |
|---|---|
| [`full_uds_scan.py`](#full_uds_scanpy) | Address-range discovery ⚠️ **sends session control** |
| [`uds_cli.py`](#uds_clipy) | Interactive UDS shell |
| [`snapshot_did.py`](#snapshot_didpy--diff_didpy) + `diff_did.py` | Snapshot-diff method |

### 2.3 Situational tools

| Tool | Applicable when |
|---|---|
| [`can_sniff.py`](#can_sniffpy) | A new physical tap point exists on an unknown segment |
| [`live_log_hda.py`](#live_log_hdapy) | Resuming the HDA engagement-flag search |

### 2.4 Library

| Module | Contents |
|---|---|
| [`canbus.py`](#canbuspy) | Shared adapter, ISO-TP and decode-table plumbing |

### 2.5 Classification

| Tool | Read-only | Sends session control |
|---|---|---|
| `full_uds_scan.py` | — | ⚠️ **Yes** |
| All others | ✅ Yes | No |

No tool in this repository can clear diagnostic trouble codes. See
[00 §3](../docs/00-safety.md).

---

## 3. Library

### `canbus.py`

Not run directly. Provides the `gs_usb` device wrapper, ISO-TP request/response
implementation, and decode tables (Mode 01 PIDs and their data lengths, DTC
codes, negative-response codes, known-module map).

Session-2 tools import it. Session-1 tools each carry their own earlier copy,
deliberately left unmodified so they continue to reflect the state their findings
were produced in.

Two constraints apply to any extension of this module:

1. **Frame reads must specify a non-zero timeout.** `libusb` treats
   `timeout_ms=0` as *block indefinitely*, and because this vehicle never
   broadcasts, there is never a frame to return.
2. **Requests must be padded to DLC=8** (ISO 15765-4, with `0xAA`). This
   vehicle's modules silently discard short frames.

Both are documented at [02 §2](../docs/02-network-architecture.md).

---

## 4. Operational tools

### `dash.py`

Live dashboard. Curses TUI presenting block-digit speed, an RPM bar, live
odometer and fuel quantity read from the cluster, and every other supported value
with magnitude bars. `q` quits.

**Colour coding** is consistent with `read_dtcs.py`: green normal, yellow worth
noticing, red act on it.

| Value | Yellow | Red |
|---|---|---|
| Coolant temperature | ≥102 °C | ≥110 °C |
| Control module voltage | outside 12.2–15.0 V | outside 11.5–15.5 V |
| Fuel level | ≤15 % | ≤8 % |
| Engine RPM | ≥5200 | ≥6200 |

Colour is always an accent on a labelled numeric value, never the sole carrier of
information, and degrades cleanly on a terminal without colour support.

**Polling budget.** Because nothing broadcasts, every value is actively polled,
making refresh rate a budget. Speed, RPM, throttle, load and pedal are polled
every cycle; the remaining ~21 values rotate one per cycle (~1 s for a full
rotation). Multi-PID batching fits the fast group plus one rotating value into a
single 6-PID request per cycle — see
[04 §5](../docs/04-signal-reference.md).

A row dims only when its module genuinely stops answering. The staleness
threshold is **derived from the measured rotation period**, never a fixed
constant; a fixed threshold greys out healthy rows in a rolling band while they
merely await their turn. The header displays live refresh rate and rotation
period.

### `journey_log.py`

Drive recorder.

```
uv run scripts/journey_log.py                # runs until Ctrl-C
uv run scripts/journey_log.py --duration 600
```

Ctrl-C terminates a journey cleanly and still writes all output, so it can simply
be interrupted on parking.

Writes three files to `journeys/`:

| File | Content |
|---|---|
| `.jsonl` | Lossless event log. Line 1 is metadata — VIN, PID list with units. |
| `.csv` | Wide format, one row per second, forward-filled. For plotting. |
| `.summary.json` | Duration, exact odometer distance, litres consumed, km/L, max and mean speed, max RPM, moving vs idle split, DTCs present at start |

Distance and fuel are read from the cluster (`0xB002`) at both ends of the trip,
so they are **exact** rather than integrated. The speed-integrated figure is
retained alongside as `distance_km` for comparison; it undercounts by a few
percent.

`fuel_used_litres_est` (MAF-derived) is always `null` on this vehicle, which has
no MAF sensor.

**Caveat.** Fuel level sloshes with tank attitude, so `fuel_used_litres` is
meaningful over a substantial distance and unreliable on a short hop. If the
reading appears to *rise*, the summary reports `null` rather than a negative
economy figure. See [04 §4.2](../docs/04-signal-reference.md).

### `plot_journey.py`

Renders a recorded journey. Requires no adapter — runs from the CSV.

```
uv run scripts/plot_journey.py               # newest journey
uv run scripts/plot_journey.py --list        # show available columns
uv run scripts/plot_journey.py --columns Speed RPM "Engine Load"
```

Output is stacked small multiples — one measure per panel on a shared time axis.
This is deliberately **not** a twin-axis speed-versus-RPM overlay, which would
imply correlations the data does not contain.

**Plotted peaks are attenuated; the summary is authoritative.** The `.csv` holds
one forward-filled row per second, downsampled from the full ~100 Hz `.jsonl`.
Transient peaks shorter than the sampling interval are therefore lost. On the
25-minute drive of 2026-07-29, the CSV's maximum RPM is **6114.5** against the
summary's **6335.0** — a 3.5 % understatement across 1493 rows condensed from
148,511 samples. Slow or coarsely-quantised measures are unaffected (peak speed
agrees exactly at 109 km/h). Quote maxima from `.summary.json`, which is computed
from the lossless log; read the plot for shape, not for extremes.

### `read_dtcs.py`

Fault-code reader covering three layers: the emissions/OBD-II layer on the ECM
(MIL lamp, readiness monitors, Modes 03/07/0A), UDS `0x19` across all 15 known
modules, and a DTC-count cross-check. Decodes to `P0123` / `P0123-87` form with
ISO 14229-1 status flags expanded.

**Read the status flags, not the code list.** On this vehicle four records are
present but only one has `confirmedDTC` set; the others carry no failure bit at
all. A tool printing only codes would report four faults on a vehicle with one.
See [05 — Diagnostics](../docs/05-diagnostics.md).

Cannot clear codes. This is deliberate.

### `vehicle_info.py`

Maintenance values, build record, odometer, and the signal-search tools.

```
uv run scripts/vehicle_info.py
uv run scripts/vehicle_info.py --find-value odo=8429.8 range=389
uv run scripts/vehicle_info.py --odo-scan-wide

# Snapshot/diff — the strongest available technique:
uv run scripts/vehicle_info.py --snapshot before.json
#   ...drive...
uv run scripts/vehicle_info.py --snapshot after.json --like before.json
uv run scripts/vehicle_info.py --diff before.json after.json     # no adapter
```

Reports maintenance-relevant Mode 01 values, the standard identification block
(`0xF186`–`0xF1A0`) on every module — part numbers, serials, hardware and
software versions — plus an odometer hunt.

**`--snapshot` / `--diff` is the strongest tool here.** Snapshot the cluster
before a drive, again afterwards, then diff: it reports every numeric field that
moved and by how much, in both directions (a service countdown *falls*). A field
that advances +14 while the vehicle travels 14 km is causal. This confirmed the
odometer increments and identified the fuel field. `--like` makes the second
snapshot a fast re-read of only the identifiers that responded the first time.

**`--find-value N`** searches every collected payload for a big-endian encoding
of `N` (1/2/3/4 bytes, at 1×/10×/0.1× scaling) and is how the odometer was first
located. It rates each hit's confidence — **treat anything under ~100 as noise.**
Static build-record identifiers (`0xF180`–`0xF1FF`) are excluded by default;
override with `--include-ident`. Hits report their delta and an `exact` flag, so a
field that truncates (whole km against a displayed 8429.8) is visibly distinct
from an exact match.

Full guidance on both techniques, including their known failure modes, is at
[07 — Methodology](../docs/07-methodology.md).

---

## 5. Investigation instruments

### `full_uds_scan.py`

⚠️ **The only tool that sends DiagnosticSessionControl.**

Scans `0x700`–`0x7FF` with TesterPresent to find every responding module (15 on
this vehicle), then queries identification identifiers and DTCs on each.

**Sends an extended-session request to every module it finds, including ABS/ESC
and MDPS.** Stationary only: in P, parking brake and foot brake applied. Expect a
transient "Check ESC" lamp.

For routine work, `vehicle_info.py` and `read_dtcs.py` obtain the same
identification and DTC data in the **default** session with no warning-lamp
exposure. Prefer them unless address rediscovery is specifically required.

### `uds_cli.py`

Interactive read-only UDS shell: `list`, `scan`, `read <ecu> <did>`, `dtc`,
`services`, `raw`, plus in-memory `snapshot` / `diff`. Best suited to
interactive exploration of a single module.

Its snapshots are held in memory and lost on exit; use `snapshot_did.py` when
they are needed on disk.

### `snapshot_did.py` + `diff_did.py`

Snapshot-diff method. Scans an identifier range, persists positive responses as
JSON, and diffs two snapshots.

```
uv run scripts/snapshot_did.py unlocked 7d0 0100 01ff
# physically change exactly one thing
uv run scripts/snapshot_did.py locked   7d0 0100 01ff
uv run scripts/diff_did.py snapshot_unlocked.json snapshot_locked.json
```

This is the method that located door lock state and the AC compressor.

**Always take a control snapshot** (rescan with nothing changed) and **always
round-trip** to the original state before trusting a result. Three separate
apparently clean candidates on this vehicle died on round-trip validation — some
bytes are slow-drifting counters that a back-to-back control test cannot catch.
The full rule set is at [07 §2](../docs/07-methodology.md).

Use this for hidden binary states; use `vehicle_info.py --find-value` for
anything displayed as a number.

---

## 6. Situational tools

Not useful at the diagnostic connector. Each is the correct instrument for a
specific task not yet reached.

### `can_sniff.py`

Passive bit-rate-sweeping sniffer. Sweeps common bit rates logging any received
frame, reconnects automatically if the adapter drops out from vibration, and
prints a countdown so it requires no interaction while driving.

Returns **zero frames** at the diagnostic connector, permanently — that gateway
is strictly request/response.

**This is the tool for the next physical milestone.** After tapping the camera or
MDPS harness, this is what determines the new segment's bit rate and confirms
traffic exists. Note that if that segment is CAN FD, this adapter (STM32F072,
classic CAN only) cannot see it at all, and a silent result there is **ambiguous
rather than negative**. See [06 §6](../docs/06-adas-openpilot.md).

### `live_log_hda.py`

HDA engagement research log. Polls camera (`0x7C4`) and MDPS (`0x7D4`)
identifiers plus ECM speed during a drive, hunting for an engagement flag.
Read-only, no session control.

The session-1 result was inconclusive: camera identifiers were entirely static,
and the only near-discrete MDPS byte proved to be a rolling alive-counter. Only
the `0x0100`–`0x01FF` range was scanned, so this is "not located", not a hard
negative.

Superseded by `journey_log.py` for general logging. Retained for resuming this
specific search over a wider identifier range.

---

## 7. Archive (`archive/`)

Superseded by the session-2 tools. Retained rather than deleted: each documents
the exact state its findings were produced in.

| Script | Superseded by |
|---|---|
| `obd_isotp.py` — VIN, ECU name, DTCs on `0x7E0` + `0x7E1` | `vehicle_info.py` (VIN, identification) and `read_dtcs.py` (DTCs, all 15 modules) |
| `live_log.py` — 4-PID drive log to CSV | `journey_log.py` (26 PIDs, JSONL + CSV + summary, clean Ctrl-C) |

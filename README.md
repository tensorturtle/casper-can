# CAN Bus Analysis of Hyundai Casper (AX)

CAN bus analysis of my Hyundai Casper, towards comma.ai compatibility.

Car: Hyundai Casper 1.0 Turbo "The Essential" Trim.
+ Manufactured 2024-03
+ Includes HDA (Highway Driving Assist) I - which does both smart cruise control and lane keep assist, but disengages when below 10km/h.

# Initial Setup Procedure

+ Identify CAN bus wires from pigtail
+ Connect to CAN-to-USB adapter and extract data
+ (Advanced) Send CAN bus messages to control various aspects.

# Confirmed OBD-II Pigtail Wire Mapping

Measured with a multimeter directly on the pigtail (see `references/OBD-II-pigtail-wire.jpg` for the generic color/pin chart used as a starting point).

| Function | Wire Color | Notes |
|---|---|---|
| CAN-H | Green | Idles ~2.5V vs GND (ignition on). ~60Ω resistance to Brown/White with adapter disconnected and ignition off, confirming a terminated CAN pair. |
| CAN-L | Brown/White | Idles ~2.5V vs GND (ignition on). |
| GND | Orange or Yellow | Both confirmed 0V, usable as ground reference. |
| Power (constant battery+) | Green/White | ~12V with ignition off, ~14V with ignition on. Always hot - matches standard OBD-II pin 16. Use this to power the CAN-to-USB adapter. |
| Power (switched/ignition) | Red | 0V with ignition off, ~14V with ignition on. Not used for adapter power. |

All other pigtail wires are unconfirmed/unused for now and should be taped off individually to avoid shorts against the CAN-H/CAN-L/GND/power lines in use.

## Current Wiring State

Taped off all wires except:
+ CAN-H (Green)
+ CAN-L (Brown/White)
+ GND (Orange - both Orange and Yellow confirmed to work equally well)

Adapter is powered via USB from the host device, not from the pigtail's Green/White battery+ line.

## Adapter Info (Jhoinrch RH-02)

See `references/USB-to-CANBUS-adapter-user-manual.jpg`.

+ Derived from the open-source [Canable](http://www.canable.io/) project ([GitHub](https://github.com/HubertD/cangaroo))
+ Ships with **candleLight** firmware by default (gs_usb-compatible), boot switch OFF = normal work mode
+ Chip: STM32F072C8T6
+ Interface: USB Type-A + 3-pin terminal block (CAN_H, CAN_L, GND) - matches our wiring, no separate power pin needed
+ Supports CAN 2.0 A/B, up to 1Mbps
+ Compatible with Windows/Linux/Mac Intel - manual claims **not compatible with Mac Apple Silicon (M-series)**, but this only applies to the vendor's bundled GUI tool. The underlying candleLight/gs_usb protocol works fine on Apple Silicon macOS via `libusb` + `python-can`/`gs_usb` (userspace, no kernel driver needed) - confirmed working on this machine (see Software Setup below).

## Software Setup (macOS, incl. Apple Silicon)

Using [`uv`](https://github.com/astral-sh/uv) with inline script dependencies (PEP 723) - no manual venv needed, just `uv run <script>.py`.

Dependencies: `python-can`, `gs_usb`, `pyusb` (needs `libusb` installed, e.g. `brew install libusb`); `plot_journey.py` additionally uses `matplotlib`.

**Python 3.14+** - all scripts declare `requires-python = ">=3.14"`. Worth knowing why: the floor was originally `>=3.9`, and since uv satisfies a floor with the *oldest* qualifying interpreter available, everything was quietly running on macOS's system Python 3.9.6 even with 3.14 installed via Homebrew. A version floor is not a version choice.

**Known macOS quirk**: `gs_usb`'s `start()` unconditionally calls `detach_kernel_driver()` on non-Windows platforms. On macOS, libusb only allows this as root, causing an `Access denied` error under a normal user. Workaround (no `sudo` needed): monkey-patch `usb.core.Device.is_kernel_driver_active` to always return `False` before opening the device - see `scripts/can_sniff.py`. There's nothing to actually detach here since this is a vendor-specific USB interface, not a claimed serial/HID device.

Main capture script: `scripts/can_sniff.py` - sweeps common bitrates (500k/125k/100k/250k/1M/50k/20k) for a fixed total duration, auto-reconnects if the USB device drops (e.g. from road vibration), and logs any received frames to `can_capture_log.csv`.

## Scripts

**See [`scripts/README.md`](scripts/README.md) for the full guide** - what each script is for, when to reach for it, and the gotchas.

Everything is `uv run scripts/<name>.py`. Only five are needed for everyday use:

| I want to... | Run |
|---|---|
| Watch live data while driving | `dash.py` |
| Record a drive for later analysis | `journey_log.py`, then `plot_journey.py` |
| Check for fault codes | `read_dtcs.py` |
| Read odometer / maintenance / build info | `vehicle_info.py` |

The rest are reverse-engineering instruments (`full_uds_scan.py`, `uds_cli.py`, `snapshot_did.py`, `diff_did.py`), situational tools for milestones not yet reached (`can_sniff.py` for a future physical tap point, `live_log_hda.py` for the HDA hunt), or `archive/` - day-1 scripts superseded by the above, kept because they document the state their findings were produced in.

Two operational notes: only **one** script can use the USB adapter at a time (a second sees a silent bus and reports "no PIDs supported", which looks exactly like the ignition being off), and every script is **read-only except `full_uds_scan.py`**, which is the only one that sends Diagnostic Session Control - see the Safety Note.

## Diagnostic Log

Initial passive sniffing across all bitrates, both CAN-H/CAN-L orientations, both GND options (Orange/Yellow), normal and listen-only modes, with real bus traffic confirmed present (driving, braking, lock/unlock) - **consistently returned 0 frames**. This looked like a dead adapter receiver, but wasn't:

+ Internal firmware loopback test (`GS_CAN_MODE_LOOP_BACK`) - 10/10 frames echoed correctly, proving the USB/firmware/controller pipeline is fully healthy on macOS.
+ Sending an **active** standard OBD-II request (Mode 01 PID 00, arbitration ID `0x7DF`) immediately got responses from ECUs at `0x7E8` and `0x7E9`.

**Conclusion**: this car's central gateway does not passively broadcast internal bus traffic to the OBD-II port (a security/privacy feature common on Hyundai/Kia vehicles since ~2018). It only responds to actively addressed requests. The wiring, adapter, and pin identification were correct the entire time - the bus just needed to be asked, not just listened to.

**Implication for HDA/ADAS data**: the gateway-reachable bus (what's on pins 6/14) is useful for standard OBD-II PIDs/DTCs via active polling, but LKAS/SCC/steering-torque/camera messages needed for openpilot-style work typically live on a separate internal bus that many Hyundai/Kia gateways don't relay to the OBD port at all.

## ECU Enumeration & VIN (via `scripts/archive/obd_isotp.py`)

Active OBD-II/UDS querying over the gateway-reachable bus, with proper ISO-TP (ISO 15765-2) multi-frame reassembly (send Flow Control after a First Frame to get the rest of a multi-frame response - needed for VIN/ECU-name, which don't fit in one CAN frame).

Two ECUs respond on this bus:

| ECU | Request ID | Response ID | Name (Mode 09 PID 0A) | Notes |
|---|---|---|---|---|
| Engine Control Module | `0x7E0` | `0x7E8` | `ECM-EngineControl` | Reports 0 stored DTCs |
| Transmission Control Module | `0x7E1` | `0x7E9` | `TCM-TransmisCtrl` | VIN request (Mode09 PID02) correctly returns negative response (VIN only lives on ECM) |

**VIN (from ECM)**: `KMHB3516BRW117199` (`KMH` = Hyundai Motor Manufacturing WMI, confirms genuine data from this car).

Only `0x7E0`/`0x7E1` (of the full `0x7E0`-`0x7E7` physical addressing range) got responses - no other ECUs are reachable on this gateway-relayed bus.

**Gotcha hit while building this**: OBD-II/UDS request frames must be padded to **DLC=8** (ISO 15765-4 padding, typically with `0xAA`) even when the actual payload is shorter - a request sent with `DLC=3` (just the payload length) was silently ignored by the ECUs, which looked identical to "the gateway is asleep" until caught by comparing against a working request.

## Full UDS Module Scan (via `scripts/full_uds_scan.py`)

Scanned the full `0x700`-`0x7FF` physical addressing range with UDS Tester Present (`0x3E 0x00`), since Hyundai/Kia chassis/body ECUs commonly live outside the standard OBD `0x7E0`-`0x7E7` range. Response ID = request ID + `0x8` in every case found. **14 ECUs responded** - far more than the OBD-standard scan found. For each, queried: Extended Diagnostic Session (`0x10 0x03`), DTCs (UDS `0x19 0x02 0xFF` - report all DTCs by status mask), and identification DIDs (`0xF190` VIN, `0xF1A0` SW version, `0xF187` part number, `0xF18C` serial number).

| Req ID | Resp ID | Part Number | Likely Module (by Hyundai/Kia part-number prefix convention) | DTC status |
|---|---|---|---|---|
| `0x770` | `0x778` | `91950-O6191` | Wiring/junction-related | see raw log |
| `0x780` | `0x788` | `0037` (truncated) | Unclear | negative response to DTC read |
| `0x796` | `0x79E` | `99240-O6500` | Parking sensors / around-view (SPAS) | negative response to DTC read |
| `0x7A0` | `0x7A8` | `95400-O6110` | Transmission-adjacent control unit | see raw log |
| `0x7B3` | `0x7BB` | `97250-O6210` | HVAC / climate control | see raw log |
| `0x7B7` | `0x7BF` | `99140-O6000` | Rear radar / blind-spot detection (BSD) | see raw log |
| `0x7C4` | `0x7CC` | `99211-O6000` | **Front-facing camera (LKAS/lane camera)** - serial `240301...` matches car's 2024-03 build date | see raw log |
| `0x7C6` | `0x7CE` | `94013-O6000` | Cluster / instrument panel (CLU) - also stores full VIN | see raw log |
| `0x7D0` | `0x7D8` | `99110-O6000` | Serial contains literal `"CCM"` - likely Body/Convenience Control Module | see raw log |
| `0x7D1` | `0x7D9` | `58900-O6810` | **ABS/ESC hydraulic control unit** | see raw log |
| `0x7D2` | `0x7DA` | `95910-O6000` | Unclear (long/complex identification payload - possibly SRS/airbag or yaw sensor) | see raw log |
| `0x7D4` | `0x7DC` | `56340-O6000` | **MDPS (Motor Driven Power Steering)** | see raw log |
| `0x7E0` | `0x7E8` | `39103-04150` | ECM (confirmed via Mode 09 name earlier) | 0 DTCs |
| `0x7E1` | `0x7E9` | (n/a) | TCM (confirmed via Mode 09 name earlier) | see raw log |
| `0x7F1` | `0x7F9` | - | Acked Tester Present only, no session/DTC response | - |

Full raw request/response data (including DTC byte arrays) captured during this scan - re-run `scripts/full_uds_scan.py` to reproduce; module identities above are inferred from part-number prefixes (a well-known but informal Hyundai/Kia convention, e.g. `56xxx`=steering, `58xxx`=brakes/ABS, `99xxx`=ADAS sensors) and are not from an official source - treat as a strong lead, not certainty.

**This is significant for the comma.ai goal**: the front camera, MDPS, and ABS/ESC modules - the three most safety/control-relevant ECUs for openpilot lateral+longitudinal control - are all identifiable via the OBD-II gateway, without needing to physically open the camera housing just for identification. Their exact part numbers are now known and can be looked up for wiring diagrams/pinouts.

**Important caveat**: this only proves these modules are reachable for *diagnostic request/response* through the gateway. The continuous, periodic broadcast messages that openpilot actually needs (steering torque, LKAS command, SCC status, updated ~50-100Hz) are a different thing entirely - our 45s passive listen test showed **zero broadcast traffic** on this gateway-relayed bus. Getting those live streaming messages still likely requires a physical tap closer to the source (e.g. splicing into the camera module's or MDPS's own CAN harness), not just querying through the OBD port.

## ⚠️ Safety Note

Sending Diagnostic Session Control (`0x10 0x03`, extended session) to safety-critical chassis modules briefly triggered a **"Check ESC" warning light** (self-cleared after ~2s) during the full UDS scan above, most likely from the ABS/ESC module (`0x7D1`) reacting to being pulled out of its default session. This is very likely benign/expected ECU behavior (many ECUs flash a warning while an external tool holds a non-default session, then auto-revert), but:

+ **Never send Diagnostic Session Control or DTC-clearing commands to ABS/ESC (`0x7D1`) or MDPS (`0x7D4`) while the vehicle is in motion.** Parked, in P, with parking brake + foot brake applied (as done here) is the only condition this should be attempted under.
+ If any warning light persists (doesn't clear within a few seconds) after a probing session, stop, turn ignition off/on to reset ECU states, and confirm the light is gone before driving.
+ Confirmed again during the parking-brake investigation below: repeated extended-session probing of `0x7D1` reliably produced brake/ABS/traction-control warning lights for ~4 seconds each time, always self-clearing. Consistently benign parked with brakes applied and repeated many times, but **still never to be attempted while driving.**

## Live Drive Test (via `scripts/archive/live_log.py`)

2-minute live drive: continuously polled ECM Mode 01 PIDs (RPM/Speed/Throttle/Coolant) while also passively logging any other frame on the bus. During the drive: locked/unlocked doors, opened windows, hazard lights, reverse gear, parking-sensor proximity alarm, side mirror adjustment, HDA engaged briefly, AC on/off.

+ **Active polling worked perfectly**: Speed up to 22 km/h, RPM up to 1915 (throttle spiking to 57.6% on acceleration), coolant steady ~90-92°C - clean, sensible, correlated telemetry.
+ **Zero passive broadcast frames** - out of 528 logged rows, all 528 were our own active PID responses; not a single unsolicited frame appeared, despite exercising doors/windows/mirrors/AC/reverse/parking-sensors/HDA.

**Conclusion (now confirmed twice, stationary and driving with many subsystems active)**: this gateway bus, reachable via the OBD-II port, is **strictly request/response** - it never broadcasts internal traffic under any circumstance tested. There is no amount of driving or triggering subsystems that will produce passive traffic here. The periodic LKAS/SCC/MDPS messages needed for openpilot-style work are simply not obtainable from this bus at all, active or passive - a physical tap point elsewhere in the vehicle (camera module, MDPS harness, etc.) is required, not more OBD-port work.

## Live State Discovery via DID Diffing (`scripts/snapshot_did.py` + `scripts/diff_did.py`)

Methodology: scan a range of `0x22` (ReadDataByIdentifier) requests on an ECU, save as a named JSON snapshot, physically change one thing in the car, scan again, diff the two snapshots. Any DID whose response bytes changed is a candidate for encoding that state.

**Important lesson learned**: always take a **control snapshot** (re-scan with nothing physically changed) before trusting a diff - some DIDs are live counters/timestamps that drift on their own regardless of any real state change, and will show up as false positives otherwise. Caught exactly this on `0x7D2` DID `0x01D0`/`0x01FA` while investigating windows (see below) - values drifted between two scans with the window untouched, revealing it as noise, not a real signal.

### Door Lock State - FOUND

**DID `0x0171` on BCM (`0x7D0`)**: single bit (bit 0) flips with lock state.
+ Locked: byte value `134` (`0b10000110`)
+ Unlocked: byte value `135` (`0b10000111`)

Found cleanly via one diff, no false positives - locked/unlocked toggle changed exactly this one byte in exactly this one DID across a 256-DID scan range (`0x0100`-`0x01FF`).

### AC Compressor State - FOUND

**DID `0x01A2` on HVAC module (`0x7B3`)**: byte offset 32 and bytes 37-39 (indices into the full ISO-TP-reassembled response array, i.e. including the `0x62 0x01 0xA2` header) track AC on/off.
+ AC on: byte[32]=`51`, bytes[37:40]=`[1, 1, 1]`
+ AC off: byte[32]=`3`, bytes[37:40]=`[0, 0, 0]`

Validated with a full on -> off -> on round trip (all bytes flipped back to original "on" values). Other bytes in this DID, and all of DIDs `0x01A0`/`0x01A1`/`0x01A3`, are live sensor telemetry (duct/evaporator temps, etc.) that drift continuously regardless of AC state - do not treat those as flags without a control-tested diff. One candidate (`0x01A0` byte 31) looked promising initially but failed the round-trip validation (didn't flip back to its original "on" value) and was downgraded to unconfirmed.

**Methodology refinement that found this**: a simple two-snapshot diff wasn't enough here (too much continuously-drifting sensor noise). Used a **masked diff**: take two control snapshots with nothing changed to build a per-byte "noise mask" (bytes that drift on their own), then only trust a byte that differs between the real before/after states AND is stable (non-noisy) across the control pair. This cut through the noise cleanly.

### Recirculation - LIKELY FOUND, not fully round-trip validated

**`0x01A1` bytes 3, 5, 7, 9, 11, 13, and `0x01A2` byte 3** all flipped `0` (outside air) -> `255` (recirculation) simultaneously, stable against a control snapshot - six+ positions moving together in a clean binary (0x00/0xFF) pattern strongly suggests a genuine flag (possibly replicated per zone/duct).

Round-trip back to outside air did **not** cleanly confirm this (bytes stayed at 255) - but the likely explanation is a confound, not a wrong signal: the climate system's overall on/off state changed between the two test legs (see the `0x0100` DID appearing/disappearing), so it wasn't a clean single-variable toggle. Investigation was paused here (HVAC exploration wrapped up) before a fully clean re-test could be done. Treat as a strong candidate, not fully confirmed.

### Not Investigated (deferred, HVAC exploration wrapped up here)

Front/rear demist, air cleaning/ionizer mode, seat heating/cooling - not yet tested. Same masked-diff methodology should work; revisit if useful later.
### Climate System Fully OFF - FOUND (via DID *availability*, not a byte value), with a caveat

**DID `0x0100` on HVAC module (`0x7B3`) only responds at all when the climate panel's OFF button is pressed** (fan/AC/vents all off, only passive outside air flowing) - confirmed absent (no response) across 7 separate snapshots taken in various AC-on/AUTO states, and consistently present across 2 snapshots with climate OFF. A different kind of signal than the others found so far: the signal is whether the DID exists/responds at all, not a specific byte's value within it.

**Caveat**: later, during the recirculation investigation, `0x0100` appeared once in a control snapshot while the system was believed to still be in an "on" state (outside air, AC on) - i.e. not perfectly clean/reproducible. Treat this signal as a strong indicator, not an absolute one, until re-verified.

### Target Temperature - PARTIALLY FOUND (not linear)

**DID `0x01A0` bytes 54 and 56 on HVAC module (`0x7B3`)** correlate with the target temperature setpoint, confirmed stable against a control snapshot. However, the mapping is **not a simple linear formula**:
+ 18.0°C -> raw `0`
+ 22.0°C -> raw `1`
+ 24.0°C -> raw `2`

A naive linear fit from the first two data points (`temp_C = raw*2 + 20`) broke when a third point was tested - 18 to 22°C (+4°C) only moved the raw value by 1, while 22 to 24°C (+2°C) also moved it by 1. This is consistent with a known real-world quirk in Hyundai/Kia HVAC systems: the displayed temperature doesn't map linearly to the internal raw value across the full range, especially near the low/high extremes (coarser steps or "LO"/"HI" super-cool/heat modes). Building a full lookup table would need testing every 0.5-1°C step across the whole range - not done yet, deferred.

### AUTO Mode Intensity Levels (1/2/3) - INCONCLUSIVE, not yet cleanly isolated

Attempted to diff between the 3 AUTO fan-intensity presets (cycled via repeated AUTO button presses). Found a candidate (`0x01A2` byte 29: `0` baseline -> `32` in AUTO, looked like a clean single-bit flag) but this test's baseline was potentially confounded by washer fluid/wiper activity run immediately before, and round-trip re-validation wasn't completed before moving to the cleaner OFF-state test above. Revisit with a clean control methodology (control-snapshot masking, like the AC compressor and OFF-state findings above) if needed.

### Parking Brake Status - NOT FOUND (false lead, ruled out)

Extensive search, ultimately inconclusive:
+ BCM (`0x7D0`) narrow + wide ranges, Cluster (`0x7C6`) `0x0000`-`0x03FF`/`0xB000`-`0xB0FF`/`0xC000`-`0xC0FF`: zero DIDs changed with parking brake applied vs released.
+ ABS/ESC (`0x7D1`) returned **zero DIDs in default session** across every range tried - but checking the actual negative response code showed NRC `0x31` (`requestOutOfRange`, i.e. "DID doesn't exist"), not `0x33` (`securityAccessDenied`) - so this module is not actually security-locked for reads, we just hadn't hit valid DIDs yet.
+ With Extended Diagnostic Session active (see Safety Note above), `0x7D1` DID `0xC101` (42-byte multi-frame response) showed a promising clean single-byte change (byte offset 8: `56` released -> `80` applied, stable against a control test) - but **failed round-trip validation** (didn't return to `56` when re-released, instead read `100`). Downgraded to false lead, same failure pattern as the earlier `0x01A0` AC candidate - some live/counter-like byte that happened to correlate with test timing rather than a stable state flag.

Not pursued further given the repeated ABS/ESC warning-light exposure for a negative result - see Safety Note.

### Window Position - NOT FOUND YET

Tried, all inconclusive/negative:
+ BCM (`0x7D0`), full `0x0000`-`0x03FF` range: 9 positive DIDs total (the door-lock-related ones), zero changed when driver window opened vs closed.
+ `0x770` (unidentified ECU, part `91950-O6191`), `0x0100`-`0x01FF`: 78 positive DIDs, zero changed.
+ `0x7D2` (unidentified ECU, part `95910-O6000`), `0x0100`-`0x01FF`: 2 DIDs appeared to change, but a control snapshot (no physical change) showed the same drift - false positive, these are live counters.
+ Not yet tried: `0x796`, `0x7B7`, `0x7C6`, `0x7B3`, `0x7C4`, wider ranges on `0x780`/`0x7A0`/`0x7F1` (all returned 0 positive DIDs in `0x0100`-`0x01FF`).

### Drive Mode (Normal/Sport) - NOT FOUND (false lead, ruled out)

No Eco mode on this car - only Normal and Sport (traction modes Snow/Mud/Sand are a separate control, not tested).

Found `0x7E1` (TCM) DID `0x01A0` byte 10 and DID `0x01F2` byte 10, both `10` (Normal) -> `9` (Sport), stable against a control snapshot - looked clean. **Failed round-trip validation**: switching back to Normal read `9` again instead of reverting to `10`. `0x7D2` showed zero signal at all for drive mode.

### Methodological Caveat: short control tests don't catch slow-drifting values

Three separate "clean, control-stable" candidates have now failed round-trip validation: the AC `0x01A0` byte 31 lead, the parking brake `0xC101` byte 8 lead, and this drive mode lead. All three passed a short (~seconds) control test but failed when re-checked minutes later. Likely explanation: some of these bytes are **slow-drifting counters or timestamps** that only change over longer timescales (minutes), which a quick back-to-back control snapshot won't catch. **Takeaway for future investigation**: a single short control test is not sufficient proof - always do a full round-trip (back to the original state) before trusting a "clean" diff, and consider spacing control snapshots further apart in time to catch slower drift.

### Media/Volume - NOT REACHABLE (confirmed negative)

Tested with CarPlay connected and audio playing, volume 20 -> 25. Zero signal across every plausible candidate: `0x780`, `0x796` (both narrow `0x0100`-`0x01FF` and wide `0x0000`-`0x03FF` ranges), `0x7B7`, `0x7C6`, `0x7F1`. None of the 14 known ECUs on this gateway-reachable bus correspond to media/volume.

**Likely explanation**: the infotainment head unit (especially relevant here since CarPlay was driving audio via USB, not the factory radio circuitry) is almost certainly on a separate bus entirely - many modern AVN (audio-video-navigation) systems sit on Ethernet, MOST, or a dedicated LIN/CAN segment not bridged to the OBD-II diagnostic gateway. This is a hard negative, not a "not found yet" - would need a physical tap at the head unit itself to investigate further, out of scope for this session.

### HDA Engagement Status via Active Polling - INCONCLUSIVE

After establishing that this bus never passively broadcasts (confirmed again during a real drive with HDA engaged three times, ~3s each around 27-28 km/h, plus lane centering enabled twice - zero non-PID frames across the full 180s log, see `hda_drive_log.csv`), tried a different approach: **active polling** (`scripts/live_log_hda.py`) of the front camera (`0x7C4`) and MDPS (`0x7D4`) via `0x22` reads throughout the drive, to see if HDA engagement is readable as discrete state (like AC/door lock were) rather than needing continuous broadcast.

Result: inconclusive, not confirmed.
+ Camera (`0x7C4`) DIDs `0x0101`/`0x0102`/`0x0103`/`0x0140` were **completely static for the entire 180s drive**, including during all three HDA windows - never changed once. Likely calibration/config data, not live state.
+ MDPS (`0x7D4`) DID `0x0101` has genuinely live, continuously-changing data (steering angle/torque - real sensor values responding to actual steering), but the only near-discrete byte found (byte 17, values 41-43) is just a rolling message counter/alive-counter, unrelated to HDA timing.

Only a narrow DID range (`0x0100`-`0x01FF`) was scanned on both modules - this is a "haven't found it yet" result, not a hard negative like media/volume. Revisit with a wider DID scan if pursuing this further.

# Day 2 Goals

Set at the start of session 2, in addition to the carried-over Next Steps below.

1. **Diagnostics / error messages** - read and *decode* fault codes the way a commercial OBD-II scanner does: stored/pending/permanent DTCs, translated into standard `P0123`-style codes with their status flags, across all 14 known ECUs (not just the ECM). `scripts/read_dtcs.py`.
2. **Real-time TUI** - a live dashboard readable at a glance while driving (speed, RPM, throttle, temps, fuel, load), rather than a scrolling wall of text. `scripts/dash.py`.
3. **Journey log** - a drive logger that writes a structured, self-describing log file suitable for plotting afterwards (speed/RPM/throttle/etc. traces, trip summary stats). `scripts/journey_log.py`.
4. **"Intelligent"/connected-car maintenance data** - the car's phone app shows odometer, battery status, tyre pressures, service items, and last-parked GPS. Determine how much of that is actually readable from the CAN/OBD side. `scripts/vehicle_info.py`.

Also introduced this session: `scripts/canbus.py`, a shared module for the gs_usb + ISO-TP + PID/DTC-decoding plumbing that had been copy-pasted across all day-1 scripts. New scripts import it; day-1 scripts are left as-is (they document the exact state they were run in).

# Day 2 Results

All of the below was captured parked, engine idling, ignition on.

## Bug worth knowing about: `timeout_ms=0` means "block forever"

The first version of `canbus.Bus.drain()` read frames with `timeout_ms=0`, intending "non-blocking". libusb interprets a 0 timeout as **wait indefinitely** - and because this car's bus never broadcasts (day-1 finding), there is never a frame to return, so the first call hung forever. It looked exactly like a dead adapter. Any read on this bus must use a small but **non-zero** timeout.

## Fault Codes (via `scripts/read_dtcs.py`)

### Emissions layer (ECM, standard OBD-II) - completely clean

+ MIL / check-engine lamp: **off**, 0 confirmed DTCs.
+ Stored (Mode 03), pending (Mode 07) and permanent (Mode 0A): **all empty**.
+ All 8 supported readiness monitors report **complete** (misfire, fuel system, components, catalyst, evap, O2 sensor, O2 heater, EGR). A car with recently-cleared codes or a disconnected battery would show incomplete monitors, so this is a genuinely healthy, fully-driven-in emissions state.

### UDS layer - 4 DTCs, only one of them a real stored fault

This is the layer a generic OBD-II dongle cannot reach, and it is where the interesting result is.

| ECU | Code | Status byte | Flags | Reading |
|---|---|---|---|---|
| `0x7C4` front camera/LKAS | `C1863-87` | `0x08` | `confirmedDTC` | **The one genuine stored fault on the car.** |
| `0x7E0` ECM | `P0638-00` | `0x40` | `testNotCompletedThisOpCycle` | Not a failure - the entry exists but no failure bit is set. |
| `0x7E0` ECM | `P0638-00` | `0x40` | `testNotCompletedThisOpCycle` | Reported **twice**, genuinely - see below. |
| `0x7E0` ECM | `P1690-00` | `0x20` | `testFailedSinceLastClear` | Failed at some point since the last clear; not currently failing, not confirmed. |

Reading the status byte matters more than the code here. Only `C1863-87` has `confirmedDTC` set; the three ECM entries have no `testFailed`/`confirmedDTC` bits, which is why the MIL is off and Mode 03 is empty. A scan tool that printed just the code list would make this car look like it has 4 faults. It has one.

+ `C1863` is a chassis code on the **front camera module** - the module most central to the openpilot goal. Failure-type byte `0x87` corresponds to "Missing Message" in the ISO 14229-1 failure-type table, i.e. the camera is complaining that a CAN message it expects is absent. **Unverified whether this is pre-existing or something our own diagnostic probing provoked** - it needs a re-read on a cold start with no probing beforehand to tell those apart. If it is pre-existing, a camera that expects messages it isn't receiving is a substantive lead.
+ `P0638` is "Throttle Actuator Control Range/Performance (Bank 1)"; `P1690` is manufacturer-specific and not decodable from public tables.

**The duplicate `P0638-00` is real, not a parser bug.** Verified against raw bytes - the ECM's response is `59 02 FF | 06 38 00 40 | 06 38 00 40 | 16 90 00 20`, i.e. it genuinely sends the same DTC record twice.

### ECUs that will not report DTCs in the default session

| ECU | NRC | Meaning |
|---|---|---|
| `0x780`, `0x796` | `0x31` requestOutOfRange | Does not implement `0x19` subfunction `0x02`. |
| `0x7D2` | `0x7F` serviceNotSupportedInActiveSession | Would answer in an **extended** session - deliberately not attempted, per the Safety Note. |
| `0x7F1` | `0x11` serviceNotSupported | No DTC service at all. |

The remaining 11 ECUs - including ABS/ESC and MDPS - answered and reported **no faults**, with no session control needed and therefore no warning lights.

## Live Dashboard (`scripts/dash.py`)

A curses TUI: large block-digit speed, RPM bar, and a scrolling-free table of every other supported value with magnitude bars, dimming any reading that goes stale.

Because nothing broadcasts here, every value is actively polled, which makes refresh rate a budget. Fast-changing values (speed, RPM, throttle, load, pedal) are polled every cycle; the rest round-robin one per cycle. Measured **~20 Hz full-screen refresh at ~100 PID responses/second** on this car - far better than expected for request/response-only polling, and easily enough to read while driving.

## Multi-PID Mode 01 Batching - WORKS (2.3x faster)

SAE J1979 permits several PIDs in one Mode 01 request; a single 8-byte frame fits the PCI byte + `0x01` + **up to 6 PIDs**. Many ECUs ignore everything past the first PID. **This ECM answers all of them.**

```
request : 06 01 0D 0C 11 04 49            speed, RPM, throttle, load, pedal
response: 41 0D 00 0C 0D 3A 11 21 04 4D 49 24
          └ 0x41 then <pid><data...> concatenated, no length markers
```

The response exceeds 7 bytes, so it arrives as a multi-frame ISO-TP transfer and needs the flow-control path (already present). Walking it requires a **per-PID data length table**, since values are packed with no delimiters - that's `canbus.PID_LENGTHS`, and an unknown PID length means you must stop walking rather than guess.

Measured fairly, at the settings `dash.py` actually uses (1 try, short window), 30 iterations:

| | Time per group of 5 | Reliability |
|---|---|---|
| One request per PID | 50.3 ms | 150/150 |
| All 5 in one request | **21.7 ms** | 30/30 |

**2.32x faster.** Note this is the honest figure: an initial test reported "57x" because its baseline used 3 retries and 0.8s windows, which no real caller does. The win comes from eliminating USB round-trips, which dominate the cost (~0.5 ms of that is actual CAN wire time).

In `dash.py` the fast group plus one rotating slow PID now fit in a single 6-PID request per cycle, taking measured refresh from **~16 Hz to ~34 Hz** and the slow-row rotation from 1.3s to 0.6s. A fallback to individual reads remains, so a partial or refused multi-PID response can never blank the dashboard.

## PID Support - 26 decodable Mode 01 PIDs, but no fuel-flow

Probed properly via the Mode 01 support bitmaps (PID `0x00`/`0x20`/`0x40`) rather than guessing. Available: engine load, coolant temp, both fuel trims, intake MAP, RPM, speed, timing advance, intake air temp, throttle position, run time, distance/time with MIL, fuel rail gauge pressure, fuel level, warmups, distance since clear, barometric pressure, control module voltage, absolute load, commanded equivalence ratio, relative/absolute throttle, ambient air temp, both accelerator pedal positions, commanded throttle actuator.

**Notably absent: MAF (`0x10`) and Engine Fuel Rate (`0x5E`).** This is a MAP-based (speed-density) engine with no mass-airflow sensor, so there is **no way to compute fuel consumption or economy from this bus** - `journey_log.py` correctly reports `null` for fuel used rather than a fabricated `0.0`. Trip fuel economy is a Bluelink/cluster figure, not a CAN-derivable one here.

## Journey Logging (`scripts/journey_log.py` + `scripts/plot_journey.py`)

Writes three files per drive: a lossless JSONL event log with a self-describing metadata header, a wide per-second CSV for plotting, and a summary JSON (duration, integrated distance, max/avg speed, max RPM, moving vs idle split, DTCs present at start). Ctrl-C ends a journey cleanly and still writes everything, so it can just be stopped on parking.

`plot_journey.py` renders stacked small multiples - one measure per panel on a shared time axis - deliberately *not* a twin-axis speed-vs-RPM overlay, which would imply correlations the data doesn't contain. Verified end-to-end on a 20-second idle capture (2000 samples).

## Maintenance / Status Values (via `scripts/vehicle_info.py`)

Live at time of capture, idling:

| Value | Reading | Note |
|---|---|---|
| Fuel Level | 90.2 % | |
| Control Module Voltage | 14.11 V | Alternator charging normally - a battery-health proxy, not a true battery SOC |
| Coolant Temp | 90 °C | Fully warm |
| Ambient Air Temp | 36 °C | |
| Intake Air Temp | 62 °C | Heat-soaked from 21 min of stationary idling, not a fault |
| Barometric Pressure | 100 kPa | |
| Run Time Since Start | 1297 s | |
| Distance With MIL On | 0 km | Consistent with the clean emissions result |
| Distance Since Codes Cleared | 8224 km | Against a confirmed 8429 km odometer - codes were cleared at ~205 km, i.e. at pre-delivery |
| Warmups Since Codes Cleared | 255 | Saturated at the 1-byte maximum |

## Build Record - identification DIDs on 14 of 15 ECUs

Reading the standard ISO 14229-1 identification block (`0xF186`-`0xF1A0`) on every ECU produced a full hardware inventory, and **independently confirms the day-1 part numbers via a standard DID rather than the informal prefix inference**:

+ Front camera `0x7C4`: part `99211O6000`, serial `240301M010258` (encodes the 2024-03-01 build, matching the car's build month), HW `1.00`, **SW `1.03`**.
+ MDPS `0x7D4`: part `56340-O6000`, serial `23081505744`.
+ ECM `0x7E0`: part `3910304150`, HW/SW `TAX-2DS00F54JA01`, supplier SW `HEPG9DCD`.

The camera's part number *and software version* are exactly what a comma.ai compatibility discussion needs, and are now known without opening the housing. `0xF18B` (ECU Manufacturing Date) returns packed BCD, not text - it renders as garbage if treated as ASCII.

Only `0x7F1` answered nothing, consistent with day 1 (it acks Tester Present and nothing else).

## Connected-Car / App Data: what is and isn't on the bus

| App feature | On CAN? | Finding |
|---|---|---|
| Odometer | **YES - FOUND** | See below. |
| Battery status | Partially | Control module voltage (14.11 V) is readable and is a charging-health proxy, but there is no true state-of-charge; this car has no intelligent battery sensor on this bus. |
| Distance driven / service intervals | Partially | "Distance since codes cleared" (8224 km) is readable; service-interval countdowns were not located. |
| Trip fuel economy | **No** | No MAF and no fuel-rate PID - not derivable, see above. |
| Per-wheel tyre pressure (TPMS) | **No** | No TPMS module answered anywhere in `0x700`-`0x7FF`. Consistent with indirect (ABS-based) TPMS on this trim, which has no pressure value to read. |
| Last-parked GPS | **No** | Requires the AVN/navigation head unit, already established (day 1) as not bridged to this gateway at all. This is a Bluelink **cloud** feature computed from the phone/telematics unit, not a CAN value - it is not obtainable from the OBD port at any effort. |

### Odometer - FOUND and VERIFIED INCREMENTING

**Cluster (`0x7C6`), DID `0xB002`, 3-byte big-endian at data-byte offset 6, unit = 1 km.** Also mirrored at **DID `0x0080`, offset 10** (same 3-byte layout), found later by a wider scan.

Verified across a real 13 km drive by before/after snapshot diff:

| Source | Before | After | Delta |
|---|---|---|---|
| `0xB002` offset 6 | 8429 | 8443 | **+14** |
| `0x0080` offset 10 | 8429 | 8443 | **+14** |
| ECM "Distance Since Clear" (Mode 01 `0x31`) | 8225 | 8238 | +13 |
| `journey_log.py` integrated from speed | - | - | +12.9 |

Both cluster locations moved identically, corroborated independently by the ECM. The +14/+13/+12.9 spread reconciles exactly: the true starting value was **8429.8**, so `floor(8429.8 + d) = 8443` requires `13.2 <= d < 14.2 km`. The two whole-km counters started at different fractional offsets, hence differing by one, and speed-integration undercounts by ~2-4%.

Read at 8429 km on the dash; `--find-value 8429` returned exactly two hits, both the same location (`offset 6 width 3`, and `offset 7 width 2` - the same value seen without its zero high byte). No other DID anywhere in the scanned ranges encoded that number, so this is unambiguous rather than a coincidence.

Note the offsets are into the **data bytes**, i.e. after stripping the `0x62` + 2-byte DID echo from the ISO-TP response. To read it:

```
request : 0x7C6  ->  03 22 B0 02 (padded to 8 with 0xAA)
odometer_km = payload[6] << 16 | payload[7] << 8 | payload[8]
```

Two independent cross-checks support it:
+ The ECM reports **8224 km** "distance since codes cleared" against an 8429 km odometer - a 205 km difference, i.e. codes were cleared when the car was essentially new (pre-delivery inspection). Internally consistent.
+ 8429 km on a 2024-03 car is ~3,600 km/year - low, but unremarkable for a city car, and the right order of magnitude.

### Fuel Quantity - FOUND (and it corrects an earlier mistake)

**Cluster (`0x7C6`), DID `0xB002`, 2-byte big-endian at data-byte offset 4, unit = litres x 512.**

```
7C6:B002 =  E0 00 00 00 3F AE 00 20 ED 00 00 00
offset:      0  1  2  3  4  5  6  7  8  9 10 11
                         └fuel┘ └─odometer─┘
fuel_litres  = ((payload[4] << 8) | payload[5]) / 512
odometer_km  =  payload[6] << 16 | payload[7] << 8 | payload[8]
```

| | Raw | Litres | Mode 01 Fuel Level |
|---|---|---|---|
| Before drive | 16302 | **31.84 L** | 88.6 % |
| After drive | 15791 | **30.84 L** | 85.9 % |
| Delta | -511 | **-0.998 L** | -2.7 pp |

Four independent checks agree:
+ Implied tank at 88.6% = **35.9 L**, against the Casper's ~36 L spec.
+ Almost exactly **1.000 L** consumed over ~13 km (~13 km/L), against the dash's 12.3 km/L cumulative figure.
+ A later live read showed 30.34 L while the Mode 01 PID read 84.7% -> 30.34/36 = 84.3%. Consistent again at a third point.
+ It explains a drop that was previously unaccountable: `-516` counts while the car sat "parked" was **an hour of idling burning ~1.008 L** - entirely realistic.

**This corrects the earlier write-up.** The 3-byte value at offset 3 reading "16818 km" was recorded as a mystery *distance* field, and "identify the other distance fields" was listed as a next step. It was never a distance - it is this fuel field (byte 3 is simply a zero high byte, so a 3-byte read at offset 3 returns the same number). The error came from going looking for distances and then reading a fuel field as one. **Lesson: a value's plausible magnitude is not evidence of its meaning.**

Caveats to respect when using it:
+ **Fuel sloshes.** Across one drive the percentage swung 88.6 -> 92.2 -> 85.9 with tank attitude. Differencing over a decent distance is sound; short trips are not.
+ The 512 counts/litre scaling is **inferred, not documented**. Falsifiable prediction: a full tank should read **~18,400** (36 x 512 = 18,432). If it doesn't, the scaling is wrong.
+ **A fourth data point disagrees.** A later idle reading showed 30.84 L against a Mode 01 fuel level of 90.2%, implying a **34.2 L** tank rather than ~35.9 L. The two sources also both drifted *upward* while parked (30.34 -> 30.84 L, 84.7 -> 90.2%), consistent with fuel settling after a drive plus different damping between the cluster and the ECM's own reading. So the field is confidently **fuel**, and the ~512 scaling is a good working figure, but treat the constant as carrying a few percent of residual uncertainty until the full-tank check above is done. Do not quote absolute litres to two decimals as if exact.

### Correction: fuel consumption IS partly derivable

An earlier section states consumption is "not derivable from this bus" because there is no MAF and no fuel-rate PID. That holds for **instantaneous flow**, but is wrong as a blanket claim: differencing this fuel-quantity field gives litres consumed, and combined with the odometer delta, real economy. `journey_log.py` now reports `fuel_used_litres` and `economy_km_per_litre` from the cluster instead of a null.

### Fields that stayed silent

Across 13 km and 27 minutes, these cluster DIDs did **not change at all**: `0x0060`, `0x0070`, `0x0072`, `0x0073`, `0xB001`, `0xB003`. Combined with the failed value searches below, trip meters, range-to-empty, average economy and cumulative running time appear to be **computed inside the cluster's firmware and never published to a readable DID**. Nothing found anywhere tracked elapsed time.

Values searched for and **not found**: `389` km range, `13760` min / `229` h cumulative running time, `12.6` km since fill-up, `2.8` and `12.3` km/L, and `84298` (a tenths-resolution odometer - both odometer fields store whole km only, so the dash's `.8` is not exposed).

### Technique note: before/after diff beats value-matching

Three techniques have now been used to find fields, in ascending order of strength:

1. **Snapshot diff on a state change** (day 1) - toggle something physical, diff two DID scans. Found door lock and AC. Needs a control snapshot and round-trip validation or it produces false leads; three day-1 candidates died that way.
2. **Value search** (`--find-value`) - search every payload for a number visible on the dash. Found the odometer instantly. Strong for large, high-resolution values; **actively misleading for small ones**.
3. **Before/after diff across a drive** (`--snapshot` / `--diff`) - the strongest. Asks "what *moved*, and by how much?" rather than "does this number appear?". A field that advances +14 while you drive 14 km is causal, not coincidental, and it finds fields whose current value you don't know and therefore *cannot* search for.

Technique 3 is what confirmed the odometer actually increments, identified the fuel field, and disproved the "mystery distance" reading. **Prefer it whenever the value can be made to change.**

### Cautionary tale: a confidence heuristic that lied

`--find-value` was extended to rate each match's confidence. The first version rated a 0.5 km trip-meter search **HIGH** confidence because "0.5 has a decimal and matched few locations". What it had actually matched was the single byte `5` inside `0xF18C` - an **ECU serial number**. Another rated a 210-minute value against the MDPS's *manufacturing date*.

Two flaws, both now fixed:
+ Static build-record DIDs (`0xF180`-`0xF1FF`) were being searched at all. They hold arbitrary bytes and cannot contain live data, so they are excluded by default (`--include-ident` to override).
+ Magnitude was ignored. Anything under ~100, or matching only 1-byte-wide fields, is now rated LOW regardless of decimals - a single byte holds any value 0-255 and proves nothing.

A relative tolerance also let `8429` silently match a search for `8429.8` while being reported as a clean hit. Hits now carry their delta and an `exact` flag, so a truncating field is visibly distinguishable from an exact one.

**General lesson: with a few hundred bytes of payload, small numbers appear by chance. Only magnitude, resolution, and causal movement are real evidence.**

### Technique note

`vehicle_info.py --find-value N` searches every collected DID payload for a big-endian encoding of `N` as 1/2/3/4 bytes at 1x/10x/0.1x scaling. Pointed at a value read off the dash, it identifies the DID, byte offset, width and scaling in a single pass. Accepts several values at once, optionally labelled: `--find-value odo=8429.8 range=389`. This is a much sharper tool than the day-1 snapshot-diff method for anything with a **known numeric value on display** - no before/after state change needed, no control snapshot, no round-trip validation, and no false-positive drift problem, because a specific multi-byte integer matching exactly is far stronger evidence than a byte that merely changed. Snapshot-diffing remains the right tool for hidden binary states (door lock, AC) that aren't displayed as a number.

## Next Steps

**Opened by day 2:**

+ ~~Verify the odometer increments~~ - **done**, +14 across a 13 km drive at both locations.
+ ~~Identify the other distance fields in `0xB002`~~ - **done**: there were none. The apparent second distance was the fuel field.
+ **Confirm the fuel scaling at a full tank.** Prediction: `0xB002` offset 4 should read ~18,400 (36 L x 512). Cheapest possible check - run `vehicle_info.py` right after a fill-up.
+ **Re-test `journey_log.py`'s exact-distance path on a drive over 1 km.** The path now works end-to-end (odometer and fuel read at both ends of a real trip), but the only drive it has seen was 0.48 km - below the odometer's 1 km resolution, so it reported a distance delta of 0 and could not exercise the fuel differencing. A 5+ km drive would confirm both.
+ ~~Multi-PID Mode 01 batching~~ - **done and confirmed working**, 2.3x, now used by `dash.py`. See the section above.
+ **Determine whether `C1863-87` on the front camera is pre-existing or self-inflicted.** Re-run `scripts/read_dtcs.py` as the *first* action after a cold start with no prior probing in that ignition cycle. If it's still there, a camera reporting "Missing Message" is a real lead about what it expects to see on its own bus; if it appears only after probing, it's our own artifact.
+ **Take a real journey log while driving** and plot it - `journey_log.py` has only been exercised on a 20-second stationary idle so far. Worth doing with HDA engaged to see whether any polled camera/MDPS DID correlates with engagement over a longer window than day 1's 180s.
+ Look for service-interval / maintenance-countdown data on the cluster (`0x7C6`), using `--find-value` against whatever the cluster menu displays (e.g. km to next service).
+ Consider whether `0x7D2`'s DTCs are worth an extended session (it answered `serviceNotSupportedInActiveSession`) - only parked, given the Safety Note, and only once we know what `0x7D2` actually is.

**Carried over from day 1:**

+ Continue window-state search across untried ECUs/ranges above, or accept it may require a DID range not yet scanned - apply the masked-diff (control-pair noise mask) technique from the AC investigation, since a naive two-snapshot diff missed the AC signal too until masking was applied.
+ Wider DID scan on camera (`0x7C4`) and MDPS (`0x7D4`) for an HDA engagement flag, per the inconclusive result above.
+ Try the same masked-diff technique on mirror position and reverse/parking-sensor proximity (see earlier "what's left to test" list).
+ Expand active polling: more Mode 01 PIDs on ECM, and identification DIDs on the ECUs that gave partial/no data above (`0x780`, `0x796`, `0x7F1`).
+ Look up the identified part numbers (`99211-O6000` camera, `56340-O6000` MDPS, `58900-O6810` ABS/ESC) online for wiring diagrams/connector pinouts - this may reveal a more accessible physical tap point than the camera housing itself.
+ **Requires driving** (flagged so we stop here for now): to capture the actual periodic LKAS/SCC/MDPS broadcast messages, need to physically tap the CAN bus at/near the camera or MDPS module while driving with HDA/cruise engaged, since the OBD-gateway bus only carries request/response traffic, not the live broadcast stream - confirmed by the live drive test above.
+ No existing public opendbc/openpilot support or reverse-engineering writeups found for the Casper specifically - check `github.com/commaai/opendbc` and the openpilot Discord `#dev-opendbc-cars` channel; the module identification above (exact part numbers) would be valuable to share there.
+ **Identify the camera connector harness ourselves.** The Casper (and Inster) is not listed in comma's harness guide - [Hyundai/Kia/Genesis harness reference](https://github.com/commaai/openpilot/wiki/Hyundai-Kia-Genesis/) - so no letter is assigned to it. The guide lists ~18 Hyundai variants (A-R, plus J which shares a Toyota housing) with photos and wiring PDFs; identification is visual, by matching the notch pattern on the connector plugged into the lane-keep camera behind the rear-view mirror. Next step is to physically open the camera housing on this car, photograph the connector, and match it against the guide's images (one missing wire is acceptable per the guide).
+ If a camera/MDPS-adjacent tap point is also silent, consider that it may be CAN FD (increasingly common on newer Hyundai/Kia platforms) rather than classic CAN - this adapter's chip (STM32F072) is classic-CAN-only and would need to be swapped for an FD-capable one (e.g. comma panda, CANable 2.0).

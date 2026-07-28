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

Dependencies: `python-can`, `gs_usb`, `pyusb` (needs `libusb` installed, e.g. `brew install libusb`).

**Known macOS quirk**: `gs_usb`'s `start()` unconditionally calls `detach_kernel_driver()` on non-Windows platforms. On macOS, libusb only allows this as root, causing an `Access denied` error under a normal user. Workaround (no `sudo` needed): monkey-patch `usb.core.Device.is_kernel_driver_active` to always return `False` before opening the device - see `scripts/can_sniff.py`. There's nothing to actually detach here since this is a vendor-specific USB interface, not a claimed serial/HID device.

Main capture script: `scripts/can_sniff.py` - sweeps common bitrates (500k/125k/100k/250k/1M/50k/20k) for a fixed total duration, auto-reconnects if the USB device drops (e.g. from road vibration), and logs any received frames to `can_capture_log.csv`.

## Diagnostic Log

Initial passive sniffing across all bitrates, both CAN-H/CAN-L orientations, both GND options (Orange/Yellow), normal and listen-only modes, with real bus traffic confirmed present (driving, braking, lock/unlock) - **consistently returned 0 frames**. This looked like a dead adapter receiver, but wasn't:

+ Internal firmware loopback test (`GS_CAN_MODE_LOOP_BACK`) - 10/10 frames echoed correctly, proving the USB/firmware/controller pipeline is fully healthy on macOS.
+ Sending an **active** standard OBD-II request (Mode 01 PID 00, arbitration ID `0x7DF`) immediately got responses from ECUs at `0x7E8` and `0x7E9`.

**Conclusion**: this car's central gateway does not passively broadcast internal bus traffic to the OBD-II port (a security/privacy feature common on Hyundai/Kia vehicles since ~2018). It only responds to actively addressed requests. The wiring, adapter, and pin identification were correct the entire time - the bus just needed to be asked, not just listened to.

**Implication for HDA/ADAS data**: the gateway-reachable bus (what's on pins 6/14) is useful for standard OBD-II PIDs/DTCs via active polling, but LKAS/SCC/steering-torque/camera messages needed for openpilot-style work typically live on a separate internal bus that many Hyundai/Kia gateways don't relay to the OBD port at all.

## ECU Enumeration & VIN (via `scripts/obd_isotp.py`)

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

## Live Drive Test (via `scripts/live_log.py`)

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

## Next Steps

+ Continue window-state search across untried ECUs/ranges above, or accept it may require a DID range not yet scanned - apply the masked-diff (control-pair noise mask) technique from the AC investigation, since a naive two-snapshot diff missed the AC signal too until masking was applied.
+ Wider DID scan on camera (`0x7C4`) and MDPS (`0x7D4`) for an HDA engagement flag, per the inconclusive result above.
+ Try the same masked-diff technique on mirror position and reverse/parking-sensor proximity (see earlier "what's left to test" list).
+ Expand active polling: more Mode 01 PIDs on ECM, and identification DIDs on the ECUs that gave partial/no data above (`0x780`, `0x796`, `0x7F1`).
+ Look up the identified part numbers (`99211-O6000` camera, `56340-O6000` MDPS, `58900-O6810` ABS/ESC) online for wiring diagrams/connector pinouts - this may reveal a more accessible physical tap point than the camera housing itself.
+ **Requires driving** (flagged so we stop here for now): to capture the actual periodic LKAS/SCC/MDPS broadcast messages, need to physically tap the CAN bus at/near the camera or MDPS module while driving with HDA/cruise engaged, since the OBD-gateway bus only carries request/response traffic, not the live broadcast stream - confirmed by the live drive test above.
+ No existing public opendbc/openpilot support or reverse-engineering writeups found for the Casper specifically - check `github.com/commaai/opendbc` and the openpilot Discord `#dev-opendbc-cars` channel; the module identification above (exact part numbers) would be valuable to share there.
+ If a camera/MDPS-adjacent tap point is also silent, consider that it may be CAN FD (increasingly common on newer Hyundai/Kia platforms) rather than classic CAN - this adapter's chip (STM32F072) is classic-CAN-only and would need to be swapped for an FD-capable one (e.g. comma panda, CANable 2.0).

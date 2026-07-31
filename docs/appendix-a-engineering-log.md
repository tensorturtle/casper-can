# Appendix A — Engineering Log

Chronological record of the investigation, retained for provenance. **Every
conclusion here is stated authoritatively in documents 01–07; this appendix
exists to record the conditions each finding was produced under, not as a
reference.** Read the numbered documents for the current state of knowledge.

---

## Session 1

### Physical layer

Identified CAN-H, CAN-L, ground and both power lines on the vehicle-side pigtail
by multimeter, starting from a generic colour chart
(`references/OBD-II-pigtail-wire.jpg`) and verifying each against the vehicle.
A 60 Ω reading across the pair with the adapter disconnected confirmed a
correctly terminated segment.

### The silence, and its resolution

Passive sniffing across all common bit rates, both wire orientations, both ground
options, and both normal and listen-only controller modes returned **0 frames** —
with real bus activity known to be occurring (driving, braking, central locking).

This presented as a failed adapter receiver. Two tests established otherwise:

- Internal firmware loopback (`GS_CAN_MODE_LOOP_BACK`): 10/10 frames echoed,
  proving the USB, firmware and controller pipeline healthy on macOS.
- An **active** Mode 01 PID 00 request to `0x7DF`: immediate responses from
  `0x7E8` and `0x7E9`.

The wiring, adapter and pin identification had been correct throughout. The
gateway simply does not broadcast — it must be asked.

### ECU enumeration

Active OBD-II/UDS querying with correct ISO-TP multi-frame reassembly found two
modules in the OBD-standard range: ECM (`0x7E0`, `ECM-EngineControl`) and TCM
(`0x7E1`, `TCM-TransmisCtrl`). VIN `KMHB3516BRW117199` from the ECM. The TCM
correctly returns a negative response to a VIN request, which lives only on the
ECM.

**Obstacle encountered:** requests must be padded to DLC=8. A request sent at
`DLC=3` was silently ignored, indistinguishable from a sleeping gateway, until
caught by comparison against a known-working request.

### Full address scan

Scanning the full `0x700`–`0x7FF` range with TesterPresent — on the basis that
Hyundai/Kia chassis and body modules commonly sit outside `0x7E0`–`0x7E7` — found
**15 responding addresses**, including the front camera, MDPS and ABS/ESC.

**Incident:** sending DiagnosticSessionControl (`0x10 0x03`) during this scan
triggered a transient "Check ESC" warning lamp, self-clearing after ~2 s, almost
certainly from the ABS/ESC module reacting to being pulled out of its default
session. This behaviour was reproduced reliably during a later parking-brake
investigation, lasting ~4 s each time and always self-clearing. It is the origin
of the constraints in [00 — Safety](00-safety.md).

### Live drive test

Two-minute drive, continuously polling ECM Mode 01 PIDs while passively logging
any other frame. Doors locked/unlocked, windows, hazards, reverse gear,
parking-sensor alarm, mirror adjustment, HDA engaged briefly, AC cycled.

- Active polling worked cleanly: speed to 22 km/h, RPM to 1915, throttle peaking
  at 57.6 %, coolant steady at 90–92 °C.
- **0 passive frames.** All 528 logged rows were responses to our own requests.

This confirmed the request/response finding a second time, under conditions
designed to provoke broadcast traffic.

### Signal hunting by snapshot diff

Located door lock state (BCM `0x0171`) in a single clean diff. Located the AC
compressor (HVAC `0x01A2`) only after developing the **masked diff** — a plain
diff was defeated by continuously-drifting duct and evaporator telemetry.

Three candidates died on round-trip validation: an AC candidate (`0x01A0`
byte 31), a parking-brake candidate (ABS/ESC `0xC101` byte 8), and a drive-mode
candidate (TCM byte 10). All three had passed a short control test. This produced
the rule that a short control test is not proof — see
[07 §2](07-methodology.md).

Media and volume were established as a **hard negative**, tested with CarPlay
active. Window position and parking brake were left as bounded negatives.

Active polling of camera and MDPS identifiers during a drive with three HDA
engagements was inconclusive: camera identifiers were entirely static, and the
one near-discrete MDPS byte proved to be an alive-counter.

---

## Session 2

### Goals set

1. Decode fault codes as a commercial scan tool does — stored, pending and
   permanent, across all modules, with status flags. → `read_dtcs.py`
2. A real-time dashboard readable at a glance while driving. → `dash.py`
3. A structured, self-describing drive log suitable for later plotting. →
   `journey_log.py`
4. Determine how much of the connected-car app's data is CAN-derivable. →
   `vehicle_info.py`

Also introduced: `canbus.py`, consolidating the gs_usb, ISO-TP and decode-table
plumbing that had been copy-pasted across every session-1 script.

### Obstacle: `timeout_ms=0` means block forever

The first version of `canbus.Bus.drain()` read frames with `timeout_ms=0`,
intending non-blocking. `libusb` interprets a zero timeout as **wait
indefinitely** — and because this vehicle never broadcasts, there is never a frame
to return. The first call hung permanently, presenting exactly as a dead adapter.

### Results

- **Diagnostics:** emissions layer completely clean with all 8 readiness monitors
  complete; UDS layer holds 4 records but only one confirmed fault
  (`C1863-87`, front camera, "Missing Message"). Whether that record is
  pre-existing or provoked by our own probing remains unresolved.
- **Multi-PID batching:** confirmed working, **2.32×**. An initial measurement
  claimed 57× against an unrealistic baseline; see [07 Rule 10](07-methodology.md).
- **Odometer:** located by value search, then **verified incrementing** across a
  13 km drive at two independent cluster locations, corroborated by the ECM.
- **Fuel quantity:** located by before/after drive diff. This **corrected an
  earlier error** — a 3-byte value at offset 3 had been recorded as a mystery
  *distance* field, and "identify the other distance fields" carried as an open
  task. It was never a distance. See [07 Rule 8](07-methodology.md).
- **Correction to a blanket claim:** an earlier write-up stated fuel consumption
  is "not derivable from this bus" on the grounds of no MAF and no fuel-rate PID.
  That holds for *instantaneous flow* but was wrong as a general statement —
  differencing the cluster fuel field against the odometer delta yields real
  economy. `journey_log.py` now reports both.
- **Build record:** identification identifiers read on 14 of 15 modules,
  independently confirming the session-1 part numbers via a standard DID rather
  than informal prefix inference.
- **Confidence-heuristic failure:** `--find-value`'s first confidence rating
  scored a trip-meter search HIGH against a byte inside an ECU serial number.
  Corrected per [07 Rules 6–7](07-methodology.md).

---

## Session 3

### Goal set

A single question: does `dash.py` show everything that can be seen live? An
audit against [04](04-signal-reference.md) said no — the confirmed body signals
were absent, MIL was polled only at startup, and MDPS DID `0x0101` was known to
carry live steering data that had never been decoded. Steering was taken first.

### Conditions

Stationary on **gravel**, engine running, handbrake on. The surface matters: it
took very little force to turn the wheel, so the push-without-turning test of
[07 Rule 5a](07-methodology.md) was performed at low torque. It still gave an
unambiguous separation, but the torque magnitudes recorded (±700 for a
deliberate push) are lower than a tarmac test would produce and should not be
read as any kind of full-scale figure.

### How the fields fell out

Four captures of a few seconds each, against 180 s of inconclusive moving log
in session 1: centre held, full left held, full right held, then push-without-
turning. Right lock flipped bytes 4–5 symmetrically (`+451.5°` / `−457.8°`,
2.5 turns lock-to-lock), which fixed the 0.1 °/count scaling against the car's
published steering spec.

### Two near-misses

After the lock captures, bytes 2–3 looked like a **redundant inverted angle
channel** — they tracked angle in all three positions. Structurally they had
to: holding against a lock loads angle and torque together, so no angle test
could separate them. Only the push at constant position did.
Recorded as [07 Rule 5a](07-methodology.md).

Second, the centre baseline first read **−11.0°**, which looked like a sensor
offset worth compensating. Properly re-centring the wheel gave −1.5°. The
offset was in the wheels, not the data; no correction was applied.

### Results

- **Steering angle — Confirmed.** Offset 4, signed BE, 0.1 °/count, positive
  left. Symmetric about zero, correct lock angle, steady while held, monotonic
  across a continuous sweep. Four independent checks; see
  [04 §7.1](04-signal-reference.md).
- **Steering torque — Working.** Offset 2, signed BE, positive right. Zero at
  rest, swings cleanly either way under load. Rated Working rather than
  Confirmed solely because **no Nm calibration exists** — the counts are raw.
- **Sign conventions disagree** between the two fields (angle positive-left,
  torque positive-right). Measured twice in each direction. Not a transcription
  error, and noted everywhere the fields are described.
- **Reclassification:** MDPS steering moved from *Not located* to Confirmed /
  Working. The session-1 alive-counter finding at offset 14 stands and was not
  contradicted — it was simply the only thing a moving log could isolate.

---

## Open items

Consolidated and prioritised in the numbered documents:

| Item | Where tracked |
|---|---|
| Camera connector identification; physical ADAS tap; CAN FD exclusion | [06 §6](06-adas-openpilot.md) |
| Resolve whether `C1863-87` is pre-existing | [05 §4.1](05-diagnostics.md), [06 §6](06-adas-openpilot.md) |
| Confirm fuel scaling at a full tank (predicts ~18,400) | [04 §4.2](04-signal-reference.md) |
| Window position, HDA flag, mirror, seat heating, service intervals | [04 §8](04-signal-reference.md) |
| Whether `0x7D2`'s DTCs justify an extended session | [05 §5](05-diagnostics.md) |
| Publish part numbers to opendbc / openpilot Discord | [06 §5](06-adas-openpilot.md) |

One further item, not yet tracked elsewhere: **re-test `journey_log.py`'s
exact-distance path on a drive over 1 km.** The path works end-to-end, but the
only drive it has seen was 0.48 km — below the odometer's 1 km resolution — so it
reported a distance delta of 0 and could not exercise fuel differencing. A 5 km
drive would confirm both.

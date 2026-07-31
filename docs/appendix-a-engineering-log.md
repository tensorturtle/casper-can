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
  Confirmed solely because **no Nm calibration exists**.
- **Torque full scale — Confirmed at ±10000**, found only because the dashboard
  was driven harder than the decode session had been: pushing hard at a lock
  pegged it at exactly ±10000 across 186 and 201 consecutive samples. The
  gravel caveat above is why the decode session never saw it — every push had
  been a light one. The clamp is a useful result in its own right, since a
  defined full scale means the field is fixed-point rather than arbitrary
  counts, and it let the dashboard bar be scaled truthfully instead of
  saturating.
- **Sign conventions disagree** between the two fields (angle positive-left,
  torque positive-right). Measured twice in each direction. Not a transcription
  error, and noted everywhere the fields are described.
- **Reclassification:** MDPS steering moved from *Not located* to Confirmed /
  Working. The session-1 alive-counter finding at offset 14 stands and was not
  contradicted — it was simply the only thing a moving log could isolate.

### Body signals: an audit that cost more than it added

With steering done, the remaining `dash.py` gap was the three Confirmed body
signals. Adding them meant re-reading them, and re-reading them with
distribution sampling rather than single reads **retired two of the three**.

- **Door lock (§6.1) — refuted.** `134` locked / `135` unlocked came from one
  sample per state. Across ~730 samples per state, both states span all four
  values `132`–`135`, and `134` is the commonest reading in *both*. The
  original diff was true and meaningless.
- **Climate-off via `0x0100` presence (§6.3) — refuted.** It answered ~450/450
  probes across every climate state. The DID simply always exists.
- **A/C compressor (§6.2) — strengthened.** One value per state, zero jitter,
  round-tripped, and independent of both AUTO and fan speed. The only body
  signal that went on the dashboard.

The near-miss was byte 7 of `0x01A2`, which read `7` at all three AUTO
strengths and `6` at both fan extremes — ~1000 jitter-free samples, and it even
cleared the AUTO-changes-fan-speed confound. It was briefly written up as
Confirmed. Then, with the system off and untouched, it drifted `5` → `4` → `3`
over a few minutes. Stability within a window is not stability; it is now
returned raw and uninterpreted. See [07 Rule 3a](07-methodology.md).

Net effect on the dashboard: **A/C compressor added, MIL now re-polled every
20 s instead of once at startup, and two signals removed from the roadmap
rather than added to the display.** A smaller dashboard than intended, and a
more honest one.

### Conditions and confounds worth knowing

- The A/C-off test was **confounded**: switching the compressor off also
  switched AUTO off on this car. Later captures separated them (byte 32 reads
  `51` with AUTO off, `3` at maximum manual fan), so the conclusion holds — but
  the first test alone did not establish it.
- The climate panel could not be put into "fan on, system otherwise off": on
  this car pressing OFF stops the fan entirely, and pressing fan `+` re-enables
  A/C. Some single-variable climate tests are not physically available.

---

## Session: appliance and app on the road

### Conditions

Radxa Zero 3W on the iPhone hotspot, CAN dongle in the OBD port, engine idling for the
rate measurements and a short drive for the app. Notification and poll rates changed
several times during the session, so figures are only comparable where stated.

### The 1 Hz road test

The first drive streamed at 1 Hz and looked sluggish. The cause was not the bus: the fast
tier was already polling at 10 Hz while the peripheral notified once a second, so nine of
every ten samples were discarded. Two independent numbers had quietly drifted apart, and
nothing in any log looked wrong. The notification rate now derives from the poll rate.

### An optimisation that measurement reversed

Reasoning from ISO-TP framing — a reply of up to 7 bytes fits one frame, beyond that costs
a Flow Control round trip — the two most urgent signals were split into their own
single-frame request. Measured against the previous six-PID batch this proved a poor
trade: 12.5 Hz for six signals beats 16 Hz for two, on the metric that matters
(75 signal-updates/s versus 66). See [04 §2.2](04-signal-reference.md). Boost, which is
computed from MAP, moved from 8.5 Hz to 12.5 Hz as a direct result of the merge.

### Three self-inflicted failures, in order of how long they took to find

**Kernel driver contention.** The kernel's `gs_usb` module claimed the same adapter the
appliance talks to over libusb. Symptom: adapter present, process healthy, every poll
failing. Visible only in `dmesg`, as a reset-and-rebind loop once per recovery attempt.
Blacklisting the module fixed it. This had probably been present all along and was
misattributed to the ignition being off.

**Recovery that was louder than the fault.** An automatic reopen-after-silence fired every
8 s against a parked car, each time issuing a USB reset — roughly seven per minute,
indefinitely. It has been rewritten to test whether the adapter still enumerates before
touching anything, and to back off to five minutes. [07 §4 Rule 14](07-methodology.md).

**Flooding the gateway.** Requesting 40 Hz to "find the ceiling" stopped the car answering
for the rest of the session; it survived a reboot and a power cycle of the board and
cleared only on an ignition cycle. Three configurations were measured and compared before
anyone noticed all three had run against a silent car — hence
[Rule 13](07-methodology.md), that a rate measurement must print its own validity.

### Bluetooth: the board was asking to pair, not the phone

Repeated iOS pairing prompts and ~30 s dropouts looked like the phone demanding security.
`btmon` showed the opposite: bluetoothd acts as a GATT *client* against whatever connects,
read the iPhone's Battery Level, was refused with `Insufficient Authentication`, and sent
an SMP Security Request to bond so it could retry — 56 times in eight minutes. Disabling
pairing alone only refused the consequence; `--noplugin=battery,scanparam,autopair`
removed the cause. Nothing in the service logs showed any of this.

### Results

Boost 8.5 → 12.5 Hz measured, notification rate 1 → 20 Hz, 30 of 31 signals answering
with zero poll errors while idling. Idle SoC temperature 48 → ~45 °C, almost entirely
from removing the desktop rather than from the clock and core limits.

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

### Next experiments, in priority order

Left undone when the session ran out of time. Each states the test, not just
the target.

1. **Calibrate steering torque to Nm.** The only thing keeping
   [04 §7.2](04-signal-reference.md) at Working. Hang a luggage scale on a
   wheel spoke at a measured radius from the centre, pull to a known force,
   read the count. Two points settle the constant and test whether ±10000
   corresponds to ±10 Nm. *Stationary, engine running.*
2. **Re-test `0x01A2` byte 7 over settled periods.**
   [04 §6.6](04-signal-reference.md). Sample for several minutes in each state
   — off, manual, AUTO — well after switching, and watch for drift within each.
   If it holds steady per state over minutes, it is a mode field after all; if
   it keeps wandering, it is analogue and should be dropped.
3. **Byte 25 of `0x01A2` — possible max-fan flag.** Read `4` at maximum manual
   fan and `0` in all six other states, but seen **once**, with no round trip.
   Needs max → low → max with distribution sampling at each step.
4. **Re-test recirculation ([04 §6.4](04-signal-reference.md)) cleanly.** The
   original test was confounded by the system's on/off state changing between
   legs. Now that `0x0100` presence is known to be worthless as a state
   indicator, the confound has to be tracked by byte 32 instead.
5. **Door lock, from scratch.** [04 §6.1](04-signal-reference.md) is refuted,
   so this is an unsolved problem again, not a re-verification. The BCM ranges
   already scanned are listed in [04 §8](04-signal-reference.md); a fresh
   search should use distribution sampling per state from the start.
6. **Log steering angle across a real drive.** Now readable at ~20 Hz. Correlate
   against speed and HDA engagement windows — it is the first ADAS-adjacent
   live signal available without a physical tap
   ([06 §2](06-adas-openpilot.md)).

One further item, not yet tracked elsewhere: **re-test `journey_log.py`'s
exact-distance path on a drive over 1 km.** The path works end-to-end, but the
only drive it has seen was 0.48 km — below the odometer's 1 km resolution — so it
reported a distance delta of 0 and could not exercise fuel differencing. A 5 km
drive would confirm both.

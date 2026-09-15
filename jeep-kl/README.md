# Jeep Cherokee KL — CAN Bus Notes

Passive CAN analysis of a **2015 Jeep Cherokee (KL)**, Mexico-market, personally
imported to Korea. (Model year is from the VIN — see §3.3. It was assumed to be
2016 at the start of this work.)

> Independent reverse-engineering work, not manufacturer documentation. Nothing
> here is endorsed by or sourced from Stellantis / FCA.

This area is **self-contained and separate from the Casper work**. It has its own
`canbus.py` rather than importing `experimentation/canbus.py`, because that
module encodes Casper-specific assumptions — decode tables, a request/response
bus that never broadcasts — that are wrong for an FCA vehicle. Sharing it would
silently import the wrong mental model. The physical adapter and the wire-colour
chart in [`../references/OBD-II-pigtail-wire.jpg`](../references/OBD-II-pigtail-wire.jpg)
are the only things in common.

Confidence ratings follow the scale in
[`../docs/04-signal-reference.md`](../docs/04-signal-reference.md) §1.

---

## 1. Applicability

| Field | Value |
|---|---|
| Model | Jeep Cherokee (KL) |
| Model year | **2015** — VIN position 10 is `F`. §3.3 |
| Market | Mexico (Toluca plant, VIN position 11 `W`), privately imported to Korea |
| Security Gateway (SGW) | **Absent** — FCA introduced it on 2018+ models. The OBD port is unrestricted. *Confidence: Working* |
| Adapter | Jhoinrch RH-02 (CANable / candleLight, `gs_usb`), classic CAN only — see [`../docs/01-physical-interface.md`](../docs/01-physical-interface.md) §4 |

Because there is no SGW, this port will accept writes. That is a reason for
more caution, not less. Everything in this area is read-only by default and
the adapter defaults to listen-only mode.

## 2. Connector wiring

Two CAN buses are reachable from the J1962 connector. Wire colours are a
property of the generic pigtail, not the vehicle, so they match the Casper's.

| Bus | J1962 pins | Wire colours | Bitrate | Status |
|---|---|---|---|---|
| CAN-C (powertrain, chassis) | 6 / 14 | Green = CAN-H, Brown/White = CAN-L | 500 kbit/s | **Confirmed — live broadcast bus, 83 IDs captured. §2.5** |
| CAN-IHS (interior modules) | 3 / 11 | Red = CAN-H, Pink = CAN-L | 125 kbit/s | *Candidate* — from FCA community sources, not yet measured on this car |
| Ground | 4 | Orange | — | Confirmed |
| Battery+, unswitched | 16 | Green/White | — | Confirmed — 14 V measured. Doubles as the check that the connector orientation and colour mapping are right. |

### 2.1 CAN-C measurements

Taken with a multimeter on the pigtail. *Confidence: Confirmed.*

| Measurement | Result | Interpretation |
|---|---|---|
| Pin 6 (green) vs ground, ignition on | **2.8 V** | CAN-H — above the 2.5 V recessive bias |
| Pin 14 (brown/white) vs ground, ignition on | **2.2 V** | CAN-L — below it |
| Differential, ignition on | **0.6 V** | A DMM averaging a busy bus. An idle bus reads ~0 V. Indicates active traffic. |
| Pin 6 ↔ pin 14 resistance, ignition off | **3.6 MΩ** | **Not** the expected 60 Ω — see below |

### 2.2 The absent termination

The Casper reads a clean 60 Ω across CAN-H/CAN-L (two 120 Ω terminators in
parallel). This car reads open-circuit. That is **architectural, not a fault**:
FCA presents CAN-C at the OBD connector as a gateway-buffered stub, with the
terminators out on the backbone where probes at the connector cannot reach them.
A megohm reading here is transceiver leakage with no resistor in the path.

*Confidence: Working* — consistent with the gateway architecture described below, but not
independently confirmed against a wiring diagram.

**Do not chase this as a wiring problem.** Expecting 60 Ω on this vehicle sends
you looking for a fault that does not exist. See §5.

### 2.3 Adapter termination switch position

The adapter's R120 termination switch is in the **`K` position** for this
vehicle. On the Casper it was in the **`E` position**.

Recorded as an observation, not an explanation — the switch was changed while
the adapter was independently faulty (§2.6), so its effect on this vehicle has
never been cleanly measured. Do not assume `K` is required here until it has
been tested against a verified-working adapter.

### 2.4 Pin 3 is not what it is on other cars

On most vehicles — including the Casper — J1962 pin 3 is *switched ignition
power*, ~14 V. On FCA vehicles it is CAN-IHS high. **Measure pin 3 against
ground with the ignition on before connecting anything to it.** ~2.5 V means
CAN-IHS. ~14 V means power, and wiring an adapter's CAN_H to it is the one way
to destroy the adapter here. Not yet measured on this car.

### 2.5 CAN-C broadcasts continuously at the OBD-II port — Confirmed

Pins 6/14 carry a **live broadcast bus at 500 kbit/s**: **83 identifiers** — 82
standard 11-bit plus one 29-bit extended — arriving at 1–100 Hz each, totalling
2,313 frames/s. *Confidence: Confirmed* — captured directly. Full
characterisation in §3.

This **overturns** the "Diagnostic CAN-C, request/response only" theory that an
earlier version of this document recorded as the leading explanation. That theory
was constructed to explain zero received frames. The frames were absent because
every one of those attempts ran the controller in **NORMAL mode**, which receives
nothing on this vehicle. See §2.6 — it is the more important finding of the two.

The FCA architecture research remains accurate as background (the gateway does
isolate CAN-C, CAN-IHS and a diagnostic bus, which is why the 60 Ω termination
check does not apply at this connector). It simply was not the reason for the
silence, and it was reached by reasoning backwards from a broken instrument.

### 2.6 The adapter cannot enter NORMAL mode — a hardware fault, not a vehicle finding

**This is an adapter defect and has nothing to do with this vehicle.** Every
observation below is reproducible on a desk with **no bus attached at all**.
*Confidence: Confirmed.*

| Observation | Evidence |
|---|---|
| Entering `NORMAL` mode hangs the adapter's firmware | Internal loopback returns 5 frames before, **0 after**, with the pigtail unplugged and **no frame ever transmitted** |
| No host-side recovery exists | `dispose_resources()`, an explicit `MODE_RESET` control transfer, `libusb reset()`, `set_configuration()`, and two resets with delays — all no effect |
| Only a physical USB power cycle recovers it | Consistent across the entire session |
| `LISTEN_ONLY` and `LOOP_BACK` work perfectly and indefinitely | 2,300 frames/s sustained, zero errors |

Because merely *starting* in normal mode is enough — no bus, no traffic, no
transmission — every vehicle-side explanation is excluded: ACK failures, the
gateway, termination, the missing 60 Ω, bit timing, ground quality.

**The adapter worked in normal mode before.** `experimentation/canbus.py` calls
`dev.start()` with the same default flags used here, and the Casper's `dash.py`
sustained 29.6 Hz of request/response polling for an entire project on this same
hardware and host. So this is degradation, not a design limitation. The most
plausible cause is the first session on this vehicle, where the adapter sat wired
to a live CAN-C bus with no host process having configured it (§5 rule 1) —
the same event that filled the dash with warnings.

**Consequences**

- Everything requiring transmission is blocked **on this adapter**: polled OBD
  values, DTC reads, DTC clears. Not on this car — on this adapter.
- All passive work is unaffected, which is why 23 signals were still decoded.
- `diagnostics.py` defaults to an **ELM327 transport** (§4.1) precisely to route
  around this.

**Remedies, in order of cost**

1. **An ELM327 dongle.** Cheap, certain, and reads and clears codes today. A phone
   app with one needs nothing from this repository.
2. **Reflash candleLight firmware over DFU.** The manual documents DFU mode: BOOT
   switch **ON**, then the device appears as an STM32 DFU target. If the hang is
   corrupted firmware rather than damaged silicon, a fresh flash restores normal
   mode at no cost. Untested here.
3. **Replace the adapter.** A CANable or comma panda; the latter is needed anyway
   if CAN FD is ever required (see `../docs/01-physical-interface.md` §4.1).

**How this was found, and why it took so long**

The symptom was first recorded as "NORMAL mode receives nothing *on this vehicle*",
and a great deal of effort went into vehicle-side theories — an isolated
Diagnostic CAN-C, gateway buffering, termination, ACK saturation driving the
controller to bus-off. All of it was plausible, some of it well-supported by
research, and none of it was the cause.

The test that settled it in two minutes was **removing the vehicle from the
experiment**. That should have been the first move, not the last: the adapter is
the one component present in every failing observation, and it was also the
component never varied.

### 2.7 Partly retracted: the wedge is real, but the theory of it was wrong

An earlier version of this document described an intermittent adapter fault that
latched bus-off and allowed "exactly one open per USB replug", then a later version
retracted that entirely and declared the adapter healthy. **Both were wrong.**

§2.6 has the truth: the adapter *does* wedge and *does* require a physical replug,
but the trigger is **entering normal mode**, not open/close cycling and not
bus-off from ACK errors. The apparent intermittency came from listen-only and
normal-mode runs alternating, so the wedge looked random when it was perfectly
deterministic.

The reasoning is documented here because how it went wrong is the transferable
part.

**How it happened.** Six bitrate sweeps returned zero frames. From that a theory
was built — FCA's isolated Diagnostic CAN-C carries no broadcast traffic — and it
was supported by genuine research and by a real 3.6 MΩ open-circuit reading. It
was wrong. Every one of those sweeps was a normal-mode run, and normal mode wedges
this adapter. The first listen-only capture produced 2,300 frames/s immediately.

**What made it stick:**

- **An elimination table with a hole in it.** Bitrate, wiring, polarity, boot
  switch, termination were all excluded rigorously. The controller *mode* was
  never a row in the table, because it was never suspected.
- **A tool that lied.** `adapter_check.py` reported a confident PASS while only
  verifying that the device enumerated and accepted configuration. It had never
  moved a frame. It now fails unless loopback returns frames.
- **A coincidence read as a pattern.** Listen-only and normal-mode runs happened
  to alternate, producing an apparent "works once per replug" rhythm. The replugs
  were doing nothing; the mode was doing everything.
- **Reasoning outward from a broken measurement.** Architecture research was used
  to *explain* the silence rather than to predict something testable. It fit
  beautifully and was irrelevant.

**Rules that follow:**

- **Vary the instrument, not just the target.** When every measurement of a
  system agrees and the conclusion is surprising, change something about the
  measuring apparatus — mode, tool, transceiver — before theorising about the
  system.
- **A tool that reports PASS must have exercised the thing it certifies.**
  Enumeration is not operation.
- **A DMM differential reading is not evidence of traffic**, and its absence is
  not evidence of silence. 0.6 V across CAN-H/CAN-L was read first as proof of a
  busy bus, then re-read as an idle gateway bias. It was the former all along; the
  meter never distinguished them. Only a decoded frame did.
- **Do not retract a correct rule to accommodate bad measurements.** "Expect a
  firehose" was written from community reports, then retracted after the silent
  sweeps. It was right the whole time.

## 3. Bus characterisation

From a single 30 s passive capture, ignition on, stationary, engine idling.
*Confidence: Confirmed* unless noted. Raw log and per-ID summary in
`captures/idle-baseline*.csv`.

| Property | Value |
|---|---|
| Bit rate | 500 kbit/s, classic CAN |
| Aggregate rate | **2,313 frames/s** (~69,600 frames in 30 s) |
| Unique identifiers | **83** — 82 standard 11-bit, 1 extended 29-bit (`0xC1CD000`) |
| Periodicity | **All 83 are strictly periodic.** No event-driven IDs observed at idle. |
| Rate tiers | 100 Hz (9 IDs), 50 Hz (20), 25 Hz (1), 20 Hz (5), 17 Hz (1), 10 Hz (20), 5 Hz (3), 4 Hz (9), 2 Hz (5), 1 Hz (10) |
| Jitter | Sub-millisecond on nearly every ID — a tightly scheduled bus |
| Constant at idle | 37 of 83 IDs never changed a single bit |

### 3.1 Message integrity — CRC-8 and rolling counter

**30 of the 83 IDs protect their payload.** The final byte is an **SAE J1850
CRC-8** over every preceding byte, and the low nibble of the byte before it is a
**4-bit rolling counter** incrementing mod 16 on every frame.

| Parameter | Value |
|---|---|
| Polynomial | `0x1D` |
| Initial value | `0xFF` |
| Final XOR | `0xFF` |
| Reflected | No |
| Coverage | All bytes except the last |

Recovered by brute force over the entire (polynomial, initial value, final XOR)
space — 16.7 million combinations — searching for the parameter set that yields a
constant XOR against the observed check byte. Exactly **one** set is consistent
across every protected ID, and it matches **100% of frames** on all 30. The
rolling counter independently matches on 100% of consecutive frame pairs.

#### The counter nibble is not always the low one

**28 of the 30 protected IDs put the rolling counter in the LOW nibble of
byte[-2]. `0x1E6` and `0x2FA` put it in the HIGH nibble.** Verified over every
frame of a 15 s capture: 28 low, 2 high, none absent. *Confidence: Confirmed.*

This is not a curiosity. `dash_passive.py` initially assumed the low nibble for
all 30 and reported **1,156 counter gaps — "frames missed by the host"** — a 4%
apparent frame loss that would have cast doubt on every capture in this document.
Actual loss, once the nibble is resolved per ID, is **exactly zero across 26,310
protected frames, with zero CRC failures.**

Use `counter_of(payload, can_id)` and `counter_mask(can_id)` from `messages.py`
rather than masking `0x0F` by hand.

Implemented as `crc8_j1850()`, `check_integrity()`, `counter_of()` and
`counter_mask()` in `messages.py` (re-exported by `canbus.py`), with the
protected-ID set as `PROTECTED_IDS` and the exceptions as
`COUNTER_HIGH_NIBBLE_IDS`.

Protected IDs: `1E2 1E4 1E6 1E8 1EC 1EE 1F0 1F2 1F4 1F6 1F8 1FC 1FE 200 202 208
20A 20C 2E2 2E4 2E6 2E8 2EA 2EC 2EE 2F2 2FA 36B 4EE 5E0`

Two consequences for signal hunting:

- On a protected ID, **the last two bytes carry no signal.** They are integrity
  fields, and a byte that appears to "change constantly" there is the counter, not
  data. Many IDs show a changed-bits mask of exactly `0f ff` in those positions
  and nothing else — those messages were entirely static during the capture.
- The remaining 52 IDs have no check byte. `check_integrity()` returning False on
  one of those is meaningless — test membership in `PROTECTED_IDS` first.

### 3.2 Identified messages

| ID | Rate | Signal | Location | Confidence |
|---|---|---|---|---|
| `0x4EC` | 10 Hz | **VIN**, ASCII in three multiplexed parts. Byte 0 is the part index (`00`/`01`/`02`), bytes 1–7 are characters. Reassembles to `1C4PJLDB3FW689935`. | b0 index, b1–7 ASCII | **Confirmed** |
| `0x1E8` | 50 Hz | **Brake switch** — two redundant copies, both asserted when pressed. The higher-rate and therefore preferred reference. | b2 bit 1, b2 bit 2 | **Confirmed** |
| `0x2E2` | 50 Hz | **Brake pressure**, 16-bit big-endian. Zero at rest; observed peaking near `0x15E0` and decaying smoothly to `0x0000` as the pedal is released. Units unknown, scaling unverified. | b0:b1 (b0 high) | **Working** |
| `0x5D8` | 4 Hz | **Brake applied** flag, and a second correlated bit — most likely the brake lamp command. | b0 bit 7, b1 bit 7 | **Confirmed** (b0), **Working** (b1) |
| `0x4DC` | 10 Hz | Two bits following the brake. Body/BCM view of brake state. | b0 bits 1, 2 | **Working** |
| `0x2E6` | 50 Hz | Two bits, **inverted** polarity vs brake — plausibly a "brake released" or drive-permitted interlock. | b5 bits 5, 7 | **Candidate** |
| `0x1E4` | 50 Hz | 16-bit value that ramps with brake application, smaller magnitude than `0x2E2`. Possibly a second pressure channel or a wheel/axle-specific value. | b0:b1 | **Candidate** |
| `0x1EE` | 100 Hz | **Steering wheel angle**, 14-bit. Straight ahead read **7212**; swept 2568–11365. Perfectly smooth, r = 1.000 against itself across a full sweep. | b0 (mask `0x3F`) : b1 | **Confirmed** (location) |
| `0x1EE` | 100 Hz | **Steering angular rate**, 12-bit. Reads exactly **2000** with the wheel stationary; correlates **+0.998** with d(angle)/dt. | b2 (mask `0x0F`) : b3 | **Confirmed** |

#### Engine, from the revving capture

| ID | Rate | Signal | Location | Confidence |
|---|---|---|---|---|
| `0x1FC` | 100 Hz | **Engine speed**, 13-bit, **1 rpm/LSB**. Idle 843, peak 4126 against an observed ~4000 rpm stationary limit. | b0 (mask `0x1F`) : b1 | **Confirmed** |
| `0x1F0` | 50 Hz | **Engine speed, second copy.** Agrees with `0x1FC` to within a few counts (810–4159). | b0 (mask `0x1F`) : b1 | **Confirmed** |
| `0x3EA` | 20 Hz | **Engine speed, third copy at 0.125 rpm/LSB** (8× the others). r = 1.000. | b6:b7 | **Confirmed** |
| `0x1FE` | 50 Hz | **Accelerator pedal or throttle**, 0–77. | b1 (mask `0x7F`) | **Working** |
| `0x1F8` | 100 Hz | **Accelerator pedal or throttle, second copy**, 0–78. | b2 (mask `0x7F`) | **Working** |
| `0x2EC` | 50 Hz | **Manifold vacuum** — runs *inverse* to rpm (r = −0.927), 160 at idle falling toward 0 under load. Pressure would rise, not fall. | b4 (mask `0xF8`) | **Candidate** |
| `0x1F8` | 100 Hz | **Engine load or torque** — tracks rpm at r = +0.965 with no lead or lag, 91–196. | b5 | **Candidate** |

#### The pedal signals were found by their lead, not their correlation

Both pedal fields score only **r ≈ 0.31** against rpm — far below any sensible
threshold — because a driver input *precedes* the engine's response. Correlation
peaks at **+0.61 with rpm delayed ~500 ms**. Two consequences:

- **A low correlation with the obvious reference does not mean unrelated.** Sweep
  the lag before dismissing a field.
- **Lead/lag distinguishes cause from effect.** `0x1F8` b5 tracks rpm at r = 0.965
  with *zero* lag, so it is a consequence of engine speed (load, torque). The pedal
  fields lead it, so they are inputs. Same capture, opposite causal direction,
  distinguishable only by timing.

Which of the two pedal copies is the pedal sensor and which is the throttle plate
is **not** resolved — they are indistinguishable at this resolution. Their maximum
of ~77 rather than ~100 is consistent with a partial-throttle stationary rev, so a
percent scale is plausible but unverified.

#### Gear selector

| ID | Rate | Signal | Location | Confidence |
|---|---|---|---|---|
| `0x4EE` | 10 Hz | **Gear selector position.** `1`=P, `2`=R, `3`=N, `4`=D. `0` appears transiently mid-shift. | b1 (mask `0x0F`) | **Confirmed** |
| `0x20A` | 50 Hz | **Gear selector, second copy**, same enumeration shifted left 3 bits. Spends more time in the transient `0` state (12% vs 1%), so it is likely the raw lever reading. | b1 (mask `0xF8`) >> 3 | **Confirmed** |

A P→R→N→D→N→R→P sweep, twice, produced a clean staircase
`4→3→2→1→2→3→4→3→2→1→2→3`. The mapping is fixed by the other five captures,
**every one of which reads P at 100%** — the car was parked throughout. That is
the strongest cross-validation in this document: five independent captures taken
for unrelated reasons all agree.

`0` decodes to **None**, not to a gear name. "Between positions" must not render
as though it were a selection.

#### One field deliberately left unidentified

`0x1F0` b5 bit 4 asserts only during the gear capture and looks tempting, but
matches nothing cleanly:

| Tested against | Result |
|---|---|
| Gear | 42% asserted in P, 66% R, 77% N, 100% D — a gradient, not a flag |
| Brake | **0% across both brake captures** — not brake |
| Elapsed time | Fluctuates 33–100% across 2 s windows — not a warm-up ramp |

It is **excluded from `SIGNALS`** rather than shipped as a Candidate with a
plausible-sounding name. A gradient across gears would have been easy to call
"gear engaged" and it would have been wrong.

#### Exterior lamps

| ID | Rate | Signal | Location | Confidence |
|---|---|---|---|---|
| `0x5D8` | 4 Hz | **Exterior lamp state.** `0x00`=off, `0x60`=DRL/position, `0x68`=headlamps. Bits 5+6 assert together for any lamp; bit 3 adds on top. | b1 (mask `0x68`) | **Working** |
| `0x3E4` | 20 Hz | **Lamps-off flag.** Asserts only with the lamps fully off — independent confirmation from a different module. | b1 bit 0 | **Working** |

**Lighting IS on CAN-C**, which corrects an expectation formed after the
turn-signal result: the absence of indicators is not because *all* body functions
live elsewhere. Lamp state is here; the blinking indicator specifically is not.

**Three bus states for four switch positions.** The switch has off / DRL-only /
on / auto, and cycling all four produced only three distinguishable states, so at
least two positions coincide on the bus — most plausibly *auto* resolving to
whichever state ambient light dictates, making it indistinguishable from a fixed
position at capture time. **Which switch position maps to which state is
unresolved** and would need a capture holding each position with known timing.
*Confidence: Working* for the bit meanings, **not** for the position mapping.

`0x3E4` b0 bits 3 and 7 also track lamp state, inverted relative to b1 bit 0.

All seven other captures read `headlamps` at 100% and the off-flag at 0%, so the
switch sat in one position throughout the rest of the campaign — a clean control.

#### Turn indicators — and a retracted negative

| ID | Rate | Signal | Location | Confidence |
|---|---|---|---|---|
| `0x5D8` | 4 Hz | **Right indicator lamp**, blinking. 48% duty, 330 ms on / 357 ms off (~1.45 Hz). | b2 bit 5 | **Confirmed** |
| `0x5D8` | 4 Hz | **Left indicator lamp**, blinking. | b2 bit 6 | **Working** |

Both read **0% in all seven captures where no indicator was on**, and the right
capture shows bit 5 blinking continuously and evenly with bit 6 flat. These are
the instantaneous lamp states, so a live display flickers — correct, not a fault.

**This retracts a "Not present" finding recorded earlier**, and the reason is
worth keeping.

The first search demanded a square wave with **jitter under 10%**. That threshold
is unsatisfiable on a **4 Hz message**: a 330 ms dwell sampled every 250 ms is
quantised to 250 ms or 500 ms, so the measured jitter is ~35% *by construction*,
no matter how perfect the underlying blink. At 4 Hz there are only ~2.7 samples
per blink cycle — barely above Nyquist. The detector rejected the correct answer
because the answer could not possibly pass it.

Worse, the negative was then rationalised: indicators are body functions, so their
absence from a powertrain bus seemed architecturally sensible, and that story was
written into this document. The headlight capture had already undermined it — lamp
state *is* on CAN-C (see above) — but the conclusion was not revisited.

**Rules that follow:**

- **Check that a threshold is achievable at the message rate before applying it.**
  A tolerance tighter than the sampling quantisation guarantees a false negative.
- **Do not explain a negative result until the detector is validated against a
  known positive.** The plausible architectural story made a tool bug feel like a
  finding.
- **A negative result on one capture is weaker than it feels.** The right-indicator
  capture cost 15 seconds and overturned it.

##### Four candidates correctly dismissed

The earlier write-up flagged four single-bit steady-state differences as possible
latched turn-signal flags. All four are **unrelated to the indicators**: `0x659`
b1 bit 5 and `0x4F4` b7 bit 3 read one value across the first three captures and
the opposite across all six later ones — a *session* boundary, most likely engine
warm-up, not an input. `0x4DE` b4 bit 0 and `0x1FC` b3 bit 0 vary irregularly
across unrelated captures.

They were held as unconfirmed rather than named, which is the only reason no wrong
signal shipped.

#### Steering notes

- **Field widths are not whole bytes.** Angle is 14 bits, rate is 12, and both
  share bytes with other content. Reading either as a plain `u16` folds a
  neighbouring field into the value. Use the masks.
- **Scaling is unresolved.** The swept span was 8,797 counts. At 0.1°/LSB that is
  880° total (±415°/±464° about centre), which is plausible for a sweep that did
  not quite reach full lock on a vehicle with roughly 2.7 turns lock-to-lock. At
  1/16°/LSB it would be 550°, which is too little. **0.1°/LSB is the working
  hypothesis; not verified.** *Confidence: Candidate.*
- **The angle centre is a sensor calibration, not a protocol constant.** 7212 is
  this vehicle's straight-ahead value and should be re-measured per car. The rate
  zero of 2000 is a clean decimal and is more likely to be a real protocol
  constant.
- **Steering appears exactly once on this segment.** A full scan of every u8 and
  u16 position on all 83 IDs found no other field correlating with angle, and
  **nothing correlating with |rate|** — so no steering *torque* signal is
  published here. That is the field openpilot would need, and its absence on this
  segment matters. MDPS torque presumably lives on another bus.

### Method used

`bus_analysis.py` for a labelled baseline, then a capture with the brake **pumped
at ~1 Hz**. `diff_captures.py` narrowed 83 IDs to a handful of candidates;
`correlate_signal.py` then used one confirmed 50 Hz bit as ground truth to find
the rest of the cluster.

Two things that materially changed the results:

- **A held input and an oscillating input need different detectors.** A brake held
  down for a whole capture is *constant* in both captures at *different values* —
  invisible to a "which bits started varying" test. `diff_captures.py` runs both
  passes for this reason.
- **Reference rate sets timing resolution.** Using the 4 Hz `0x5D8` as ground
  truth found 2 correlated bits; using the 50 Hz `0x1E8` found 8. A slow
  reference blurs fast signals into apparent disagreement.

Everything else on the bus still needs differential capture — see §7.

### 3.3 Vehicle identity from the bus

VIN `1C4PJLDB3FW689935`, read passively off `0x4EC` with no request sent.

| VIN position | Character | Meaning |
|---|---|---|
| 1–3 | `1C4` | Chrysler Group multipurpose vehicle |
| 10 | `F` | **Model year 2015** — not 2016 |
| 11 | `W` | Toluca, Mexico assembly plant — consistent with the vehicle's origin |

The model year correction supersedes the owner's initial recollection of 2016.
*Confidence: Confirmed* (VIN position 10 is standardised).

## 4. Tools

All run with PEP 723 inline dependencies and `requires-python = ">=3.14"` — see
[`../CLAUDE.md`](../CLAUDE.md) for why the floor must not be lowered.

| Tool | Transmits? | Purpose |
|---|---|---|
| `adapter_check.py` | no (loopback) | Prove the adapter can **move frames**, via internal loopback. Pigtail out. Run freely — it is not destructive. |
| `selftest_loopback.py` | optional | Deeper adapter diagnosis: loopback variants, TX echo, error frames. Use when `adapter_check.py` fails. |
| `listen_probe.py` | no | Quick passive frame capture with a per-ID summary. |
| `bus_analysis.py` | no | **Full passive characterisation** in one pass: rates, periodicity, jitter, DLC variation, changed-bits masks, counter detection. Writes a raw frame log for later diffing. |
| `obd_probe.py` | yes | Minimal supported-PID query. Superseded by `diagnostics.py`. |
| `diagnostics.py` | yes | Fault codes (stored / pending / permanent) **with descriptions**, MIL state and advice, freeze frame, VIN, supported PIDs. Optional gated DTC clear. Works over **ELM327** or gs_usb. |
| `selftest_diagnostics.py` | no | **35 checks on the whole decode chain with no car, dongle or adapter attached.** Run after any change to `obd.py`, `elm327.py` or `dtc_descriptions.py`. |
| `dash_passive.py` | **no** | **Live dashboard, listen-only.** Decoded signals with confidence marks, bus health (CRC failures, rolling-counter gaps), and a "moving now" panel for discovery. Works today. |
| `dash.py` | yes | Polled OBD-II dashboard. **Blocked** by §2.6 — has never spoken to the car. |
| `diff_captures.py` | no | Diff two labelled captures: newly-varying bits **and** steady-state differences. Offline. |
| `correlate_signal.py` | no | Given one known **bit**, find every bit and byte that tracks it. Offline. |
| `correlate_analog.py` | no | Given one known **numeric field**, find every byte correlating with its value *or its rate of change*. Offline. |
| `canbus.py`, `obd.py`, `messages.py` | — | Shared plumbing. Not scripts. |
| `elm327.py`, `dtc_descriptions.py`, `capture_io.py` | — | ELM327 transport, DTC descriptions, capture-path safety. Not scripts. |

```bash
uv run jeep-kl/adapter_check.py                        # pigtail OUT, proves the adapter works
uv run jeep-kl/bus_analysis.py --seconds 30 --out captures/idle.csv --label idle
uv run jeep-kl/diagnostics.py                          # read-only fault codes
uv run jeep-kl/dash.py                                 # live values
```

Raw captures go in `jeep-kl/captures/`, which is gitignored.

**Which tools work today**, given §2.6:

| | |
|---|---|
| Listen-only tools | `adapter_check.py`, `listen_probe.py`, `bus_analysis.py` — **all working** |
| Transmitting tools | `obd_probe.py`, `diagnostics.py`, `dash.py` (polled half) — **blocked**, normal mode receives nothing |

**Replug the adapter's USB before every real-bus capture.** Empirically the
adapter delivers one successful capture per USB re-enumeration; the next
invocation returns zero frames regardless of mode. In-process repeated opens and
cross-process loopback runs both work fine, so the trigger appears to involve
sustained high-rate traffic across a process boundary. Root cause unresolved —
see §2.6. The offline tools (`diff_captures.py`, `correlate_signal.py`) need no
adapter at all and can be re-run freely.

## 5. Methodology — rules this vehicle has already taught

Same principle as [`../docs/07-methodology.md`](../docs/07-methodology.md): each
rule is here because something went wrong.

1. **Never leave the adapter wired to CAN-C un-initialised.** With the adapter
   attached to pins 6/14 and *no host process having opened it*, the vehicle
   produced a dash full of warnings across unrelated systems — service
   electronic brake system, service airbag, service electronic throttle control,
   LaneSense, ACC/FCW unavailable — plus a check-engine light. An un-configured
   transceiver can hold the differential pair dominant, and when CAN-C drops
   every module loses contact with every other module and logs
   lost-communication faults simultaneously. **All of the multi-system warnings
   cleared on a key cycle with the pigtail removed**, which is the signature of
   transient lost-communication codes rather than damage.

   A low battery during crank produces a nearly identical dash on FCA vehicles
   and cannot be excluded as a contributing cause. The car had been in normal
   use, which argues against it.

   The order that follows from this:

   ```
   ignition off  →  adapter USB into host  →  confirm enumeration
                 →  pigtail into OBD port  →  ignition on
                 →  run tool immediately   →  pigtail out before next key cycle
   ```

2. **Default to listen-only (silent) mode.** `Bus(listen_only=True)` is the
   default and puts the controller in a state where it physically cannot drive
   the pair or even emit ACK bits. `send()` raises rather than no-op'ing in this
   mode, because a silent no-op looks exactly like an unanswered request.

3. **Expect a firehose, and treat silence as a fault.** Confirmed — §2.5. CAN-C
   broadcasts continuously at pins 6/14. If a listen-only tool returns zero frames
   with the ignition on, **suspect the instrument before the vehicle**: replug USB
   and retry. This rule was briefly retracted mid-session on the strength of six
   silent bitrate sweeps — every one of which was a normal-mode run. It was right
   all along. Retracting a correct rule to accommodate bad measurements is its own
   failure mode.

4. **Vary the instrument, not just the target.** The single most expensive mistake
   here, made **twice**. First: bitrate, wiring, polarity, termination and
   boot-switch position were eliminated rigorously while the *controller mode* was
   never questioned, because it was not in the hypothesis space. Then, having
   learned that, the same error recurred at larger scale — an entire investigation
   into gateway architecture, ACK saturation, ground resistance and bit timing,
   when **unplugging the car and retesting on a desk took two minutes** and
   settled it (§2.6). The adapter was present in every failing observation and was
   the one component never varied.

   The generalisation: when a fault survives many eliminations, ask which
   component appears in *every* failing test. That one is the suspect precisely
   because it never changed.

5. **A tool that reports PASS must have exercised what it certifies.**
   `adapter_check.py` reported PASS for hours on enumeration alone, having never
   moved a frame. Enumeration is not operation.

6. **A multimeter differential reading does not prove traffic**, and its absence
   does not prove silence. 0.6 V across CAN-H/CAN-L was read as a DMM averaging a
   busy bus, then re-read as an idle gateway bias to fit the silence. It was the
   former all along; the meter never distinguished them. Only a decoded frame did.

7. **Meter probes in the connector can latch faults.** An airbag service warning
   appeared while probing pins with the ignition on — a probe tip bridging
   adjacent pins is enough. Measure at the adapter's terminal block rather than
   in the J1962 connector where practical, and prefer ignition off.

8. **Do not expect 60 Ω across pins 6/14.** See §2.2. The gateway makes the
   standard termination check inapplicable here.

9. **Only one process may hold the USB adapter.** A second sees a silent bus,
   which on this vehicle is indistinguishable from a broken connection.

10. **Held inputs and oscillating inputs need different detectors.** A brake held
    down for a whole capture is constant in both captures at different values, and
    is invisible to a "which bits started varying" test. Pump the input instead —
    it converts a level into an unmistakable time signature, and 20 transitions in
    15 s at 1 Hz is self-validating.

11. **Correlate against the highest-rate reference available.** Timing resolution
    is the reference message's period. A 4 Hz reference found 2 correlated bits; a
    50 Hz reference on the same capture found 8.

12. **An integrity checker needs its own integrity check.** The counter-gap
    detector reported 4% frame loss, which was entirely its own bug: two IDs carry
    the counter in the high nibble. Real loss is zero. A monitor that cries wolf
    about data quality will get the *data* distrusted rather than the monitor —
    validate it against a saved capture where the answer is known.

13. **Self-check every correlation.** `correlate_signal.py` scores the reference
    bit against itself and must read 100.0%. It read 67% at first, from an
    off-by-one in the timestamp lookup that silently mismatched every transition.
    A correlation tool with no self-check will confidently report nothing.

### 4.1 Reading fault codes

**The gs_usb adapter cannot do this** — it cannot enter normal mode at all, on any
bus (§2.6). Reading codes requires transmitting, so `diagnostics.py` defaults to an
**ELM327 dongle**: different hardware, different firmware, and about the price of
lunch.

**The dongle on order** (2026-09-15): **OBDResource FORScan ELM327 USB**, ₩29,300.
Two properties decided it over a ₩14,230 alternative:

- **CH340 USB-serial bridge**, printed on the product image. The cheaper unit's
  description pointed at a **PL2303**, which on Apple Silicon macOS is a coin
  flip — Prolific's current drivers refuse counterfeit chips, and counterfeits
  dominate. CH340 is supported on modern macOS. This is the half that talks to
  the host, and it is independent of the ELM327 itself.
- **A physical HS/MS CAN switch**, which reroutes the dongle's transceiver
  between pins **6/14** (CAN-C) and pins **3/11** (the CAN-IHS tap §2.4 and §3.2
  both want and that has never been reached). A bus switch instead of a wiring
  job.

The ELM327 die is not stated in the listing, but FORScan refuses to work with the
cheaper PIC18F2480 clones, so FORScan branding is strong evidence of a
**PIC18F25K80** — the variant with complete AT support and reliable 500 kbit/s
CAN. That is what `elm327.py`'s incomplete-AT-support error at `_init()` exists
to catch if the inference is wrong.

**Before flipping the switch to MS, measure pin 3** (§2.4). On this vehicle pin 3
is not what it is on other cars, and the MS position connects a transceiver to
whatever is actually there.

```bash
uv run jeep-kl/selftest_diagnostics.py                 # no hardware needed
uv run jeep-kl/diagnostics.py --list-ports
uv run jeep-kl/diagnostics.py --port /dev/tty.usbserial-XXXX
uv run jeep-kl/diagnostics.py --port ... --clear --i-understand
```

Both transports implement the same `request()` interface, so if the gs_usb
problem is ever solved, `--transport gsusb` works unchanged.

Codes are reported with descriptions. Unlisted codes fall back to **structural
decoding** — the letter gives the system, the digits narrow the subsystem — so an
undocumented manufacturer code still says where to look instead of printing bare.
Lost-communication `U`-codes carry an explicit note that they are **often
transient**: this vehicle produced a dash full of them when an un-initialised
adapter sat on CAN-C (§5 rule 1), and they cleared on a key cycle. Telling "a
module failed" from "the bus was disturbed and recovered" is the difference
between a repair and a non-event.

## 6. Safety

[`../docs/00-safety.md`](../docs/00-safety.md) applies in full. Additionally,
specific to this vehicle:

- **No SGW means writes are possible.** Passive tools never transmit. The
  transmitting tools (`diagnostics.py`, `dash.py`, `obd_probe.py`) send only
  OBD-II emissions services, never UDS, and never address ABS/ESC (`0x7D1`) or
  MDPS (`0x7D4`) directly.
- **`diagnostics.py` can clear DTCs**, behind `--clear --i-understand`, and only
  after writing a JSON report. This is the sole exception to the repository's
  no-DTC-clear rule, scoped to this vehicle for ordinary maintenance — see
  [`../CLAUDE.md`](../CLAUDE.md). Do not relax the gates.
- **Do not drive with warnings on the dash.** A steady yellow MIL is
  "investigate soon"; a flashing MIL is "stop".
- Insulate every unused pigtail conductor individually. Pin 16 (green/white) is
  **unswitched battery** and is the dangerous one.

## 7. Current state

**Established**

- CAN-C wiring confirmed end-to-end, including a pin-16 orientation check. §2
- `dash_passive.py` **confirmed working live** — VIN read passively, brake cluster
  reading correctly, zero CRC failures and zero counter gaps.
- **CAN-C is live at 500 kbit/s on pins 6/14** — 83 IDs, 2,313 frames/s, all
  strictly periodic. §2.5, §3
- **SAE J1850 CRC-8 + 4-bit rolling counter** on 30 of the 83 IDs, parameters
  fully recovered. §3.1
- **VIN read passively** off `0x4EC`: `1C4PJLDB3FW689935`, model year 2015. §3.3
- **Brake cluster identified** — switch (two redundant bits), 16-bit pressure,
  applied flag, and body-side copies. §3.2
- **Steering angle and angular rate identified** on `0x1EE` at 100 Hz. §3.2
- **Engine speed identified on three IDs** (two at 1 rpm/LSB, one at 0.125), plus
  two pedal/throttle copies and load/vacuum candidates. §3.2
- **Gear selector decoded** on `0x4EE` and `0x20A`, P/R/N/D. §3.2
- **Exterior lamp state decoded** on `0x5D8`, with an independent off-flag on
  `0x3E4`. §3.2
- **21 signals now decode**, cross-validated by replaying captures they were not
  derived from: brake reads all-zero during the revving capture, steering rate
  reads exactly 0 with the wheel parked, and gear reads P at 100% across all five
  non-gear captures.
- **Normal mode receives nothing; listen-only works perfectly.** §2.6

**Open**

- **The gs_usb adapter is faulty** — it cannot enter normal mode at all, on any
  bus (§2.6). `dash.py`'s polled half and `obd_probe.py` are unusable until it is
  reflashed or replaced. This is not a property of the vehicle.
- `diagnostics.py` now has an **ELM327 transport** that routes around the problem
  entirely (§4.1). **A dongle is on order as of 2026-09-15** — an OBDResource
  FORScan ELM327 USB with a CH340 bridge and an HS/MS CAN switch (§4.1). Its
  decode chain passes 35 offline checks (`selftest_diagnostics.py`), so the
  remaining unknown is the dongle, not the code.
- **The check-engine light is still unread.** The one outstanding item with
  real-world consequences rather than research interest.
- **Fuel level has never been searched for**, on either route. It is absent from
  §3.2, and it is **not** rated *Not located* — that rating means a bounded
  search failed, and no search has been made. `obd.py` already decodes PID `0x2F`
  and `obd_probe.py` already probes for it; neither has ever run. See §8, where
  it is now the top priority.
- The distinguishing experiment for §2.6 has not been run:
  `scratchpad/normal_mode_forensics.py` records whether normal mode receives a
  brief burst then stops (joined, then kicked off by ACK failures) or nothing at
  all (never joined). That decides software-fixable vs different-hardware.
- **One capture per USB replug**, cause unknown. §2.6
- Steering angle **scaling** unresolved — 0.1°/LSB is the working hypothesis. §3.2
- Eight captures exist: baseline, two brake, steering sweep, revving, left
  indicator, gear selector, headlights.
- **Headlight switch-position mapping unresolved** — four positions, three bus
  states. §3.2
- A **right-indicator** capture would test the latched-flag candidates in §3.2.
- `0x1F0` b5 bit 4 is **unexplained** — see §3.2.
- **Turn signal is absent from CAN-C** (§3.2) even though lamp state is present,
  so the CAN-IHS tap at pins 3/11 remains worth doing but is a weaker bet than it
  looked. Measure pin 3 first (§2.4).
- **Pedal vs throttle-plate is unresolved** — the two copies are indistinguishable
  at this resolution. A slow, deliberate pedal ramp might separate them.
- **Nothing has been captured with the vehicle moving.** A 115-second drive
  capture was taken and then **destroyed** by rerunning the same command with the
  same `--log` path while stationary. `bus_analysis.py` and `dash_passive.py` now
  refuse to overwrite an existing capture without `--force`, so this cannot recur.
  Wheel speeds, road speed and the 37 idle-constant IDs still need a drive;
  `0xC1CD000` (the extended ID) has never changed a bit.
  The one thing the lost capture did establish: **logging keeps up with the bus** —
  83,163 frames over 36 s is 2,310 frames/s, matching the bus rate exactly, so the
  dashboard's logging is not a bottleneck.
- **No steering torque signal exists on this segment** (§3.2). If openpilot
  compatibility is ever assessed for this vehicle, that is a finding of the same
  kind as the Casper's ADAS-segment conclusion in
  [`../docs/06-adas-openpilot.md`](../docs/06-adas-openpilot.md).
- `listen_probe.py` formats extended (29-bit) IDs poorly — one appeared as
  `C1CD000`. `bus_analysis.py` handles them correctly.
- 37 of 83 IDs were fully constant at idle, and `0xC1CD000` (the extended ID) has
  never changed a bit. Some will need the vehicle moving.
- CAN-IHS on pins 3/11 unverified — **measure pin 3 before connecting.** §2.4
- Outstanding dash items: change engine oil (maintenance reminder), licence plate
  light out (a real bulb), and a **steady yellow check-engine light** whose code
  has not been read. Whether the MIL predates this session is unresolved.

## 8. Next steps — ordered, fuel gauge first

The stated priority is a **live fuel-gauge reading**. That phrase hides a fork,
and the fork decides the order of everything below.

| | What it gives | Cost |
|---|---|---|
| **Polled** — OBD-II PID `0x2F` | A tank percentage on demand, a few Hz. Decoder already written (`obd.py:148`). | One dongle, one code change |
| **Broadcast** — a CAN signal | The cluster's own value, continuous, no request needed. The real "live gauge". | A search that has never been attempted |

The polled route is not merely the easier one — **it is how the broadcast route
gets found**. A known-good percentage, timestamped against a simultaneous passive
capture, turns a blind diff into the same supervised correlation that produced
engine speed and steering angle (§3.2, "Method used"). Do them in this order.

### Stage 0 — before the dongle arrives (no hardware needed)

1. **Give `obd_probe.py` the ELM327 transport.** It imports `canbus.Bus`
   directly (`obd_probe.py:31`) and has no `--transport` flag, so it is still
   welded to the adapter §2.6 broke. `Elm327Transport` and `GsUsbTransport`
   already expose an identical `request()`, so this is a constructor swap plus
   the `--port` / `--baud` flags `diagnostics.py` already has.
2. **Teach `elm327.py` user-defined protocol B.** `PROTOCOL = "6"`
   (`elm327.py:29`) pins it to ISO 15765-4 11-bit at **500 kbit/s** — CAN-C only.
   CAN-IHS is **125 kbit/s**, reachable only via `ATSP B` with an `ATPP 2C` baud
   divisor. Needed for Stage 3; not needed before it.
3. **Extend `selftest_diagnostics.py`** to cover both. The 35 offline checks are
   the reason the dongle is the only unknown; keep it that way.

### Stage 1 — desk check, before going near the car

```bash
uv run jeep-kl/selftest_diagnostics.py
uv run jeep-kl/diagnostics.py --list-ports
```

Nothing listed means the **CH340 driver**, not a faulty dongle. Settle that
indoors. If `ATZ` returns nothing, try `--baud 115200`; the code defaults to
38400 and clones ship at both.

### Stage 2 — first trip to the car, switch in **HS**

Pigtail **out** — the dongle needs the whole connector. Ignition **ON**.

1. **Read the fault codes.** `uv run jeep-kl/diagnostics.py --port ...` — the
   steady yellow MIL is the one open item with real-world consequences. Do it
   first because it is the thing that might change what you do next.
2. **Probe for PID `0x2F`.** Supported means fuel level is solved to a
   percentage the same minute.
3. **Log a value, a timestamp and the dash gauge position** at the same moment.
   That triple is the ground truth Stage 3 consumes. Cheap to take now,
   impossible to reconstruct later.

Expect the percentage to be **coarse or stepped** — that is normal for FCA and
is not a decode bug.

### Stage 3 — the broadcast signal, which is the actual live gauge

Fuel is a **slow** signal: it will not move inside a 36-second capture, so the
correlation method that found brake and steering does not apply directly. It
needs captures at genuinely different tank levels.

1. Take a `bus_analysis.py` capture **at each fill state you can get** — ideally
   either side of a refuel, labelled with the PID `0x2F` reading from Stage 2.
   Three points beat two, because three test **monotonicity** and two do not.
2. `diff_captures.py` across them, concentrating on the **37 IDs that were fully
   constant at idle** (§7). A tank level is exactly the kind of signal that hides
   there.
3. Expect several candidates to survive: odometer, trip counters, ambient
   temperature and battery voltage all drift between sessions too. Monotonicity
   against a known fill order is what separates fuel from those.
4. **If nothing on CAN-C tracks it**, that is informative rather than a failure —
   it is the same shape as the turn-signal result (§3.2), and it points at
   CAN-IHS. Then, and only then, flip to **MS** — after measuring pin 3 (§2.4),
   and with protocol B from Stage 0 in place.

### What would make this fail, and the cheaper thing to try first

Every step above assumes the dongle. **Remedy 2 of §2.6 — reflashing candleLight
over DFU — is still untested and still free**, and it is the only route that also
revives the Casper's polled toolchain, which depends on the same broken adapter.
The desk evidence favours it: loopback returns 5 frames before normal mode and 0
after, with no bus attached and no frame transmitted, which is a firmware hang,
not damaged silicon. Twenty minutes with the BOOT switch **ON** before the dongle
arrives is well spent.

If it works, verify that it enters **normal mode and stays up** — not merely that
loopback passes. Loopback was never what broke. That is §2.7's rule: a tool that
reports PASS must have exercised the thing it certifies.

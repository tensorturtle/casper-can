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

### 2.3 Adapter termination switch position — `K` here, `E` on the Casper

**The R120 termination switch must be in `K` for this vehicle.** In `E` the
adapter receives **nothing at all** — not a degraded capture, not a few frames,
but total silence. *Confidence: Confirmed*, 2026-09-16, by direct A/B on a running
engine: `E` gave 0 frames at every bitrate from 33 kbit/s to 1 Mbit/s; moving the
switch to `K` and replugging gave **75,468 frames, 80 IDs, 3,773 frames/s** on the
very next command, with nothing else changed.

This supersedes the earlier note that the switch's effect "has never been cleanly
measured". It has now.

Why it bites: this vehicle has no termination reachable at the OBD connector
(§2.2 — 3.6 MΩ, a gateway-buffered stub), so the adapter's own resistor is the
only one in the path. The Casper presents a normal 60 Ω bus, where adding a third
terminator is what breaks things. **The correct setting is opposite on the two
cars**, which is exactly why this is easy to get wrong.

> **Moving the adapter between the Casper and the Jeep? Move this switch.**
> One adapter serves both vehicles and the Radxa Zero 3W, and the required
> position differs per vehicle:
>
> | Vehicle | R120 |
> |---|---|
> | Jeep Cherokee KL | **`K`** |
> | Hyundai Casper | **`E`** |
>
> The failure mode is silent and deeply misleading. A wrong switch position looks
> identical to a dead adapter, a dead bus, an ignition-off car or a faulty
> pigtail — and it survives every software check, because loopback never reaches
> the transceiver and passes regardless. It cost a full diagnostic session before
> being found, during which bitrate, USB re-enumeration, host-side reset and
> ignition state were all excluded first.
>
> **Check the switch before anything else** when a bus that previously worked has
> gone silent and the adapter has been anywhere near the other car.

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

#### 2026-09-16 — the wedge no longer reproduces. This is not yet a retraction.

`normal_mode_forensics.py` — the experiment §7 listed as never run — was written
and run. It is the desk experiment §2.6 describes: loopback, then a normal-mode
start with no bus attached and no frame transmitted, then loopback again.

| | Result |
|---|---|
| Runs | 6, on the same power cycle, three of them back to back |
| Loopback before normal mode | 5 of 5 every run |
| Normal-mode start | Succeeded every run, no exception raised |
| Loopback after normal mode | **5 of 5 every run** — §2.6 recorded 0 |

The back-to-back runs matter more than the count. §2.6 established that only a
physical USB power cycle clears the wedge, so had a normal-mode start wedged the
adapter, the *next* run's first loopback would have returned 0. It returned 5,
six times.

**The firmware hang is not present.** *Confidence: Confirmed* for the desk
behaviour.

**That is not the same as "the adapter can transmit", and the difference is the
whole of §2.7.** Loopback never reaches the transceiver. §2.7 records this exact
adapter being wrongly declared healthy once already, on exactly this class of
evidence, and the rule written from it is that a tool reporting PASS must have
exercised the thing it certifies. Nothing here has put a bit on a wire.

So the status of transmission is **Not verified**, not *Working*. The outstanding
test is a real request to a real module on the vehicle — `diagnostics.py
--transport gsusb` — with a response decoded. Until that returns, treat the
ELM327 dongle as still the primary route and this as a promising second.

What changed is unknown. The adapter had been moved to the Radxa Zero 3W and back
between sessions, so it has seen power cycles that §2.6's session did not, and
§2.6's "degradation" may have been a state that outlived a replug but not a
relocation. Recorded as unexplained rather than reasoned about — §2.7's failure
was building theory on top of a measurement instead of testing it.

##### Settled the same day, at the car: §2.6 stands.

The vehicle test was run hours later, on a live bus with the termination switch
finally correct (§2.3), on a **fresh USB enumeration with nothing run before it**
so no spent-enumeration excuse survives:

| | Result |
|---|---|
| Receive, listen-only | **75,468 frames, 80 IDs, 3,773 frames/s** — flawless |
| `diagnostics.py --transport gsusb` | **no answer from any module** |

**So the adapter still cannot transmit, and everything above this heading is a
false negative.** The desk experiment could not have detected the fault, because
the only evidence it collects is loopback and loopback never reaches the
transceiver. That is §2.7's rule — *a tool that reports PASS must have exercised
the thing it certifies* — and it was violated by a script written to honour it.

The addendum is kept rather than deleted, because the mistake is the useful part:
it shows the rule is not obeyed by quoting it. **Nothing about transmission should
be believed until a real module answers a real request.**

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

### 3.4 Five identifiers stopped broadcasting between August and September

**This is the leading explanation for the faulty fuel gauge (§8).**
*Confidence: Confirmed* for the disappearance itself.

| ID | Rate in August | DLC | Constant payload in August | Now |
|---|---|---|---|---|
| `0x2F6` | 10 Hz | 1 | `32` — **decimal 50** | **absent** |
| `0x2F8` | 5 Hz | 5 | `00 00 00 00 00` | **absent** |
| `0x6DA` | 2 Hz | 4 | `05 00 00 00` | **absent** |
| `0x7D2` | 1 Hz | 2 | `01 00` | **absent** |
| `0x7D8` | 1 Hz | 4 | (varied) | **absent** |

All five appeared at exact, regular rates in **every one of the nine August
captures**, including 15-second ones. In the 2026-09-16 capture — 40 seconds, the
longest ever taken on this vehicle — **none of them appears at all**. Absence over
a longer window than the ones that saw them is not a sampling artefact.

Reproduce with:

```bash
uv run jeep-kl/slow_signal_candidates.py     # they drop out of the ID set entirely
```

**`0x2F6` is the fuel-level candidate.** A **single byte at 10 Hz holding 50** has
exactly the shape of a tank percentage, and a roughly half-full tank in August is
consistent with it. *Confidence: Candidate* — this is inference from shape and
value, not a decode, and it cannot be confirmed while the message is absent.

**Why this matters more than any signal search.** It answers the question §8 was
built to ask. The cluster is not being told a *wrong* fuel level; it is being told
**nothing**. That accounts for every symptom together:

- the gauge pinned at its minimum — there is no value to render;
- the low-fuel telltale **blinking** rather than steadily lit — the cluster is
  flagging missing data, not reporting a low tank. The owner's report that it
  never blinks in normal use is what makes this readable.

**It also redirects the repair.** §8's research pointed at the saddle tank's two
level senders. A failed sender produces a wrong or pinned *value*; it does not
remove five identifiers from the bus. This is a module, its power, or its wiring.
**Check fuses before buying parts.**

Five identifiers vanishing together points at **one module going silent**, not
five independent faults. A silent module on CAN-C normally sets a
**lost-communication U-code** in the modules that miss it — which makes the unread
MIL (§7) the most likely place its identity is already written down. See §5 rule 2
for the one case where such codes are transient rather than real.

**The absence survives a key cycle.** A second 40-second capture was taken after
restarting the engine, and the two captures have **identical identifier sets** —
78 each, the same five missing:

| Capture | IDs | frames/s | `2F6` | `2F8` | `6DA` | `7D2` | `7D8` |
|---|---|---|---|---|---|---|---|
| `idle-baseline` (August) | 83 | 2,313 | 300 | 150 | 60 | 30 | 30 |
| `fuel-relatively-full-gauge-empty` | 78 | 2,252 | – | – | – | – | – |
| `fuel-confirm-after-keycycle` | 78 | 2,160 | – | – | – | – | – |

So this is a **persistent** silence, not an intermittent dropout, and not a
transient bus disturbance of the kind §5 rule 2 describes. *Confidence: Confirmed.*

**Settled by the key-on capture (§3.5): the module never powers up.** The five
appear at no point in 75 seconds spanning ignition-off, key-on, the node-address
burst and a minute of idling. A module with power but a bad sensor still boots and
broadcasts; one that never transmits at all has no power. **Check fuses, grounds
and connectors first.**

**Not yet established:** which module, and whether the five are one module's output
or several. Note that `0x7D2` sits in the `0x7Dx` range this vehicle also uses for
periodic broadcast (`0x7D0` and `0x7D4` are still present), so the missing set
spans at least two ID blocks — consistent with one module holding several
identifiers, but not proof of it.

### 3.5 The key-on transient — 17 identifiers that steady-state capture never sees

Every capture before 2026-09-16 was taken with the engine already idling. A
75-second capture spanning **ignition off → RUN → engine start**
(`captures/key-on-transient.csv`) sees **95 identifiers** against 78 at steady
state and 83 in August. *Confidence: Confirmed.*

| Phase | t | What appears |
|---|---|---|
| Before key-on | 0.19 s | `0x817A006`, `0x817A00D`, `0x817A035` — 3 extended IDs, distinct payloads, on an otherwise near-dormant bus |
| Key-on | 4.45 s | 55 identifiers start at once; `0xF7`, `0xF2`, `0xF4` appear once or twice and never again |
| Just after | 6.51 s | **11 extended IDs in 20 ms, every payload identical**: `00 00 00 07 60 20` |

**The bus appears to have a node-address space.** The 6.51 s burst is one module
emitting the same payload to eleven different identifiers that differ only in the
low byte:

```
1E114000  1E114001  1E114002  1E114006  1E11400B  1E11400D
1E114018  1E11401A  1E11401E  1E114035  1E114039
```

Identical payload plus varying low byte reads as **addressing, not data** — a
network-management broadcast to each node in turn. The addresses `06`, `0D` and
`35` also appear as the low byte of the three pre-ignition `0x817A0xx` messages,
which is what makes the address reading more than a coincidence.

*Confidence: Candidate.* This is one burst in one capture. Take a second key-on
capture before trusting the address list, and note that a module being *addressed*
does not prove it is alive — the sender has no way to know.

#### `0x7D8` is multiplexed into four channels — function unknown

It is the only one of the five missing identifiers that carried changing data.
Byte 0 takes exactly four values and behaves as an index; byte 1 then carries a
value in the 21–25 range:

```
00 17 80 00     byte 0: 0x00 0x08 0x10 0x18  -> index 0,1,2,3
08 15 40 00     byte 1: 23, 21, 24, 24       -> four values, all 21-25
10 18 80 00
18 18 c0 00
```

Four channels invites "four wheels" and therefore TPMS, and the KL does handle
TPMS in a separate RF-Hub behind the rear headliner. **The vehicle contradicts
it**: the tyre-pressure telltale is not lit (owner-confirmed 2026-09-16), and a
dead TPMS receiver should raise one. Four channels on this vehicle could equally
be four cylinders.

*Confidence: Not identified.* Recorded because the multiplexing is Confirmed and
because ruling TPMS out is itself useful — it removes the most obvious module
candidate for §3.4.

**Why it was worth taking:** it is the experiment that settled §3.4. See below.

#### The five missing identifiers never appear, even at power-up

`2F6`, `2F8`, `6DA`, `7D2`, `7D8`: **0 frames across the entire 75 seconds**, in
every phase — dormant bus, key-on, the address burst, and a minute of idling.

This is the discriminator §3.4 could not provide. A module that has power but
cannot read its sensor still boots and broadcasts, then faults; it would appear at
key-on and stop, or publish an invalid value. **Appearing at no point means it
never powers up.**

| Observation | Conclusion |
|---|---|
| Appears at key-on, then stops | Module alive, sensor/wiring fault |
| **Never appears at all** ← this vehicle | **Module has no power** — fuse, ground, or connector |

*Confidence: Confirmed* for the observation; *Working* for the conclusion, which
assumes the module would broadcast at all if powered.

**Ten minutes of driving, including speed bumps, changed nothing.**
`captures/drive-keyon-gauge-empty.csv` — **2,418,361 frames, 95 identifiers, 10
minutes**, spanning ignition-off, key-on, and a drive over deliberately rough
surface. None of the five appeared once.

That is a second, independent discriminator, and it is about *how* open the
circuit is:

| Observation | Conclusion |
|---|---|
| Returns for a few frames under vibration | **Marginal** — corroded ground, loose pin, chafed wire |
| **Silent through speed bumps** ← this vehicle | **Cleanly open** — blown fuse, broken ground, unplugged connector |

Speed bumps are about the strongest provocation available without dismantling
anything. A marginal connection would be expected to make contact at least once
in ten minutes of it. **Look for something plainly disconnected rather than
wiggle-testing harnesses.** *Confidence: Working.*

Driving also added **no new identifiers** — all 95 were present within 30 s of
key-on. So road speed and the wheel speeds are inside identifiers that were
already being captured and were merely constant at idle, not on messages that
appear only in motion.

**So check fuses, grounds and connectors before replacing any module or sender.**
This is now evidence, not the process-of-elimination guess it was in §3.4.

Consistent with the owner's report that the gauge is pinned and the low-fuel
telltale blinking **from the instant of key-on**, before the engine runs — the
data source was never present, rather than failing once the engine started.

## 4. Tools

All run with PEP 723 inline dependencies and `requires-python = ">=3.14"` — see
[`../CLAUDE.md`](../CLAUDE.md) for why the floor must not be lowered.

| Tool | Transmits? | Purpose |
|---|---|---|
| `adapter_check.py` | no (loopback) | Prove the adapter can **move frames**, via internal loopback. Pigtail out. Run freely — it is not destructive. |
| `selftest_loopback.py` | optional | Deeper adapter diagnosis: loopback variants, TX echo, error frames. Use when `adapter_check.py` fails. |
| `normal_mode_forensics.py` | yes (internal) | **Reproduce §2.6's normal-mode wedge on a desk**, no vehicle needed: loopback, normal-mode start, loopback again. Refuses to run if it sees bus traffic. |
| `long_capture.py` | no | **Streaming long capture.** Writes each frame as it arrives instead of buffering, so a 10-minute run costs no memory and an interrupted one still leaves a valid file. Announces the moment a `--watch` identifier appears — the tool for "did it ever come back". |
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
| `slow_signal_candidates.py` | no | **Find signals too slow to move inside one capture** — frozen within every capture, different between them. The method for fuel level, odometer and anything else that changes between visits rather than during them. Offline. |
| `canbus.py`, `obd.py`, `messages.py` | — | Shared plumbing. Not scripts. |
| `elm327.py`, `dtc_descriptions.py`, `capture_io.py` | — | ELM327 transport, DTC descriptions, capture-path safety. Not scripts. |

```bash
uv run jeep-kl/adapter_check.py                        # pigtail OUT, proves the adapter works
uv run jeep-kl/bus_analysis.py --seconds 30 --out captures/idle.csv --label idle
uv run jeep-kl/diagnostics.py                          # read-only fault codes
uv run jeep-kl/dash.py                                 # live values
```

Raw captures go in `jeep-kl/captures/`, which is gitignored.

**Which tools work today** (revised 2026-09-16, see the §2.6 addendum):

| | |
|---|---|
| Listen-only tools | `adapter_check.py`, `listen_probe.py`, `bus_analysis.py`, `dash_passive.py` — **all working** |
| Long captures | `long_capture.py` — **working**, 2.4M frames over 10 minutes with the vehicle moving |
| Offline tools | `diff_captures.py`, `correlate_*.py`, `slow_signal_candidates.py`, `selftest_diagnostics.py` — **all working**, no hardware at all |
| Transmitting tools | `obd_probe.py`, `diagnostics.py`, `dash.py` (polled half) — **untested, worth trying.** The normal-mode hang that blocked them no longer reproduces on the desk. That is not proof they work: loopback never reaches the transceiver, and §2.7 is the record of believing it did. One real request to a real module settles it. |

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

1. **Shared hardware carries per-vehicle settings. Check them before debugging
   anything else.** One adapter serves the Jeep, the Casper and the Radxa Zero
   3W, and its R120 termination switch needs **opposite positions** on the two
   cars — `K` here, `E` on the Casper (§2.3). Left on the wrong one it receives
   *nothing*, at any bitrate, while every software check still passes: loopback
   never reaches the transceiver, so the adapter certifies itself healthy while
   deaf. The cost of checking is one glance; the cost of not checking was an
   entire session that excluded bitrate, USB re-enumeration, host-side reset and
   ignition state before anyone looked at the switch. **When a bus that worked
   before goes silent, ask what physical state moved since it last worked** — and
   with shared hardware, the answer is usually "it was on the other car".

2. **Never leave the adapter wired to CAN-C un-initialised.** With the adapter
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

3. **Default to listen-only (silent) mode.** `Bus(listen_only=True)` is the
   default and puts the controller in a state where it physically cannot drive
   the pair or even emit ACK bits. `send()` raises rather than no-op'ing in this
   mode, because a silent no-op looks exactly like an unanswered request.

4. **Expect a firehose, and treat silence as a fault.** Confirmed — §2.5. CAN-C
   broadcasts continuously at pins 6/14. If a listen-only tool returns zero frames
   with the ignition on, **suspect the instrument before the vehicle**: replug USB
   and retry. This rule was briefly retracted mid-session on the strength of six
   silent bitrate sweeps — every one of which was a normal-mode run. It was right
   all along. Retracting a correct rule to accommodate bad measurements is its own
   failure mode.

5. **Vary the instrument, not just the target.** The single most expensive mistake
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

6. **A tool that reports PASS must have exercised what it certifies.**
   `adapter_check.py` reported PASS for hours on enumeration alone, having never
   moved a frame. Enumeration is not operation.

7. **A multimeter differential reading does not prove traffic**, and its absence
   does not prove silence. 0.6 V across CAN-H/CAN-L was read as a DMM averaging a
   busy bus, then re-read as an idle gateway bias to fit the silence. It was the
   former all along; the meter never distinguished them. Only a decoded frame did.

8. **Meter probes in the connector can latch faults.** An airbag service warning
   appeared while probing pins with the ignition on — a probe tip bridging
   adjacent pins is enough. Measure at the adapter's terminal block rather than
   in the J1962 connector where practical, and prefer ignition off.

9. **Do not expect 60 Ω across pins 6/14.** See §2.2. The gateway makes the
   standard termination check inapplicable here.

10. **Only one process may hold the USB adapter.** A second sees a silent bus,
   which on this vehicle is indistinguishable from a broken connection.

11. **Held inputs and oscillating inputs need different detectors.** A brake held
    down for a whole capture is constant in both captures at different values, and
    is invisible to a "which bits started varying" test. Pump the input instead —
    it converts a level into an unmistakable time signature, and 20 transitions in
    15 s at 1 Hz is self-validating.

12. **Correlate against the highest-rate reference available.** Timing resolution
    is the reference message's period. A 4 Hz reference found 2 correlated bits; a
    50 Hz reference on the same capture found 8.

13. **An integrity checker needs its own integrity check.** The counter-gap
    detector reported 4% frame loss, which was entirely its own bug: two IDs carry
    the counter in the high nibble. Real loss is zero. A monitor that cries wolf
    about data quality will get the *data* distrusted rather than the monitor —
    validate it against a saved capture where the answer is known.

14. **Self-check every correlation.** `correlate_signal.py` scores the reference
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

- **The gs_usb adapter still cannot transmit.** §2.6 stands, now retested against
  a live, correctly-terminated bus: receive is perfect (75,468 frames, 80 IDs,
  3,773 frames/s) while `diagnostics.py --transport gsusb` gets **no answer**, on a
  fresh enumeration with nothing run before it. The desk experiment that suggested
  otherwise (§2.6 addendum) was loopback-based and therefore could not see this —
  §2.7's rule, demonstrated again. **The ELM327 dongle remains the route to fault
  codes**, and reading them is now the highest-value action in the project because
  it should name the module that went silent (§3.4).
- `diagnostics.py` now has an **ELM327 transport** that routes around the problem
  entirely (§4.1). **A dongle is on order as of 2026-09-15** — an OBDResource
  FORScan ELM327 USB with a CH340 bridge and an HS/MS CAN switch (§4.1). Its
  decode chain passes 35 offline checks (`selftest_diagnostics.py`), so the
  remaining unknown is the dongle, not the code.
- **The check-engine light is still unread**, and it is now the single most
  valuable unread thing in the project: five identifiers went silent (§3.4), and
  that normally writes a lost-communication U-code naming the module.
- **The fuel gauge is faulty, and the bus explains why.** The gauge reads at its
  lowest position on a relatively full tank and the **low-fuel telltale blinks** —
  behaviour the owner has never seen in normal use. **Five identifiers that
  broadcast in every August capture are now completely absent** (§3.4), one of
  them a single-byte 10 Hz value of 50 that has the shape of a tank percentage.
  The cluster is being told *nothing*, not something wrong. *Confidence: Confirmed*
  for the disappearance, *Candidate* for `0x2F6` being fuel level.
- **The silent module never powers up** (§3.5) — the five appear at no point in a
  capture spanning ignition-off through key-on and idle. That points at a fuse,
  ground or connector rather than a failed sender or module. **Which** module it
  is remains unknown; a lost-communication U-code is the likely record of it.
- **The bus has an undocumented node-address space** (§3.5) — eleven addresses
  seen in a key-on broadcast, three of them also awake before ignition. *Candidate*,
  from a single burst. A second key-on capture would confirm the address list, and
  it may be the route to naming the silent module.
- **Nothing had ever been captured across a key-on** until 2026-09-16. It revealed
  17 identifiers invisible to steady-state capture. Other transitions — key-off,
  door unlock, engine stop — have still never been captured and may hide as much.
- **Fuel level has never been searched for on the bus**, on either route. It is
  absent from §3.2, and it is **not** rated *Not located* — that rating means a
  bounded search failed, and no search has been made. `obd.py` already decodes PID
  `0x2F` and `obd_probe.py` already lists it as "fuel tank level"; neither has
  ever run.
- ~~The distinguishing experiment for §2.6 has not been run.~~ **Done** —
  `normal_mode_forensics.py` now exists in this directory (not `scratchpad/`) and
  reproduces §2.6's desk sequence. Result in the §2.6 addendum: the hang is gone.
  The remaining question it cannot answer is whether normal mode *joins* a live
  bus, which needs the vehicle.
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
- ~~Nothing has been captured with the vehicle moving.~~ **Done 2026-09-16** —
  `captures/drive-keyon-gauge-empty.csv`, 10 minutes and 2.4M frames including
  key-on and speed bumps. Not yet mined for road speed or wheel speeds; §3.5
  notes they must be inside identifiers that were already constant at idle,
  since driving added no new ones. The note below is kept for the rule it taught.
- **(historical) Nothing had been captured with the vehicle moving.** A 115-second drive
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
  has not been read. **The MIL predates this work** — owner-confirmed 2026-09-16,
  attributed to unrelated earlier issues. This resolves the question left open in
  August and has a practical consequence: a fault-code read will return **old and
  new codes mixed**, and the lamp cannot distinguish them. Read the **pending**
  set and freeze-frame data first — that is where a recently-set fault shows —
  rather than assuming the first familiar code explains the newest symptom.
- **No other symptoms accompany the fuel-gauge fault** — owner-confirmed
  2026-09-16. No tyre-pressure warning, and nothing odd about interior lights,
  locks, chimes, wipers or the temperature readout. This is evidence about §3.4:
  whatever module went silent drives **nothing else the driver can see**, which
  argues against a major body module and against the `0x7D8`-is-TPMS reading (a
  dead TPMS receiver should raise a tyre warning, and none is present).

## 8. Next steps — the fuel gauge, which is now a fault and not just a signal

**The goal changed on 2026-09-16.** This section previously planned the search for
a healthy fuel signal. The gauge is in fact **faulty**: it reads at its lowest
possible position on a tank the owner reports as topped up, and the low-fuel
telltale **blinks** rather than simply illuminating as it does in normal use (§7).

That reframes the work without discarding it. The same search is still required,
but it now answers a diagnostic question rather than a curiosity:

> Does the bus carry a **correct** fuel level that the cluster renders wrongly, or
> a **wrong** one that the cluster renders faithfully?

This is a digital dash, so the classic failure of a mechanical gauge — a stuck
stepper motor — is **architecturally impossible**. The cluster is rendering a
number. Either the number is wrong or the rendering is, and one passive capture at
a known tank level distinguishes them. Passive is all that is needed, which is why
this survived the adapter being unable to transmit.

> **Answered 2026-09-16, and by neither branch of the fork.** The capture was
> taken and **five identifiers that broadcast in every August capture are gone**
> (§3.4) — including `0x2F6`, a single-byte 10 Hz value of 50 with the shape of a
> tank percentage. The cluster is not being told a wrong number; it is being told
> **nothing**. That accounts for the pinned gauge and, separately, for the
> *blinking* telltale, which is the cluster flagging missing data rather than
> reporting a low tank.
>
> Everything below remains the correct plan for **decoding** fuel level, and is
> worth doing once the signal is back. But the immediate question is no longer
> "which byte is fuel" — it is **which module went silent and why**. Read the
> fault codes, and check fuses before buying a pump module: a failed sender
> produces a wrong value, not five missing identifiers.

**The blink is evidence, and it is the owner's own baseline that makes it so.**
A cluster whose renderer had failed would show a wrong value; it would not invent
a signalling pattern it has no reason to produce. A cluster that has *detected* a
bad input would. This argues against the cluster and toward the value reaching it
— which means the fault is likely **stored as a DTC**. *Confidence: Candidate* —
it is an inference from one behavioural observation, not a measurement.

Which puts the **unread steady-yellow MIL** at the top. It was already the one
open item with real-world consequences; it may simply name this fault outright.

| | What it gives | Cost |
|---|---|---|
| **The DTC** | Possibly the answer, by name, in one minute. | A transport that transmits |
| **Polled** — OBD-II PID `0x2F` | What the PCM believes the level is, independent of the cluster. | Same transport |
| **Broadcast** — a CAN signal | What the cluster is actually being told. Settles the fork above. | A search that has never been attempted |

Read them in that order. The first two are ground truth for the third: a known
percentage, timestamped against a simultaneous passive capture, turns a blind diff
into the supervised correlation that produced engine speed and steering angle
(§3.2, "Method used").

### Two checks at the car that need no hardware at all

Both are free, and either could end this before any tooling is involved.

1. **The key dance** — ignition ON/OFF three times, ending ON, then read the EVIC.
   Documented across FCA vehicles of this era; **not confirmed for the KL**, so
   this is thirty seconds spent on a maybe.
2. **The cluster actuator self-test**, which sweeps every gauge and lights every
   telltale from the cluster's own memory. This is the *direct* test of the branch
   the blink argues against: if the fuel gauge sweeps full-scale correctly under
   self-test, the renderer is provably sound and the fault is upstream, in the
   sender or its wiring. It converts the inference above into a measurement, which
   is what §2.7 demands.

Also worth one look: is the gauge showing **a real zero** (bottom segment lit) or
**no valid reading** (segments blank, dashes)? On a digital dash these look alike
and mean opposite things — "a value of zero arrived" versus "nothing valid
arrived".

### What the vehicle's own hardware says about the likely fault

The KL has a **saddle-shaped fuel tank and therefore two level senders** — "A"
inside the pump module, "B" an auxiliary unit on the other side. The cluster
displays a single blended figure, so **one dead sender can pin the display**
without the tank being anywhere near empty.

On 2014–2015 Cherokee, **P2067** (sender B circuit low) is frequently a **PCM
software fault rather than a failed sender**, addressed by TSBs 18-085-17,
18-060-14, 18-035-16 and 18-007-15. That is a dealer reflash, not a pump module.
`dtc_descriptions.py` now carries P0460–P0464 and P2066–P2069 with that note, so a
read will say this rather than falling back to "fuel and air metering".

*Confidence: Candidate* throughout — this is community and parts-catalogue
research, not a measurement on this car, and it is recorded to direct the search,
not to pre-judge it.

### Stage 0 — before the dongle arrives (no hardware needed)

**Re-ordered 2026-09-16.** The gs_usb adapter's normal-mode hang no longer
reproduces (§2.6 addendum), so the dongle may no longer be on the critical path.
`diagnostics.py --transport gsusb` and `obd_probe.py` both already work through
`canbus.Bus` and are ready to try. **Try them at the car before spending time on
the items below** — a single decoded response settles a question no amount of desk
work can, and a single refusal costs one minute.

1. **Give `obd_probe.py` the ELM327 transport.** It imports `canbus.Bus`
   directly (`obd_probe.py:31`) and has no `--transport` flag, so it is still
   welded to the gs_usb adapter. `Elm327Transport` and `GsUsbTransport`
   already expose an identical `request()`, so this is a constructor swap plus
   the `--port` / `--baud` flags `diagnostics.py` already has. Now a fallback
   rather than a blocker.
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
2. **Run `slow_signal_candidates.py` first** — it already narrows this from 83
   identifiers to 4, using only the captures on disk, and needs no hardware:

   ```
   32 identifiers frozen within every capture
     28 identical between captures too   (dead ends — configuration, not measurement)
      4 different between captures       (candidates: 1EA, 4E2, 4E4, 659)
   ```

   The method is the point: a signal too slow to move inside one capture is
   indistinguishable from a constant, so the unit of observation has to change
   from the frame to the **session**. Frozen within, different between.

   Of the four, three differ only in `stationary-idle-36s` — one later session,
   so a single step tells you nothing about direction. **`0x659` is the one worth
   looking at**: byte 1's high nibble, 1 Hz, and it decreases monotonically
   through the August session, `0xF` → `0xE` → `0xD` over about forty minutes.
   It is the only quantity in all 83 identifiers that behaves that way.

   **The arithmetic argues against it being fuel**, and that is worth stating
   plainly rather than burying: 15 → 13 of 16 steps in forty minutes of idling
   implies roughly 8 litres burned, where real idle consumption is under one.
   Ambient temperature falling through a summer night, or battery voltage
   recovering, fit the shape better. *Confidence: Candidate*, and a weak one.

   Note the irony worth checking anyway: if `0x659` *is* fuel, `0xF` is full, and
   the fault would be in the cluster rather than the sender — the opposite of what
   the blinking telltale suggests.

3. `diff_captures.py` across them for the byte-level detail once a candidate is
   worth pursuing.
4. Expect several candidates to survive: odometer, trip counters, ambient
   temperature and battery voltage all drift between sessions too. Monotonicity
   against a known fill order is what separates fuel from those.
5. **If nothing on CAN-C tracks it**, that is informative rather than a failure —
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

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

### 2.6 NORMAL mode receives nothing; listen-only works perfectly

**The adapter can listen to this bus but cannot participate in it.**
*Confidence: Confirmed* — reproduced repeatedly, both modes back to back on the
same physical connection in a single process.

| Controller mode | Result |
|---|---|
| `LISTEN_ONLY` (silent) | **2,300+ frames/s, zero error frames, indefinitely** |
| `NORMAL` | **0 frames.** Not one, before any transmission is attempted |
| `NORMAL` + one OBD request to `0x7DF` | 0 frames, 0 responses |

The likely mechanism: in normal mode the controller must transmit an ACK bit for
every frame it receives. If it cannot assert a dominant bit that the other nodes
see, every reception is an error, the transmit error counter saturates within
milliseconds and the controller takes itself off the bus — which stops reception
too. Listening is passive and needs no ACK, so it is unaffected.

**Ruled out:**

- **Termination.** Tested in both R120 positions (`K` and `E`). Identical.
- **Software / library misuse.** Loopback mode passes: the controller's TX and RX
  paths both work, five frames sent and five received internally.
- **A permanently faulty adapter.** Loopback passes; listen-only captures
  2,300 frames/s reliably. The hardware works. An earlier version of this document
  attributed everything to the adapter latching bus-off, which was wrong — the
  mode split is deterministic and reproducible.
- **RX overflow.** Pausing reads for 5 s on a 2,300 frame/s bus, then resuming,
  loses nothing.

#### One capture per USB re-enumeration

Separately from the mode split, and unresolved: **the adapter delivers exactly one
successful real-bus capture per USB replug.** The next invocation returns zero
frames whatever the mode.

What has been tested, all passing, none of which reproduces it:

- repeated opens within one process, with and without clean teardown
- repeated opens across separate processes, using loopback
- pausing reads for 5 s on a live 2,300 frame/s bus, then resuming
- a USB-level `reset()` in place of a physical replug — does **not** substitute

The distinguishing factor appears to be sustained high-rate traffic across a
process boundary, but that has not been isolated. *Confidence: the behaviour is
Confirmed; the cause is unknown.*

Practical rule: **replug before every real-bus capture.** Offline tools need no
adapter and can be re-run freely.

**Not yet tested** — the experiment that distinguishes the two remaining
explanations: whether normal mode receives a brief burst and *then* stops (joined,
then kicked off by ACK failures) or receives nothing from the very first
millisecond (never joined). `scratchpad/normal_mode_forensics.py` does this;
it has not been run.

**Consequence:** everything requiring transmission is blocked — polled OBD values,
DTC reads, DTC clears. Passive analysis is entirely unaffected and is where the
work should go meanwhile. For reading the check-engine code in the near term, a
consumer ELM327 dongle is the pragmatic route; it is a different transceiver and
is not subject to whatever this one is hitting.

### 2.7 Retracted: "the adapter wedges" — it does not

An earlier version of this document devoted a long section to an intermittent
adapter fault that latched bus-off, needed a USB replug, and allowed "exactly one
open per replug". **None of that is real.** §2.6 supersedes it entirely: the
adapter is healthy, and the behaviour is a clean deterministic split between
listen-only (works) and normal mode (does not).

The wrong conclusion is documented here because of how it was reached, which is
the transferable part.

**How it happened.** Six bitrate sweeps returned zero frames. From that a theory
was built — FCA's isolated Diagnostic CAN-C carries no broadcast traffic — and it
was supported by genuine research and by a real 3.6 MΩ open-circuit reading. It
was wrong. Every one of those sweeps was a normal-mode run. The first listen-only
capture produced 2,300 frames/s immediately.

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
| `diagnostics.py` | yes | Fault codes (stored / pending / permanent), MIL state, freeze frame, VIN, supported PIDs. Optional gated DTC clear. |
| `dash_passive.py` | **no** | **Live dashboard, listen-only.** Decoded signals with confidence marks, bus health (CRC failures, rolling-counter gaps), and a "moving now" panel for discovery. Works today. |
| `dash.py` | yes | Polled OBD-II dashboard. **Blocked** by §2.6 — has never spoken to the car. |
| `diff_captures.py` | no | Diff two labelled captures: newly-varying bits **and** steady-state differences. Offline. |
| `correlate_signal.py` | no | Given one known **bit**, find every bit and byte that tracks it. Offline. |
| `correlate_analog.py` | no | Given one known **numeric field**, find every byte correlating with its value *or its rate of change*. Offline. |
| `canbus.py`, `obd.py`, `messages.py` | — | Shared plumbing. Not scripts. |

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
   here. Bitrate, wiring, polarity, termination and boot-switch position were all
   eliminated rigorously while the *controller mode* was never questioned, because
   it was not in the hypothesis space. When every measurement agrees and the
   conclusion is surprising, change something about the measuring apparatus before
   theorising about the system.

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
- **17 signals now decode**, cross-validated by replaying captures they were not
  derived from: brake reads all-zero during the revving capture, steering rate
  reads exactly 0 with the wheel parked, and `brake released?` sits at 100%.
- **Normal mode receives nothing; listen-only works perfectly.** §2.6

**Open**

- **Everything requiring transmission is blocked** by §2.6: polled OBD values,
  DTC reads, DTC clears. `dash.py`'s polled half, `diagnostics.py` and
  `obd_probe.py` are written and unit-checked but **have never spoken to the car**.
  A consumer ELM327 dongle is the pragmatic route to fault codes meanwhile.
- The distinguishing experiment for §2.6 has not been run:
  `scratchpad/normal_mode_forensics.py` records whether normal mode receives a
  brief burst then stops (joined, then kicked off by ACK failures) or nothing at
  all (never joined). That decides software-fixable vs different-hardware.
- **One capture per USB replug**, cause unknown. §2.6
- Steering angle **scaling** unresolved — 0.1°/LSB is the working hypothesis. §3.2
- Remaining captures for the differential campaign: **turn signal, headlights,
  gear selector**. Baseline, both brake captures, the steering sweep and the
  revving capture exist.
- **Pedal vs throttle-plate is unresolved** — the two copies are indistinguishable
  at this resolution. A slow, deliberate pedal ramp might separate them.
- **Nothing has been captured with the vehicle moving.** Wheel speeds, gear and
  the 37 idle-constant IDs need a drive. `0xC1CD000` (the extended ID) has never
  changed a bit.
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

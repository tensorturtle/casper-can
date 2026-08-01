# Jeep Cherokee KL — CAN Bus Notes

Basic CAN scanning of a **2016 Jeep Cherokee (KL)**, Mexico-market, personally
imported to Korea.

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
| Model year | 2016 |
| Market | Mexico, privately imported to Korea |
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
you looking for a fault that does not exist. See §4.

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

Pins 6/14 carry a **live broadcast bus at 500 kbit/s**, roughly 60 distinct
11-bit identifiers arriving at 1–20 Hz each, plus at least one 29-bit extended
identifier. *Confidence: Confirmed* — captured directly.

This **overturns** the "Diagnostic CAN-C, request/response only" theory that an
earlier version of this document recorded as the leading explanation. That theory
was constructed to explain zero received frames. The frames were absent because
**the adapter was faulty**, not because the bus was quiet. See §2.6 — it is the
more important finding of the two.

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
- **A wedged or faulty adapter.** An earlier version of this document attributed
  all of this to the adapter latching bus-off and needing a USB replug. **That was
  wrong.** The apparent "works once per replug" pattern was an artefact of
  listen-only and normal-mode runs happening to alternate. Repeated plain opens,
  across processes, with and without clean teardown, with and without a USB
  reset — all pass. There is no wedge.
- **RX overflow.** Pausing reads for 5 s on a 2,300 frame/s bus, then resuming,
  loses nothing.

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

Implemented as `crc8_j1850()` and `check_integrity()` in `canbus.py`, with the
protected-ID set as `PROTECTED_IDS`.

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

| ID | Rate | Content |
|---|---|---|
| `0x4EC` | 10 Hz | **VIN, as ASCII in three multiplexed parts.** Byte 0 is the part index (`00`, `01`, `02`); bytes 1–7 are ASCII characters. Reassembles to `1C4PJLDB3FW689935`. *Confirmed.* |

That is the only ID decoded so far. Everything else needs differential capture —
see §6.

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
| `dash.py` | yes | Live dashboard: polled OBD-II values plus passive broadcast health with live CRC validation. |
| `canbus.py`, `obd.py` | — | Shared plumbing. Not scripts. |

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

No replug ritual is needed. Listen-only tools can be run back to back
indefinitely. If a listen-only tool returns zero frames, check the ignition and
the pigtail — not the adapter.

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
   broadcasts continuously at pins 6/14. If `listen_probe.py` returns zero frames
   with the ignition on, **suspect the adapter before the vehicle**: replug USB,
   confirm with `adapter_check.py`, then retry. This rule was briefly retracted
   mid-session on the strength of six silent bitrate sweeps. It was right; the
   instrument was broken. Retracting a correct rule to accommodate bad
   measurements is its own failure mode.

6. **A multimeter differential reading does not prove traffic.** 0.6 V across
   CAN-H/CAN-L was read as a DMM averaging a busy bus. An idle stub held at
   asymmetric bias looks identical. Only a decoded frame proves traffic.

7. **Meter probes in the connector can latch faults.** An airbag service warning
   appeared while probing pins with the ignition on — a probe tip bridging
   adjacent pins is enough. Measure at the adapter's terminal block rather than
   in the J1962 connector where practical, and prefer ignition off.

4. **Do not expect 60 Ω across pins 6/14.** See §2.

5. **Only one process may hold the USB adapter.** A second sees a silent bus,
   which on this vehicle is indistinguishable from a broken connection.

## 6. Safety

[`../docs/00-safety.md`](../docs/00-safety.md) applies in full. Additionally,
specific to this vehicle:

- **No SGW means writes are possible.** Nothing in this area transmits, and no
  tool here clears DTCs — deliberately. Do not add one.
- **Do not drive with warnings on the dash.** A steady yellow MIL is
  "investigate soon"; a flashing MIL is "stop".
- Insulate every unused pigtail conductor individually. Pin 16 (green/white) is
  **unswitched battery** and is the dangerous one.

## 7. Current state

**Established**

- CAN-C wiring confirmed end-to-end, including a pin-16 orientation check. §2.
- **CAN-C is live and broadcasting at 500 kbit/s on pins 6/14.** ~60 11-bit IDs
  at 1–20 Hz, plus at least one 29-bit extended ID. §2.5
- **Normal mode receives nothing; listen-only works perfectly.** §2.6

**Open**

- **Everything requiring transmission is blocked** by §2.6: polled OBD values,
  DTC reads, DTC clears. `dash.py`'s polled half, `diagnostics.py` and
  `obd_probe.py` are written and unit-checked but have never spoken to the car.
- The distinguishing experiment for §2.6 has not been run:
  `scratchpad/normal_mode_forensics.py` records whether normal mode receives a
  brief burst then stops (joined, then kicked off) or nothing at all (never
  joined).
- `listen_probe.py` formats extended (29-bit) IDs poorly — one appeared as
  `C1CD000`. Needs an EFF-aware column.
- No ID has been identified yet. Next step is diffing an idle capture against
  captures with a specific input changed (steering, brake, throttle).
- CAN-IHS on pins 3/11 unverified — **measure pin 3 before connecting.** §2.3
- Outstanding dash items: change engine oil (maintenance reminder), license plate
  light out (a real bulb), and a **steady yellow check-engine light** whose code
  has not been read. Whether the MIL predates this session is unresolved.
- No OBD-II request has ever been successfully answered — every attempt was made
  with the faulty adapter, so `obd_probe.py` is written but untested.

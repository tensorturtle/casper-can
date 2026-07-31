# 07 — Signal Discovery Methodology

Prescriptive guidance for locating an undocumented signal on this vehicle. Every
rule below is derived from a technique that produced a wrong answer on this
vehicle before it was corrected.

---

## 1. Technique selection

Three techniques are available, in ascending order of evidential strength.
**Choose by what you know about the target, not by convenience.**

| # | Technique | Use when | Strength |
|---|---|---|---|
| 1 | **Snapshot diff on a state change** | The signal is a hidden binary or discrete state not displayed as a number (door lock, AC compressor) | Weakest — requires control snapshots and round-trip validation |
| 2 | **Value search** | The value is displayed numerically somewhere in the vehicle and is large and high-resolution | Strong for large values, **actively misleading for small ones** |
| 3 | **Before/after diff across a drive** | The value can be made to change by a known amount | **Strongest** — prefer whenever applicable |

### 1.1 Why technique 3 dominates

Technique 3 asks *"what moved, and by how much?"* rather than *"does this number
appear?"* A field that advances by +14 while the vehicle travels 14 km is causal,
not coincidental. It also locates fields whose current value is unknown and which
therefore **cannot be searched for at all**.

Technique 3 confirmed the odometer increments, identified the fuel-quantity
field, and disproved a mis-attributed "mystery distance" field. Prefer it
whenever the value can be made to change.

```
uv run scripts/vehicle_info.py --snapshot before.json
#   ...drive...
uv run scripts/vehicle_info.py --snapshot after.json --like before.json
uv run scripts/vehicle_info.py --diff before.json after.json   # no adapter needed
```

`--like` makes the second snapshot a fast re-read of only the identifiers that
responded the first time.

---

## 2. Rules for snapshot diffing (technique 1)

### Rule 1 — Always take a control snapshot

Re-scan with **nothing changed** before trusting any diff. Some identifiers hold
live counters or timestamps that drift on their own and appear as false positives
otherwise.

### Rule 2 — Always round-trip

Return the vehicle to its original state and re-read. A candidate that does not
return to its original value is not a state flag.

**This rule is not optional.** Three separate candidates on this vehicle passed a
clean control test and then failed round-trip validation:

| Candidate | Module | Apparent behaviour | Round-trip result |
|---|---|---|---|
| AC compressor | HVAC `0x01A0` byte 31 | Clean single-byte change | Did not return to original |
| Parking brake | ABS/ESC `0xC101` byte 8 | `56` → `80`, control-stable | Read `100`, not `56` |
| Drive mode | TCM `0x01A0`/`0x01F2` byte 10 | `10` → `9`, control-stable | Read `9` again |

### Rule 3 — A short control test is not proof

All three failures above passed a control test taken *seconds* apart and failed
when re-checked *minutes* later. The likely explanation is **slow-drifting
counters or timestamps** operating on a timescale a back-to-back control snapshot
cannot detect.

Space control snapshots further apart in time — comparable to the interval over
which the real test will run.

### Rule 3a — Sample a distribution, never a single read

A single read per state cannot distinguish a state bit from a jittering one.
Read each state a few hundred times and compare the **set of values** the byte
takes. A real signal holds one value per state with the sets disjoint.

This retired two long-standing "Confirmed" entries in one session
([04 §6.1](04-signal-reference.md), [04 §6.3](04-signal-reference.md)). The
door-lock byte had been recorded as `134` locked / `135` unlocked from one
sample each; across ~730 samples per state, *both* states produce all four
values of `132`–`135`, and `134` is the most common reading in each. The diff
that found it was true and meaningless.

The same pass confirmed the A/C compressor byte properly — one value per state,
zero jitter, sets disjoint — so this is a test entries can pass.

Two corollaries:

- **Let the system settle.** Values are transient for a second or two after a
  change while actuators move. Sample after, not during.
- **Sample long, and late.** A byte that is stable for 184 samples can still be
  drifting on a slower timescale: [04 §6.6](04-signal-reference.md)'s byte 7
  was jitter-free in seven states, then wandered `5` → `4` → `3` over minutes
  in an untouched system. Stability within a window is not stability.

### Rule 3b — Prefer a value in a byte to the presence of a DID

[04 §6.3](04-signal-reference.md) encoded "climate off" as whether DID `0x0100`
answered at all. It does not survive: across ~450 probes in every climate
state, it answered every time.

Absence of a response can be produced by timing, a busy module or too short a
receive window — none of which is a state change. Presence is only evidence
when its absence has been demonstrated to be reproducible and caused by the
state you are testing.

### Rule 4 — Use a masked diff when the payload is noisy

A plain two-snapshot diff is insufficient where an identifier mixes state flags
with continuously-drifting sensor telemetry. The AC compressor signal was **not**
findable by plain diff for this reason.

**Masked-diff procedure:**

1. Take two control snapshots with nothing changed.
2. Build a per-byte **noise mask** — every byte that differs between the controls.
3. Perform the real before/after test.
4. Trust a byte only if it differs between the real states **and** is stable
   (unmasked) across the control pair.

This is what isolated the AC compressor flag from surrounding duct and
evaporator temperature telemetry.

### Rule 5 — Change one variable

The recirculation candidate ([04 §6.4](04-signal-reference.md)) remains
unconfirmed because the climate system's overall on/off state changed between the
two test legs. The signal may well be correct; the test was not clean.

### Rule 5a — Fields that always move together need a test that pins one

Steering torque ([04 §7.2](04-signal-reference.md)) tracked angle across left,
centre and right and was nearly filed as a redundant angle channel — because
holding the wheel against a lock loads both at once. Pushing the wheel *without
letting it turn* swung torque to ±700 at a constant 0.1°, and settled it.

When two fields correlate across every test you have run, that is evidence
about your tests. Find the manoeuvre that moves one and holds the other at zero.

### Rule 5b — Sweep stationary before searching in motion

The same signals were rated **Not located** after a 180 s drive log, then found
in one 4-second stationary capture. A drive moves speed, angle, torque and load
together, so every byte moves and none stands out; lock-to-lock exercises a
control's *entire* range with the rest of the car held still.

Reserve driving for signals that genuinely require motion.

---

## 3. Rules for value search (technique 2)

`vehicle_info.py --find-value N` searches every collected payload for a
big-endian encoding of `N` as 1, 2, 3 or 4 bytes at 1×, 10× and 0.1× scaling.
Several values may be given at once, optionally labelled:

```
uv run scripts/vehicle_info.py --find-value odo=8429.8 range=389
```

Pointed at a value read off the instrument cluster, it identifies the
identifier, byte offset, width and scaling in a single pass — with no state
change, no control snapshot, no round-trip and no drift problem. It located the
odometer immediately.

### Rule 6 — Magnitude and resolution are the evidence, not the match

**With a few hundred bytes of payload, small numbers appear by chance.** A single
byte holds any value 0–255 and proves nothing.

An early version of the confidence heuristic rated a 0.5 km trip-meter search
**HIGH** confidence on the reasoning that "0.5 has a decimal and matched few
locations". What it had matched was the single byte `5` inside `0xF18C` — an ECU
**serial number**. Another rated a 210-minute value against the MDPS's
**manufacturing date**.

Two corrections, both now implemented:

- **Static build-record identifiers (`0xF180`–`0xF1FF`) are excluded by default.**
  They contain arbitrary bytes and cannot hold live data. Override with
  `--include-ident`.
- **Magnitude is weighted.** Anything below ~100, or matching only 1-byte-wide
  fields, is rated LOW regardless of apparent precision.

### Rule 7 — Distinguish exact matches from truncating ones

A relative tolerance originally allowed `8429` to satisfy a search for `8429.8`
while being reported as a clean hit. Hits now carry their delta and an `exact`
flag, so a field that truncates is visibly distinguishable from one that matches
exactly.

---

## 4. General principles

### Rule 8 — Plausible magnitude is not evidence of meaning

A 3-byte value reading `16818` was recorded as a mystery **distance** field, and
"identify the other distance fields" was carried as an open task. It was never a
distance — it is the fuel-quantity field ([04 §4.2](04-signal-reference.md)),
where byte 3 is simply a zero high byte, so a 3-byte read at offset 3 returns the
same number.

The error arose from going looking for distances and consequently reading a fuel
field as one. **Confirm what a field is by making it move in a known way, not by
whether its value looks reasonable.**

### Rule 9 — Read the negative response code

A module returning nothing is not necessarily locked. Distinguish:

| NRC | Meaning |
|---|---|
| `0x31` `requestOutOfRange` | Identifier does not exist — keep searching |
| `0x33` `securityAccessDenied` | Genuinely protected — searching will not help |
| `0x7F` `serviceNotSupportedInActiveSession` | Would answer in an extended session |
| `0x11` `serviceNotSupported` | Service not implemented at all |

ABS/ESC was briefly assumed security-locked on the basis of empty responses; the
actual NRC was `0x31`. See [05 §5.1](05-diagnostics.md).

### Rule 10 — Benchmark at the settings the caller actually uses

An initial measurement of multi-PID batching reported a **57×** speed-up. Its
baseline used 3 retries and 0.8 s receive windows, which no real caller employs.
Measured at the settings `dash.py` actually uses, the honest figure is **2.32×**
([04 §5](04-signal-reference.md)).

### Rule 11 — Distinguish "not located" from "not present"

A bounded search that found nothing is evidence of absence only within the
bounds searched. This document set separates the two ratings deliberately, and
every "not located" entry in [04 §8](04-signal-reference.md) states the ranges
actually covered.

---

## 5. Failure modes that mimic each other

Several distinct faults present identically on this vehicle. Recognising them
saves considerable time.

| Observed | Possible causes |
|---|---|
| **Zero frames received** | Gateway does not broadcast (normal, expected); another process holds the adapter; ignition off; segment is CAN FD and invisible to a classic-CAN adapter |
| **No response to a request** | Request not padded to DLC=8; identifier does not exist; module requires an extended session; adapter held by another process |
| **Read hangs indefinitely** | Receive timeout specified as `0`, which `libusb` treats as *block forever* |
| **Module appears security-locked** | Valid identifiers not yet found — check the NRC |

Each is documented in full at [02 — Network Architecture](02-network-architecture.md).

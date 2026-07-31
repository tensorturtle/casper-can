# 04 — Signal Reference

Every signal located on the gateway-reachable segment, with its encoding,
verification basis and confidence rating.

---

## 1. Confidence scale

Every entry in this document carries one of the following ratings. They are
defined here and used consistently.

| Rating | Definition |
|---|---|
| **Confirmed** | Encoding verified by a round-trip state change or by independent cross-check against a second source. Safe to build on. |
| **Working** | Encoding is correct; a scaling constant or offset carries residual uncertainty. Usable with the stated caveat. |
| **Candidate** | Correlation observed and control-tested, but not round-trip validated. Do not build on. |
| **Not located** | Searched without success. The search was bounded — absence of evidence only. |
| **Not present** | Established absent by architecture, not merely unfound. |

Ratings are not decoration. Three separate signals that looked clean on a
single before/after diff failed round-trip validation; see
[07 — Methodology](07-methodology.md) for why, and treat **Candidate** as
genuinely unreliable.

---

## 2. Standard OBD-II — Mode 01 (SAE J1979)

Support determined by reading the Mode 01 support bitmaps (PIDs `0x00`, `0x20`,
`0x40`) rather than by probing individual PIDs.

**26 decodable PIDs are supported** on the ECM (`0x7E0`):

Engine load · coolant temperature · short and long-term fuel trim · intake
manifold absolute pressure · engine RPM · vehicle speed · timing advance ·
intake air temperature · throttle position · run time since engine start ·
distance travelled with MIL on · time run with MIL on · fuel rail gauge
pressure · fuel tank level · warm-ups since codes cleared · distance since codes
cleared · barometric pressure · control module voltage · absolute load value ·
commanded equivalence ratio · relative throttle position · absolute throttle
position B · ambient air temperature · accelerator pedal position D and E ·
commanded throttle actuator.

### 2.1 Notable absences

| PID | Name | Consequence |
|---|---|---|
| `0x10` | Mass Air Flow | Not fitted — this is a MAP-based speed-density engine |
| `0x5E` | Engine Fuel Rate | Not supported |

**There is no instantaneous fuel-flow signal on this vehicle.** Tools report
`null` for MAF-derived consumption rather than a fabricated `0.0`.

The iPhone app offers speed-density *estimates* of air flow, fuel rate, economy
and range, computed from RPM, MAP and intake temperature with an assumed
volumetric efficiency. They are labelled `(est.)` there and are **not
measurements** — they carry no confidence rating from §1 and must not be cited as
findings. See [iphone-app/README.md](../iphone-app/README.md#derived-metrics).

Fuel *consumption over a distance* is nevertheless obtainable — by differencing
the cluster's fuel-quantity field. See §4.2.

---

## 3. Maintenance and status values

Representative capture, stationary, engine idling, fully warmed:

| Value | Reading | Interpretation |
|---|---|---|
| Fuel tank level | 90.2 % | — |
| Control module voltage | 14.11 V | Alternator charging normally. A charging-health proxy, **not** a battery state-of-charge. |
| Coolant temperature | 90 °C | Fully warm |
| Ambient air temperature | 36 °C | — |
| Intake air temperature | 62 °C | Heat-soaked after 21 min stationary idling — not a fault |
| Barometric pressure | 100 kPa | — |
| Run time since start | 1297 s | — |
| Distance with MIL on | 0 km | Consistent with clean emissions state (doc 05) |
| Distance since codes cleared | 8224 km | Against a confirmed 8429 km odometer — codes cleared at ~205 km, i.e. at pre-delivery inspection |
| Warm-ups since codes cleared | 255 | Saturated at the single-byte maximum |

There is **no intelligent battery sensor** on this segment; no true
state-of-charge value exists to read.

---

## 4. Cluster (`0x7C6`) — odometer and fuel quantity

Both values live in a single DID. Byte offsets below are into the **data bytes**
— i.e. after stripping the `0x62` positive-response byte and the 2-byte DID echo
from the reassembled ISO-TP response.

```
7C6 : B002  =  E0 00 00 00 3F AE 00 20 ED 00 00 00
offset:        0  1  2  3  4  5  6  7  8  9 10 11
                           └fuel┘  └─odometer──┘
```

### 4.1 Odometer — **Confirmed**

| Attribute | Value |
|---|---|
| Module | Cluster `0x7C6` |
| Primary location | DID `0xB002`, offset **6**, 3 bytes big-endian |
| Mirror location | DID `0x0080`, offset **10**, same layout |
| Unit | 1 km (whole kilometres only) |

```
request     : 0x7C6 → 03 22 B0 02   (padded to DLC=8 with 0xAA)
odometer_km = payload[6] << 16 | payload[7] << 8 | payload[8]
```

**Verification** — before/after snapshot across a real 13 km drive:

| Source | Before | After | Delta |
|---|---|---|---|
| `0xB002` offset 6 | 8429 | 8443 | **+14** |
| `0x0080` offset 10 | 8429 | 8443 | **+14** |
| ECM distance since clear (Mode 01 `0x31`) | 8225 | 8238 | +13 |
| Speed-integrated distance | — | — | +12.9 |

The spread reconciles exactly. The true starting value was 8429.8 km, so
`floor(8429.8 + d) = 8443` requires `13.2 ≤ d < 14.2 km`. The two whole-km
counters began at different fractional offsets, hence the one-km difference, and
speed integration undercounts by 2–4 %.

A value search for the displayed 8429 returned exactly two hits, both the same
physical location (offset 6 width 3, and offset 7 width 2 — the same value read
without its zero high byte). No other DID in any scanned range encoded that
number.

**Resolution limit:** both fields store whole kilometres. The tenths digit shown
on the instrument cluster (`.8`) is not published to any readable DID.

### 4.2 Fuel quantity — **Working**

| Attribute | Value |
|---|---|
| Module | Cluster `0x7C6` |
| Location | DID `0xB002`, offset **4**, 2 bytes big-endian |
| Scaling | litres × 512 *(inferred — see caveats)* |

```
fuel_litres = ((payload[4] << 8) | payload[5]) / 512
```

**Verification** across a 13 km drive:

| | Raw | Litres | Mode 01 fuel level |
|---|---|---|---|
| Before | 16302 | 31.84 L | 88.6 % |
| After | 15791 | 30.84 L | 85.9 % |
| Delta | −511 | **−0.998 L** | −2.7 pp |

Four independent checks support the interpretation:

- Implied tank capacity at 88.6 % = **35.9 L**, against the Casper's ~36 L
  published capacity.
- Almost exactly **1.000 L** consumed over ~13 km (~13 km/L), against the
  instrument cluster's 12.3 km/L cumulative figure.
- A third reading: 30.34 L against a Mode 01 level of 84.7 % → 30.34/36 =
  84.3 %. Consistent.
- It accounts for a previously unexplained −516 count drop while the vehicle sat
  parked: one hour of idling at ~1.008 L. Realistic.

**Caveats — respect these when using the field:**

1. **Fuel sloshes.** Across one drive the reported percentage swung
   88.6 → 92.2 → 85.9 with tank attitude. Differencing over a substantial
   distance is sound; short trips are not.
2. **The 512 counts/litre scaling is inferred, not documented.** Falsifiable
   prediction: a full tank should read **~18,400** (36 × 512 = 18,432). This
   check has not yet been performed.
3. **A fourth data point disagrees.** A later idle reading of 30.84 L against a
   Mode 01 level of 90.2 % implies a **34.2 L** tank rather than ~35.9 L. Both
   sources also drifted *upward* while parked (30.34 → 30.84 L, 84.7 → 90.2 %),
   consistent with fuel settling after a drive combined with different damping
   in the cluster and the ECM.

The field is confidently **fuel quantity**. The 512 constant is a good working
figure carrying a few percent residual uncertainty. **Do not quote absolute
litres to two decimal places as though exact.**

### 4.3 Cluster fields confirmed static — **Not located**

Across 13 km and 27 minutes, these cluster DIDs did not change at all:
`0x0060`, `0x0070`, `0x0072`, `0x0073`, `0xB001`, `0xB003`.

Values searched for and not found anywhere: 389 km range-to-empty;
13,760 min / 229 h cumulative running time; 12.6 km since fill-up; 2.8 and
12.3 km/L economy figures; 84,298 (a tenths-resolution odometer).

**Assessment:** trip meters, range-to-empty, average economy and cumulative
running time appear to be computed inside the cluster's firmware and never
published to a readable DID. Nothing located anywhere tracks elapsed time.

---

## 5. Multi-PID Mode 01 batching — **Confirmed**

SAE J1979 permits multiple PIDs in a single Mode 01 request; one 8-byte frame
accommodates the PCI byte, the `0x01` mode byte, and **up to 6 PIDs**. Many ECUs
ignore everything past the first PID. **This ECM answers all of them.**

```
request : 06 01 0D 0C 11 04 49          speed, RPM, throttle, load, pedal
response: 41 0D 00 0C 0D 3A 11 21 04 4D 49 24
          └ 0x41, then <pid><data…> concatenated with no length markers
```

Two implementation requirements:

- The response exceeds 7 bytes, so it arrives as a multi-frame ISO-TP transfer
  and requires the flow-control path.
- Values are packed with **no delimiters**, so walking the response requires a
  per-PID data-length table (`canbus.PID_LENGTHS`). An unknown PID length means
  parsing must **stop**, not guess.

**Measured performance** at the settings `dash.py` actually uses (1 attempt,
short receive window), 30 iterations:

| Strategy | Time per group of 5 | Reliability |
|---|---|---|
| One request per PID | 50.3 ms | 150/150 |
| All 5 in one request | **21.7 ms** | 30/30 |

**2.32× faster.** The saving comes from eliminating USB round-trips, which
dominate the cost — roughly 0.5 ms of the total is actual CAN wire time.

Applied in `dash.py`, this took measured full-screen refresh from ~16 Hz to
**~34 Hz** and slow-row rotation from 1.3 s to 0.6 s. A fallback to individual
reads is retained, so a partial or refused multi-PID response cannot blank the
display.

---

## 6. Body and comfort signals

Located by snapshot-diff on `0x22` ReadDataByIdentifier scans. See
[07 — Methodology](07-methodology.md) for the technique and its failure modes.

### 6.1 Door lock state — **Not located** *(was Confirmed; refuted 2026-07-31)*

**This entry previously claimed a Confirmed door-lock bit. That claim was wrong
and has been withdrawn.** It is kept here rather than deleted because the way it
failed is the point.

The original claim: BCM `0x7D0` DID `0x0171`, bit 0, `134` locked / `135`
unlocked, "located in a single diff with no false positives."

The DID holds exactly **one** payload byte. Sampling it ~730 times in each
state, with the doors untouched throughout:

| Byte value | Locked | Unlocked |
|---|---|---|
| `132` | 14 | 55 |
| `133` | 239 | 235 |
| `134` | **395** | **429** |
| `135` | 80 | 6 |

Both states span all four values, and `134` — the documented *locked* value —
is the most common reading in **both**. The low two bits jitter continuously;
a single read cannot recover lock state. The original diff caught `134` in one
state and `135` in the other by chance.

The distributions are not identical (`135` is commoner locked, `132` commoner
unlocked), so a *statistical* signal may exist over many samples. That is not
something a dashboard can display, and it has not been tested against a control
for confounds. Treat lock state as **not located**.

See [07 Rule 3a](07-methodology.md) — the rule this produced.

### 6.2 Air-conditioning compressor — **Confirmed**

| Attribute | Value |
|---|---|
| Module | HVAC `0x7B3` |
| DID | `0x01A2` |
| Encoding | Byte offset 32, and bytes 37–39 |

| State | byte[32] | bytes[37:40] |
|---|---|---|
| On | `51` | `[1, 1, 1]` |
| Off | `3` | `[0, 0, 0]` |

Offsets are into the full reassembled response array, **including** the
`0x62 0x01 0xA2` header. Validated with a complete on → off → on round trip;
all bytes returned to their original values.

**Re-verified 2026-07-31 by distribution sampling** — the test that refuted
§6.1 — and it passes cleanly. Byte 32 held a *single* value in every settled
state, with no jitter at all:

| State | byte[32] | Samples |
|---|---|---|
| A/C on, AUTO off | `51` | 116 |
| A/C off | `3` | 126 |
| A/C on again | `51` | 125 |
| AUTO levels 1 / 2 / 3 | `51` | 184 each |
| Fan low and fan max, A/C off | `3` | 184 each |

Two things this establishes beyond the original round trip:

- It reads `51` with **AUTO off** and `3` with the fan at maximum, so it tracks
  the compressor itself — not the AUTO mode or the blower that share the panel.
- Immediately after a change the DID returns transient values for a second or
  two while the blend doors move. `canbus.read_hvac()` returns `None` for any
  unrecognised value rather than rounding it to on or off.

This is the only body signal displayed by `dash.py`.

**Warning:** the remaining bytes of this DID, and all of `0x01A0`, `0x01A1` and
`0x01A3`, are live sensor telemetry (duct and evaporator temperatures) that
drift continuously regardless of AC state. Do not treat any of them as a flag
without a control-tested diff. One candidate (`0x01A0` byte 31) looked
promising, failed round-trip validation, and was withdrawn.

### 6.3 Climate system fully off — **Not located** *(was Confirmed; refuted 2026-07-31)*

**Withdrawn.** The claim was that HVAC `0x7B3` DID `0x0100` responds *only* when
the climate panel's OFF button is engaged, making its presence the signal.

`0x0100` was probed continuously alongside `0x01A2` throughout the session, in
every climate state tested — A/C on, A/C off, AUTO at all three strengths, and
manual fan at minimum and maximum. **It responded to every single one of
roughly 450 probes.** It never once failed to answer, in any state.

The DID simply always exists. The original result — absent across 7 snapshots,
present across 2 — is not reproducible, and the caveat added later (that it
appeared once unexpectedly) was the first sign of this.

A presence test is a fragile form of evidence: absence can be caused by
timing, a busy module, or a short receive window, none of which is a state
change. Prefer a value in a byte.

### 6.4 Recirculation — **Candidate**

| Attribute | Value |
|---|---|
| Module | HVAC `0x7B3` |
| Encoding | `0x01A1` bytes 3, 5, 7, 9, 11, 13 and `0x01A2` byte 3 |
| Transition | `0` (outside air) → `255` (recirculation), all simultaneously |

Six-plus positions moving together in a clean binary `0x00`/`0xFF` pattern,
stable against a control snapshot, strongly suggests a genuine flag replicated
per zone or duct.

Round-trip back to outside air did not cleanly confirm — the bytes remained at
`255`. The likely explanation is a confound rather than a wrong signal: the
climate system's overall on/off state also changed between the two test legs
(evidenced by `0x0100` appearing and disappearing, §6.3), so this was not a
clean single-variable toggle. A clean re-test has not been performed.

### 6.5 Target temperature setpoint — **Candidate** (non-linear)

| Attribute | Value |
|---|---|
| Module | HVAC `0x7B3` |
| Encoding | DID `0x01A0`, bytes 54 and 56 |

Correlates with the setpoint and is stable against a control snapshot, but the
mapping is **not linear**:

| Displayed | Raw |
|---|---|
| 18.0 °C | `0` |
| 22.0 °C | `1` |
| 24.0 °C | `2` |

A linear fit from the first two points (`temp_C = raw × 2 + 20`) broke on the
third: 18 → 22 °C (+4 °C) advanced the raw value by 1, and 22 → 24 °C (+2 °C)
also advanced it by 1. This is consistent with known Hyundai/Kia HVAC behaviour,
where displayed temperature maps non-linearly to the internal value near the
range extremes (coarser steps, plus `LO`/`HI` maximum-cool and maximum-heat
modes). A complete lookup table would require testing every 0.5–1 °C step across
the full range.

### 6.6 AUTO mode — **Not located** *(byte 29 refuted 2026-07-31)*

The earlier candidate — `0x01A2` byte 29 moving `0` → `32` in AUTO — **does not
reproduce**. Byte 29 read `0` in all seven states sampled: A/C on, A/C off,
AUTO at levels 1, 2 and 3, and manual fan at minimum and maximum. The original
baseline was noted at the time as possibly confounded by washer and wiper
activity, which is the likely explanation.

**No byte distinguishes AUTO level 1 from 2 from 3.** Across 184 samples at
each level, only bytes 4, 8 and 18 differed, and those are continuous with
overlapping ranges — duct and evaporator temperatures responding to fan speed,
not a level field.

#### Byte 7 — a near-miss worth recording

Byte 7 (mirrored at 17) looked like a clean AUTO flag and is **not** one:

| State | byte 7 | Samples |
|---|---|---|
| AUTO level 1 / 2 / 3 | `7` | 184 each |
| A/C on, AUTO off | `6` | 125 |
| Manual fan **lowest** | `6` | 184 |
| Manual fan **maximum** | `6` | 184 |

That is ~1000 jitter-free samples, and it even survives the obvious confound —
AUTO changes fan speed, but byte 7 ignores fan speed entirely, reading `6` at
both extremes. On that evidence it was briefly recorded as Confirmed.

It then read `5` with the system switched fully off, and — **untouched, in that
same state** — drifted to `4`, then `3` over the following minutes. A state
field does not wander. It is more likely an analogue quantity (a temperature
settling after shutdown) that happens to sit at `6` and `7` while the system
runs.

`canbus.read_hvac()` returns byte 7 raw, as `auto_raw`, deliberately
uninterpreted. Re-testing it means watching it across a long *settled* period
in each state, not just at the moment of switching — see
[07 Rule 3a](07-methodology.md).

---

## 7. MDPS (`0x7D4`) — steering angle and torque

Both values live in a single DID. Byte offsets are into the **data bytes** —
after stripping the `0x62` positive-response byte and the 2-byte DID echo.

```
7D4 : 0101  =  7A 79 FF 92 FF 92 00 FF C3 00 00 03 03 01 2C 01
offset:        0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
                     └torque┘ └─angle─┘           └counter
```

```
request : 0x7D4 → 03 22 01 01   (padded to DLC=8 with 0xAA)
```

Read together by `canbus.read_steering()`; displayed live by `dash.py`.

### 7.1 Steering angle — **Confirmed**

| Attribute | Value |
|---|---|
| Module | MDPS `0x7D4` |
| Location | DID `0x0101`, offset **4**, 2 bytes signed big-endian |
| Scaling | 0.1 °/count |
| Sign | **Positive = left** |

```
angle_deg = s16(payload[4], payload[5]) / 10
```

**Verification** — stationary lock-to-lock sweep, engine running:

| Position | Raw bytes | Decoded |
|---|---|---|
| Straight ahead | `FF 92` … `FF FD` | −1.5 to −1.9° |
| Full left | `11 A3` | **+451.5°** |
| Full right | `EE 1E` | **−457.8°** |

Full lock is not a single fixed number: pushing hard against the right lock
read **−468.0°** against −457.8° when merely held, consistent with column
wind-up and tyre scrub. Treat ±450–470° as the lock region.

Four independent checks:

- **Symmetric about zero**, and centre reads within 2° of 0.0 with the wheels
  visibly straight. An earlier −11.0° baseline was simply a not-quite-straight
  wheel, not a sensor offset — it resolved to −1.5° once actually centred.
- **±457° is 2.5 turns lock-to-lock**, matching the car's steering spec. This
  independently fixes the 0.1 °/count scaling; no other plausible constant
  yields a sane lock angle.
- **Rock-steady while held** — 97 consecutive samples at a held lock all read
  −457.6°. It is a position, not a rate or an accumulator.
- **Monotonic ramp** across a continuous 0 → 450° sweep, with no wrap or
  discontinuity.

### 7.2 Steering torque — **Working**

| Attribute | Value |
|---|---|
| Module | MDPS `0x7D4` |
| Location | DID `0x0101`, offset **2**, 2 bytes signed big-endian |
| Scaling | Fixed-point, full scale **±10000** — physical unit not established |
| Sign | **Positive = right** (opposite to angle) |
| Saturates | Hard clamp at exactly ±10000 |

```
torque = s16(payload[2], payload[3])
```

**Verification** — push against the wheel *without letting it turn*:

| Action | Torque | Angle |
|---|---|---|
| At rest | −27 | 0.0° |
| Push left | −830 | 0.1° |
| Push right | **+630** | −2.4° |

The angle field does not move while torque swings cleanly either side of zero,
which is what separates the two. A firm ordinary turn sits around ±1800.

**Full scale — Confirmed at ±10000.** Pushing hard against either lock pegs the
field at exactly ±10000 and holds it there:

| Test | Raw | Samples pegged | Angle meanwhile |
|---|---|---|---|
| Hard push, left lock | `D8 F0` = −10000 | 186 / 186 | 457.4° |
| Hard push, right lock | `27 10` = +10000 | 201 / 201 | −468.0° |

Every sample sat on the limit exactly, in both directions, while the angle
field kept reading normally. A physical sensor limit produces a ragged
maximum; an exact symmetric round number is a **firmware clamp**, so ±10000 is
a defined full scale rather than the largest value that happened to occur.

**Caveats:**

1. **No Nm calibration.** A defined ±10000 full scale implies a fixed-point
   encoding rather than arbitrary counts, which narrows the possibilities — but
   nothing measured here establishes the constant. The obvious candidate,
   0.001 Nm/count giving ±10.00 Nm, is only a *plausible* range for a steering
   column and plausibility is not evidence
   ([07 Rule 8](07-methodology.md)). **Do not quote Nm.**
   *Falsifiable test:* apply a known force at a known radius from the wheel
   centre — a luggage scale on a spoke — and compare against the count.
2. **The sign convention is inverted relative to angle** — positive torque is
   rightward, positive angle is leftward. This was measured twice in both
   directions; it is not a transcription error.
3. Torque is loaded whenever the wheel is held against a lock, so an
   angle-only test **cannot** separate these two fields — see §7.3.

### 7.3 Why this was previously "Not located"

An earlier attempt scanned these DIDs during a moving drive and concluded only
that offset 14 (reported then as "byte 17", counting from the start of the full
response including the header) was an alive-counter. That remains correct —
offset 14 cycles continuously and encodes nothing.

The reason angle and torque were missed is instructive, and is recorded as a
rule in [07 — Methodology](07-methodology.md): the earlier test varied *driving
state*, which moves everything at once. A **stationary single-variable sweep**
made angle obvious in one capture. More importantly, holding the wheel against
a lock loads angle **and** torque simultaneously, which initially made the
torque field look like a redundant inverted angle channel. Only the
push-without-turning test — varying force while holding position constant —
separated them.

### 7.4 Bytes not identified

| Offset | Behaviour |
|---|---|
| 0, 1 | ~120–127, moved to 120/119 while held at a lock but unresponsive to a light push. Possibly motor current or assist level. **Not identified.** |
| 6, 7 | Track angle coarsely (centre `00 FF`, full left `00 F8`, full right `00 07`) but do not scale consistently against offset 4. **Not identified.** |
| 8 | Free-running alive-counter. |
| 9–13, 15 | Static across every test. |
| 14 | Alive-counter (the one found in the earlier drive log). |

---

## 8. Signals searched for and not located

| Signal | Rating | Search performed |
|---|---|---|
| **Window position** | Not located | BCM `0x7D0` full `0x0000`–`0x03FF` (9 responding DIDs, none changed); `0x770` `0x0100`–`0x01FF` (78 responding DIDs, none changed); `0x7D2` `0x0100`–`0x01FF` (2 DIDs appeared to change, but a control snapshot showed identical drift — live counters). Not yet tried: `0x796`, `0x7B7`, `0x7C6`, `0x7B3`, `0x7C4`, and wider ranges on `0x780` / `0x7A0` / `0x7F1`. |
| **Parking brake** | Not located | BCM `0x7D0` narrow and wide; cluster `0x7C6` `0x0000`–`0x03FF`, `0xB000`–`0xB0FF`, `0xC000`–`0xC0FF` — zero DIDs changed. ABS/ESC `0x7D1` returns zero DIDs in the default session, but with NRC `0x31` `requestOutOfRange` ("identifier does not exist") rather than `0x33` `securityAccessDenied` — the module is **not** read-locked; valid identifiers simply had not been found. In an extended session, `0x7D1` DID `0xC101` byte 8 moved `56` (released) → `80` (applied), stable against a control test, but **failed round-trip** (read `100` on re-release). Withdrawn. Not pursued further given repeated ABS warning-lamp exposure for a negative result. |
| **Drive mode (Normal/Sport)** | Not located | This vehicle has no Eco mode; traction modes (Snow/Mud/Sand) are a separate control and were not tested. TCM `0x7E1` DID `0x01A0` byte 10 and DID `0x01F2` byte 10 both moved `10` (Normal) → `9` (Sport), stable against a control snapshot, but **failed round-trip** (read `9` again on return to Normal). `0x7D2` showed no signal at all. Withdrawn. |
| **HDA engagement state** | Not located | Camera `0x7C4` DIDs `0x0101`/`0x0102`/`0x0103`/`0x0140` were **completely static** across a 180 s drive including three HDA engagement windows — likely calibration or configuration data, not live state. MDPS `0x7D4` DID `0x0101` carries live steering angle and torque — both now decoded, see §7 — but neither is an engagement flag, and the DID's only near-discrete byte (offset 14) is a rolling alive-counter unrelated to HDA timing. Only `0x0100`–`0x01FF` was scanned on both modules. |
| **Front/rear demist, ionizer, seat heating/cooling** | Not located | Not yet tested. The control-masked diff of §6.2 should apply. |
| **Service-interval countdown** | Not located | Not yet searched against the cluster menu display. |
| **Media / volume** | **Not present** | Tested with CarPlay connected and audio playing, volume 20 → 25. Zero signal across `0x780`, `0x796` (narrow and wide ranges), `0x7B7`, `0x7C6`, `0x7F1`. No module on this segment corresponds to media control. See [02 §3](02-network-architecture.md) — the head unit is not bridged to this gateway. |
| **Per-wheel tyre pressure** | **Not present** | No TPMS module answers in `0x700`–`0x7FF`. Consistent with indirect ABS-derived TPMS, which holds no pressure value. |
| **Last-parked position** | **Not present** | A Bluelink cloud feature computed by the telematics unit, not a CAN value. Not obtainable from the diagnostic connector at any effort. |
| **Instantaneous fuel flow** | **Not present** | No MAF, no fuel-rate PID. See §2.1. |

**"Not located" is a bounded negative result.** Each entry states the ranges
actually scanned; none should be read as proof the signal does not exist.

---

## 9. Connected-app feature coverage

How much of what the manufacturer's phone application displays is obtainable
from the diagnostic connector:

| App feature | Status | Basis |
|---|---|---|
| Odometer | **Available** | Cluster `0xB002` / `0x0080` — §4.1 |
| Fuel level / quantity | **Available** | Cluster `0xB002` §4.2, plus Mode 01 percentage |
| Trip fuel economy | **Derivable** | Fuel delta ÷ odometer delta over a drive — §4.2 |
| Battery status | Partial | Control module voltage is a charging-health proxy; no true state-of-charge exists on this segment |
| Distance driven / service intervals | Partial | Distance since codes cleared is available; service countdowns not located |
| Tyre pressures | Not present | §7 |
| Last-parked position | Not present | §7 |

# 06 — ADAS Access and openpilot Compatibility

Assessment of what the openpilot objective requires, what has been established,
and what remains.

---

## 1. Objective

openpilot lateral and longitudinal control on a Hyundai/Kia platform requires
the ability to **observe and inject periodic messages** on the segment shared by
the forward-facing camera, MDPS and ABS/ESC — LKAS command frames, SCC status,
steering torque and camera output, typically at 50–100 Hz.

## 2. Established: the required messages are not at the diagnostic connector

**This is a hard architectural limit, not an unfinished search.**

| Finding | Status |
|---|---|
| Camera (`0x7C4`), MDPS (`0x7D4`) and ABS/ESC (`0x7D1`) are individually reachable for diagnostic request/response through the gateway | Established |
| Their **periodic broadcast messages** are absent from this segment under every tested condition | Established |
| No amount of driving or subsystem activation produces passive traffic here | Established — see [02 §1.1](02-network-architecture.md) |

The distinction matters and is easy to conflate. **Diagnostic reachability of a
module is not access to its network.** The gateway relays addressed
request/response transactions; it does not relay the continuous messaging those
modules exchange among themselves.

Active polling was also tested as an alternative to broadcast capture, on the
hypothesis that HDA engagement might be readable as discrete state in the manner
of door lock or AC compressor. Result: inconclusive — camera DIDs were entirely
static across three HDA engagement windows, and the only near-discrete MDPS byte
proved to be an alive-counter. See [04 §8](04-signal-reference.md). Only the
`0x0100`–`0x01FF` range was scanned, so this remains a bounded negative.

**Steering angle and torque are, however, now readable** by polling MDPS
`0x7D4` DID `0x0101` — see [04 §7](04-signal-reference.md). This does not change
the conclusion above, and the distinction is worth stating precisely, because
these are exactly the signals an openpilot port needs:

- Polled request/response reaches roughly **20 Hz**, against the **50–100 Hz**
  the ADAS segment carries natively. Adequate for observation and logging; not
  a control-loop rate.
- It is *reading* the MDPS, not participating in the LKAS conversation. Nothing
  here provides the steering **command** frames, which is what a port must
  inject.

So the value is diagnostic: steering angle can now be logged and correlated
against speed and HDA behaviour during a drive without a physical tap. The tap
is still required for a port.

**Conclusion: a physical tap on the ADAS segment is required.** The conventional
point for Hyundai/Kia is the connector at the forward-facing camera behind the
rear-view mirror.

## 3. Established: module identification, without disassembly

The three modules most relevant to openpilot are fully identified through the
diagnostic connector, including the camera's software version — normally the
information a compatibility discussion turns on.

| Module | Address | Part number | Software |
|---|---|---|---|
| Front camera (LKAS) | `0x7C4` | `99211-O6000` | HW `1.00`, **SW `1.03`** |
| MDPS | `0x7D4` | `56340-O6000` | — |
| ABS/ESC | `0x7D1` | `58900-O6810` | — |

Serial `240301M010258` on the camera encodes a 2024-03-01 build, matching the
vehicle's build month. Full build record in [03 §3](03-ecu-inventory.md).

## 4. Harness identification — **Candidate: Hyundai A**

The Casper (and the closely related Inster) is **not listed by model** in comma's
[Hyundai/Kia/Genesis harness reference](https://github.com/commaai/openpilot/wiki/Hyundai-Kia-Genesis/),
so no harness letter is assigned to it by name. The reference deliberately
identifies by connector rather than by model:

> "It's important to look where the notches are on your plug side, and ensure
> they match correctly."

The guide lists 18 variants (A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q,
R — J shares a Toyota housing) with notch-pattern photographs and wiring PDFs.
One missing wire relative to a listed variant is acceptable per the guide.

### 4.1 Assessment

**Visual inspection of the vehicle's connector indicates harness A is the most
likely match.** Two facts support this:

| Supporting fact | Weight |
|---|---|
| Connector appearance matches the reference image for Hyundai A | Primary — this is the guide's own definitive criterion |
| comma designates harness A for **non-HDA2** vehicles; this car is **HDA I** | Corroborating — consistent, and excludes the HDA2 variants |

The HDA-level agreement is genuine corroboration rather than restatement: HDA2
cars use a different camera connector and a different harness family, so a
non-HDA2 designation is a real constraint that this vehicle satisfies.

### 4.2 Not yet confirmed

This is a **visual match, not a verified one.** Before ordering hardware:

- Compare the notch pattern against the reference photograph directly and at the
  same orientation — notch position, not overall shape, is the discriminator.
- Check the Hyundai A wiring diagram (linked from the guide) against the actual
  connector, conductor by conductor. A single missing wire is tolerable; a
  mismatch in *which* wire is not.
- Confirm the connector inspected is the one at the forward-facing camera
  (`0x7C4`, part `99211-O6000`) behind the rear-view mirror, not another
  connector in the same area.

## 5. Prior art

No public opendbc or openpilot support exists for the Casper, and no
reverse-engineering write-up was located. Relevant channels:

- [`commaai/opendbc`](https://github.com/commaai/opendbc)
- openpilot Discord, `#dev-opendbc-cars`

The part numbers and software versions in §3 would be of direct value to that
discussion.

## 6. Required next steps, in order

1. **Confirm the harness as Hyundai A.** Visual inspection already points to A
   (§4.1). Remaining work is verification, not discovery: photograph the camera
   connector's notch pattern against the reference image at matching
   orientation, and check the Hyundai A wiring diagram conductor by conductor
   (§4.2). This is the gating step — nothing downstream can proceed until the
   connector is settled.
2. **Look up wiring diagrams** for `99211-O6000` (camera), `56340-O6000` (MDPS)
   and `58900-O6810` (ABS/ESC). A diagram may reveal a more accessible tap point
   than the camera housing itself.
3. **Tap the segment and capture.** Run `can_sniff.py` at the new tap point to
   determine its bit rate and confirm traffic exists. This is the tool's intended
   purpose — it returns zero frames at the diagnostic connector permanently, but
   is the correct instrument for a fresh, unknown segment.
4. **Exclude CAN FD before concluding silence.** If the new tap point also reads
   silent, this is **ambiguous**, not negative: the present adapter (STM32F072)
   is classic-CAN only and cannot see a CAN FD segment at all. CAN FD is
   increasingly common on newer Hyundai/Kia platforms. Repeat with an FD-capable
   adapter (comma panda, CANable 2.0) before drawing any conclusion. See
   [01 §4.1](01-physical-interface.md).
5. **Resolve `C1863-87`.** Determine whether the camera's "Missing Message" fault
   is pre-existing or self-inflicted, per the cold-start procedure in
   [05 §4.1](05-diagnostics.md). If pre-existing, a camera reporting an absent
   expected message is a real lead about the content of its own network.

## 7. Secondary investigations

Not on the critical path, but open:

- Wider DID scan on camera (`0x7C4`) and MDPS (`0x7D4`) for an HDA engagement
  flag — only `0x0100`–`0x01FF` has been covered.
- Take a journey log with HDA engaged over a window substantially longer than
  180 s, to test whether any polled camera or MDPS identifier correlates with
  engagement.

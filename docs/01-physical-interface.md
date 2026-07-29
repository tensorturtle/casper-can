# 01 — Physical Interface

Diagnostic connector wiring, bus electrical characteristics, adapter hardware,
and host software requirements.

---

## 1. Diagnostic connector pin assignment

The vehicle's OBD-II connector conforms to the standard SAE J1962 pin
assignment. The table below records the **verified** correspondence between
J1962 pins, the harness wire colours found on the vehicle-side pigtail, and
function. Verified by direct multimeter measurement on the pigtail.

| J1962 pin | Wire colour | Function | Verification |
|---|---|---|---|
| 6 | Green | CAN-H | ~2.5 V vs GND, ignition on |
| 14 | Brown / White | CAN-L | ~2.5 V vs GND, ignition on |
| 4 | Orange | Chassis ground | 0 V |
| 5 | Yellow | Signal ground | 0 V — interchangeable with pin 4 in practice |
| 16 | Green / White | Battery positive, unswitched | ~12 V ignition off, ~14 V ignition on |
| 3 | Red | Switched (ignition) power | 0 V ignition off, ~14 V ignition on |

All remaining pigtail conductors are unassigned for the purposes of this work
and should be **individually insulated** to prevent shorts against the
conductors in use.

### Reference material

`references/OBD-II-pigtail-wire.jpg` — the generic colour/pin chart used as the
starting hypothesis. The table above supersedes it for this vehicle.

## 2. Bus electrical characteristics

| Parameter | Value | Method |
|---|---|---|
| Topology | Twisted pair, differential | — |
| Termination | **60 Ω** across CAN-H / CAN-L | Measured with adapter disconnected, ignition off. Two 120 Ω terminators in parallel — a correctly terminated segment. |
| Recessive bias | ~2.5 V on both lines vs GND | Ignition on |
| Bit rate | **500 kbit/s** | Confirmed by successful request/response exchange |
| Protocol | Classic CAN 2.0A/B, 11-bit identifiers | — |
| Transport | ISO 15765-2 (ISO-TP) | Required for all payloads > 7 bytes |

## 3. Recommended minimum connection

Only three conductors are required:

```
Green        → adapter CAN_H
Brown/White  → adapter CAN_L
Orange       → adapter GND
```

The adapter is powered from the host's USB port. Pin 16 (Green/White) is
available as a ~12 V supply if host-independent power is required, but is not
used in this configuration.

## 4. Adapter hardware

**Jhoinrch RH-02** — see `references/USB-to-CANBUS-adapter-user-manual.jpg`.

| Attribute | Specification |
|---|---|
| Design lineage | Derived from the open-source [CANable](http://www.canable.io/) project |
| Firmware | **candleLight** (`gs_usb` protocol), factory default |
| Microcontroller | STM32F072C8T6 |
| Host interface | USB Type-A |
| Bus interface | 3-pin terminal block (CAN_H, CAN_L, GND) |
| Protocol support | CAN 2.0A/B up to 1 Mbit/s |
| **CAN FD** | **Not supported** — see limitation below |
| Boot switch | OFF = normal operating mode |

### 4.1 CAN FD limitation

The STM32F072 CAN peripheral implements classic CAN only. Any vehicle segment
operating at CAN FD is **invisible** to this adapter — it will report zero
frames, which is indistinguishable from a genuinely idle bus. This is material
to the work described in [06 — ADAS and openpilot](06-adas-openpilot.md): if a
future physical tap point also reads silent, CAN FD must be excluded before
concluding the segment is inactive. An FD-capable adapter (comma panda, CANable
2.0) is required to rule it out.

### 4.2 Apple Silicon compatibility

The adapter's printed manual states no compatibility with Apple Silicon
(M-series) macOS. **This applies only to the vendor's bundled GUI
application.** The underlying candleLight/`gs_usb` protocol is a userspace
`libusb` protocol requiring no kernel driver, and operates correctly on Apple
Silicon macOS via `python-can` / `gs_usb`. Confirmed operational, including live
USB device enumeration.

## 5. Host software requirements

| Requirement | Detail |
|---|---|
| Python | **3.14 or later** (all scripts declare `requires-python = ">=3.14"`) |
| Runner | [`uv`](https://github.com/astral-sh/uv) — PEP 723 inline dependencies, no virtual environment to manage |
| System library | `libusb` (`brew install libusb` on macOS) |
| Python packages | `python-can`, `gs_usb`, `pyusb`; `matplotlib` for `plot_journey.py` |

Invocation is uniformly:

```
uv run scripts/<name>.py
```

### 5.1 Known platform quirk — macOS kernel-driver detach

`gs_usb`'s `start()` unconditionally calls `detach_kernel_driver()` on
non-Windows platforms. On macOS, `libusb` permits this only as root, producing
an `Access denied` error for an unprivileged user.

**Resolution (no elevated privileges required):** patch
`usb.core.Device.is_kernel_driver_active` to return `False` before opening the
device. The device presents a vendor-specific USB interface with no claimed
serial or HID driver, so there is nothing to detach. Implemented in
`scripts/canbus.py` and `scripts/can_sniff.py`.

### 5.2 Interpreter version floor

A version floor is not a version selection. `uv` satisfies a floor with the
**oldest** qualifying interpreter available, so a `>=3.9` declaration silently
bound every script to macOS's system Python 3.9.6 despite 3.14 being installed.
The floor is declared at `>=3.14` for this reason. Verified on 3.14.3.

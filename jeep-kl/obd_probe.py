# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Ask the Jeep Cherokee KL which OBD-II PIDs it supports.

Superseded by `diagnostics.py`, which does this plus fault codes, freeze frames
and VIN. Kept because it is the minimal single-purpose request tool.

**Correction:** an earlier version of this docstring claimed the DLC carries no
broadcast traffic and that listening was futile. That was wrong. Pins 6/14 are a
live 500 kbit/s broadcast bus with 83 identifiers — see README §2.5. The apparent
silence was the adapter hanging on entry to normal mode (§2.6), not the gateway.

This sends standard OBD-II Service 01 PID 00 ("supported PIDs") to the
functional broadcast address 0x7DF and reports every ECU that answers.

Read-only. Sends only OBD-II Service 01 (current data) and Service 09 (vehicle
information) requests — no UDS, no session control, no writes, nothing that can
change vehicle state. Stationary use regardless; see ../docs/00-safety.md.

    uv run jeep-kl/obd_probe.py
    uv run jeep-kl/obd_probe.py --bitrate 125000     # try CAN-IHS pins 3/11
"""
import argparse
import time

from canbus import CAN_C_BITRATE, Bus

# Functional (broadcast) request address. Any emissions-related ECU may answer.
OBD_FUNCTIONAL_REQUEST = 0x7DF
# Physical response addresses. Responses never come from request_id + 8 when the
# request was functional — they arrive from this range, one ID per responding ECU.
OBD_RESPONSE_RANGE = range(0x7E8, 0x7F0)

# The four "supported PIDs" bitmap PIDs. Each reports support for the next 32.
SUPPORT_PIDS = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0]

PID_NAMES = {
    0x04: "calculated engine load",
    0x05: "coolant temperature",
    0x0B: "intake manifold pressure",
    0x0C: "engine RPM",
    0x0D: "vehicle speed",
    0x0E: "timing advance",
    0x0F: "intake air temperature",
    0x10: "MAF air flow rate",
    0x11: "throttle position",
    0x1F: "run time since engine start",
    0x21: "distance travelled with MIL on",
    0x2F: "fuel tank level",
    0x31: "distance since codes cleared",
    0x33: "absolute barometric pressure",
    0x42: "control module voltage",
    0x43: "absolute load value",
    0x45: "relative throttle position",
    0x46: "ambient air temperature",
    0x49: "accelerator pedal position D",
    0x4A: "accelerator pedal position E",
    0x5C: "engine oil temperature",
}


def request(bus, payload, window=1.0):
    """Send an OBD request functionally and collect single-frame answers.

    Returns {responder_id: response_bytes}. Multi-frame (ISO-TP) answers are
    not reassembled here — this tool only asks questions with short answers.
    """
    framed = [len(payload)] + list(payload)
    bus.send(OBD_FUNCTIONAL_REQUEST, framed)
    answers = {}
    end = time.time() + window
    while time.time() < end:
        aid, data = bus.read_one(timeout_ms=100)
        if aid is None or aid not in OBD_RESPONSE_RANGE or not data:
            continue
        pci = data[0] >> 4
        if pci == 0x0:  # single frame
            answers.setdefault(aid, data[1 : 1 + (data[0] & 0x0F)])
    return answers


def supported_pids(bus, responder_filter=None):
    """Walk the supported-PID bitmaps and return {responder_id: set(pids)}."""
    found = {}
    for base in SUPPORT_PIDS:
        answers = request(bus, [0x01, base])
        if not answers:
            break
        reached_end = True
        for aid, resp in answers.items():
            if responder_filter and aid != responder_filter:
                continue
            # Expect 41 <base> AA BB CC DD
            if len(resp) < 6 or resp[0] != 0x41 or resp[1] != base:
                continue
            bitmap = resp[2:6]
            pids = found.setdefault(aid, set())
            for byte_i, byte in enumerate(bitmap):
                for bit in range(8):
                    if byte & (0x80 >> bit):
                        pids.add(base + byte_i * 8 + bit + 1)
            # The last bit of the bitmap means "next range also supported".
            if bitmap[3] & 0x01:
                reached_end = False
        if reached_end:
            break
    return found


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE)
args = parser.parse_args()

print(f"requesting at {args.bitrate} bps — TRANSMITTING to 0x7DF (Service 01/09 only)")

# listen_only=False: this tool must transmit. That is the entire point.
with Bus(bitrate=args.bitrate, listen_only=False) as bus:
    print("\n[1] Service 01 PID 00 — supported PIDs")
    first = request(bus, [0x01, 0x00])
    if not first:
        raise SystemExit(
            "\nNo answer.\n"
            "  - confirm ignition is ON (engine running is fine)\n"
            "  - confirm CAN_H/CAN_L are not swapped at the terminal block\n"
            "  - this tool transmits, and the current adapter cannot enter normal\n"
            "    mode at all (README §2.6). That is almost certainly the cause,\n"
            "    and it is a hardware fault rather than anything about this car.\n"
            "  - confirm the bus is alive with: uv run jeep-kl/bus_analysis.py\n"
            "  - try --bitrate 125000 for CAN-IHS"
        )

    for aid, resp in sorted(first.items()):
        print(f"  responder 0x{aid:03X}: {bytes(resp).hex(' ')}")

    print("\n[2] walking all supported-PID ranges")
    table = supported_pids(bus)
    for aid, pids in sorted(table.items()):
        print(f"\n  ECU 0x{aid:03X} supports {len(pids)} PIDs:")
        for pid in sorted(pids):
            name = PID_NAMES.get(pid, "")
            print(f"    0x{pid:02X}  {name}")

    print("\n[3] Service 09 PID 00 — supported vehicle-info PIDs")
    info = request(bus, [0x09, 0x00])
    for aid, resp in sorted(info.items()):
        print(f"  responder 0x{aid:03X}: {bytes(resp).hex(' ')}")
    if not info:
        print("  (no answer — Service 09 may be unsupported)")

print("\nDone. Nothing was written to the vehicle.")

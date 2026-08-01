# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
#     "pyserial",
# ]
# ///
"""Read the Jeep Cherokee KL's fault codes, and optionally clear them.

Reading is the default and is entirely read-only. Clearing requires two explicit
flags and cannot run unless a report was written first.

    uv run jeep-kl/diagnostics.py --list-ports
    uv run jeep-kl/diagnostics.py --port /dev/tty.usbserial-XXXX
    uv run jeep-kl/diagnostics.py --port ... --clear --i-understand
    uv run jeep-kl/diagnostics.py --transport gsusb        # blocked, see below

## Which transport

**Use `elm327` (the default).** The gs_usb adapter cannot transmit on this vehicle
at all — normal mode receives nothing (README §2.6) — so `--transport gsusb` will
fail here for reasons that have nothing to do with this file. An ELM327 dongle is
a different transceiver and is not subject to that problem.

The two transports are interface-compatible, so if the gs_usb problem is ever
solved this tool works over it unchanged.

## Why clearing is gated

`../CLAUDE.md` states that no tool in this repository clears DTCs, deliberately.
That rule is scoped to the Casper work, where the codes *are* the research data.
This tool exists because the owner asked for it for this vehicle, for ordinary
maintenance rather than research.

The reasons to be careful are real:

- **Clearing erases evidence.** The stored codes are the only record of what set
  the MIL, and of the lost-communication faults from the debugging session
  (README §2.7). Once cleared they are gone.
- **Clearing resets readiness monitors.** Service 04 wipes I/M readiness along
  with the codes. The vehicle reports "not ready" until a full drive cycle
  completes, and an emissions inspection in that window fails automatically.
- **Clearing fixes nothing.** If the fault is present the MIL returns. A code that
  comes straight back is information; a code cleared and forgotten is a fault you
  now know nothing about.
- **Permanent DTCs (Service 0A) cannot be cleared** by Service 04 at all. They
  clear only after the vehicle's own monitors pass.

## Safety

`../docs/00-safety.md` applies. This sends only OBD-II emissions services
(01, 02, 03, 04, 07, 09, 0A). Never UDS, never a non-default diagnostic session,
never anything addressed at ABS/ESC (0x7D1) or MDPS (0x7D4). Stationary only.
"""
import argparse
import json

from capture_io import resolve_capture_path
from dtc_descriptions import describe, mil_advice
from obd import (
    ECM_RESPONSE,
    FUNCTIONAL_REQUEST,
    SVC_CLEAR_DTC,
    SVC_PENDING_DTC,
    SVC_PERMANENT_DTC,
    SVC_STORED_DTC,
    negative_response,
    read_dtcs,
    read_status,
    read_vin,
    supported_pids,
)

parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--transport", choices=("elm327", "gsusb"), default="elm327",
                    help="elm327 (default) or gsusb (blocked on this vehicle)")
parser.add_argument("--port", help="serial port for the ELM327 dongle")
parser.add_argument("--baud", type=int, default=38400,
                    help="ELM327 baud rate (38400 and 115200 are both common)")
parser.add_argument("--bitrate", type=int, default=500000, help="gsusb only")
parser.add_argument("--out", default="captures/dtc-report.json")
parser.add_argument("--clear", action="store_true",
                    help="clear stored DTCs after reading (requires --i-understand)")
parser.add_argument("--i-understand", action="store_true",
                    help="confirm you have read the warnings about clearing")
parser.add_argument("--list-ports", action="store_true",
                    help="list serial ports and exit")
parser.add_argument("--verbose", action="store_true", help="log dongle traffic")
args = parser.parse_args()

if args.list_ports:
    try:
        from serial.tools import list_ports
    except ImportError:
        raise SystemExit("pyserial not available — run via `uv run`.")
    ports = list(list_ports.comports())
    if not ports:
        raise SystemExit("No serial ports found. Is the dongle plugged in or paired?")
    print("serial ports:")
    for p in ports:
        print(f"  {p.device:<30} {p.description}")
    print("\nELM327 dongles usually appear as usbserial, wchusbserial, or a\n"
          "Bluetooth-incoming port. Pass one with --port.")
    raise SystemExit(0)

if args.clear and not args.i_understand:
    raise SystemExit(
        "Refusing to clear.\n\n"
        "Clearing erases the only record of what set the MIL, resets I/M readiness\n"
        "monitors (an emissions test will fail until a full drive cycle completes),\n"
        "and fixes nothing. Permanent DTCs will not clear regardless.\n\n"
        "Read the header of this file, then pass --i-understand as well."
    )

out_path = resolve_capture_path(args.out, __file__)

NO_ANSWER = (
    "The vehicle did not answer.\n\n"
    "  - ignition on? (the engine need not be running)\n"
    "  - dongle fully seated in the OBD-II port?\n"
    "  - if --transport gsusb: that transport cannot transmit on this vehicle\n"
    "    at all (README §2.6). Use the default elm327 transport.\n"
)


def open_transport():
    if args.transport == "elm327":
        if not args.port:
            raise SystemExit(
                "--port is required for the ELM327 transport.\n"
                "Run with --list-ports to see what is available."
            )
        from elm327 import Elm327Error, Elm327Transport
        try:
            return Elm327Transport(args.port, baudrate=args.baud,
                                   verbose=args.verbose)
        except Elm327Error as exc:
            raise SystemExit(f"ELM327 setup failed: {exc}")
        except Exception as exc:
            raise SystemExit(
                f"Could not open {args.port}: {exc}\n"
                f"Try --list-ports, and --baud 115200 if 38400 fails."
            )
    from canbus import Bus
    from obd import GsUsbTransport
    return GsUsbTransport(Bus(bitrate=args.bitrate, listen_only=False))


report = {"transport": None, "vin": None, "status": None, "stored": {},
          "pending": {}, "permanent": {}, "freeze_frame": None,
          "supported_pids": [], "cleared": False}

tp = open_transport()
print(f"transport: {tp.describe()}")
report["transport"] = tp.describe()

try:
    status = read_status(tp)
    if status is None:
        raise SystemExit(NO_ANSWER)
    report["status"] = status

    print(f"\n{'=' * 70}")
    print("VEHICLE STATUS")
    print(f"{'=' * 70}")
    print(f"  MIL (check engine):  {'ON' if status['mil_on'] else 'off'}")
    print(f"  confirmed DTC count: {status['dtc_count']}")
    print(f"  PID 01 raw:          {status['raw']}")
    print(f"\n  {mil_advice(status['mil_on'], status['dtc_count'])}")

    vin = read_vin(tp)
    report["vin"] = vin
    print(f"\n  VIN: {vin or '(no answer)'}")
    if vin and len(vin) >= 11:
        years = {"E": 2014, "F": 2015, "G": 2016, "H": 2017, "J": 2018}
        print(f"  model year (VIN position 10 = '{vin[9]}'): "
              f"{years.get(vin[9], 'unknown')}")

    for label, service, key in (
        ("STORED (confirmed — these command the MIL)", SVC_STORED_DTC, "stored"),
        ("PENDING (seen once, not yet confirmed)", SVC_PENDING_DTC, "pending"),
        ("PERMANENT (cannot be cleared by any tool)", SVC_PERMANENT_DTC, "permanent"),
    ):
        print(f"\n{'=' * 70}")
        print(f"{label}  — service 0x{service:02X}")
        print(f"{'=' * 70}")
        found = read_dtcs(tp, service, request_id=FUNCTIONAL_REQUEST)
        any_codes = False
        for aid, codes in sorted(found.items()):
            report[key][f"0x{aid:03X}"] = codes
            if not codes:
                continue
            any_codes = True
            print(f"  module 0x{aid:03X}:")
            for code in codes:
                desc, note = describe(code)
                print(f"    {code}  {desc}")
                if note:
                    print(f"           note: {note}")
        if not found:
            print("  (no module answered)")
        elif not any_codes:
            print("  none")

    first_stored = next((c for v in report["stored"].values() for c in v), None)
    if first_stored:
        print(f"\n{'=' * 70}")
        print("FREEZE FRAME — service 0x02, frame 0")
        print(f"{'=' * 70}")
        print("  Engine conditions recorded when the fault was first stored.")
        resp = tp.request([0x02, 0x02, 0x00])
        body = resp.get(ECM_RESPONSE) or next(iter(resp.values()), None)
        if body:
            report["freeze_frame"] = body.hex(" ")
            print(f"  raw: {body.hex(' ')}")
        else:
            print("  (no answer — freeze frames may not be supported)")

    print(f"\n{'=' * 70}")
    print("SUPPORTED SERVICE 01 PIDS")
    print(f"{'=' * 70}")
    supported = sorted(supported_pids(tp))
    report["supported_pids"] = [f"0x{p:02X}" for p in supported]
    print(f"  {len(supported)}: " + " ".join(f"{p:02X}" for p in supported))

    # Write BEFORE clearing. A clear that loses the record is worse than no clear.
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nreport saved: {out_path}")

    if args.clear:
        stored = [c for v in report["stored"].values() for c in v]
        perm = [c for v in report["permanent"].values() for c in v]
        print(f"\n{'=' * 70}")
        print("CLEARING — service 0x04")
        print(f"{'=' * 70}")
        if perm:
            print(f"  {len(perm)} permanent code(s) will NOT clear: "
                  + ", ".join(perm))
        if not stored:
            print("  Nothing stored to clear. Skipping — sending Service 04 anyway\n"
                  "  would reset readiness monitors for no benefit.")
        else:
            print(f"  clearing {len(stored)} stored code(s): " + ", ".join(stored))
            resp = tp.request([SVC_CLEAR_DTC], request_id=FUNCTIONAL_REQUEST,
                              window=2.0, expect_multiple=True)
            if not resp:
                print("  no acknowledgement — the clear may not have applied")
            for aid, body in sorted(resp.items()):
                nrc = negative_response(body)
                if nrc:
                    print(f"  module 0x{aid:03X}: REFUSED ({nrc})")
                elif body and body[0] == 0x44:
                    print(f"  module 0x{aid:03X}: cleared")
                else:
                    print(f"  module 0x{aid:03X}: unexpected {body.hex(' ')}")
            report["cleared"] = True
            out_path.write_text(json.dumps(report, indent=2))

            after = read_status(tp)
            if after:
                print(f"\n  MIL after clear: {'ON' if after['mil_on'] else 'off'}"
                      f"   stored count: {after['dtc_count']}")
                if after["mil_on"]:
                    print("  MIL still on — the fault is active. That is\n"
                          "  information, not a failure of the clear.")
            print("\n  Readiness monitors are now reset. Expect 'not ready' until a\n"
                  "  full drive cycle completes.")
finally:
    tp.close()

print("\nDone.")

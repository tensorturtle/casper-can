# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Read the Jeep Cherokee KL's fault codes, and optionally clear them.

Reading is the default and is entirely read-only. Clearing requires two explicit
flags and cannot run unless a report was successfully written first.

    uv run jeep-kl/diagnostics.py                        # read only
    uv run jeep-kl/diagnostics.py --clear --i-understand # read, save, then clear

## Why clearing is gated

`../CLAUDE.md` states that no tool in this repository clears DTCs, deliberately.
That rule is scoped to the Casper work, where the codes *are* the research data
and erasing them destroys the findings. This tool exists because the owner asked
for it for this vehicle, where the goal is ordinary car ownership rather than
reverse engineering.

The reasons to be careful are real and worth reading once:

- **Clearing erases evidence.** The stored codes are currently the only record of
  what caused the MIL, and of the lost-communication faults from the debugging
  session (README §2.7). Once cleared they are gone.
- **Clearing resets readiness monitors.** Service 04 wipes the I/M readiness
  status along with the codes. The vehicle will report "not ready" until it has
  completed a full drive cycle, and an emissions inspection during that window
  fails automatically.
- **Clearing does not fix anything.** If the underlying fault is present, the MIL
  returns. A code that comes straight back is diagnostic information; a code
  cleared and forgotten is a fault you now know nothing about.
- **Permanent DTCs (Service 0A) cannot be cleared** by Service 04 at all. They
  clear themselves only after the vehicle's own monitors pass. If a code appears
  under "permanent" it will survive this tool, by design of the standard.

## Safety

`../docs/00-safety.md` applies. This tool sends only OBD-II emissions services
(01, 02, 03, 04, 07, 09, 0A) to the standard addresses. It never sends UDS, never
addresses ABS/ESC (0x7D1) or MDPS (0x7D4) directly, and never enters a
non-default diagnostic session. Stationary use only.
"""
import argparse
import json
import sys
from pathlib import Path

from canbus import CAN_C_BITRATE, Bus
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
    request,
    supported_pids,
)

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--bitrate", type=int, default=CAN_C_BITRATE)
parser.add_argument("--out", default="captures/dtc-report.json")
parser.add_argument("--clear", action="store_true",
                    help="clear stored DTCs after reading (requires --i-understand)")
parser.add_argument("--i-understand", action="store_true",
                    help="confirm you have read the warnings about clearing")
args = parser.parse_args()

out_path = Path(args.out)
if not out_path.is_absolute():
    out_path = Path(__file__).resolve().parent / out_path
out_path.parent.mkdir(parents=True, exist_ok=True)

if args.clear and not args.i_understand:
    raise SystemExit(
        "Refusing to clear.\n\n"
        "Clearing erases the only record of what set the MIL, resets I/M readiness\n"
        "monitors (an emissions test will fail until a full drive cycle completes),\n"
        "and fixes nothing. Permanent DTCs will not clear regardless.\n\n"
        "Read the header of this file, then pass --i-understand as well."
    )

report = {"vin": None, "status": None, "stored": {}, "pending": {},
          "permanent": {}, "freeze_frame": None, "cleared": False}

print("connecting…")
with Bus(bitrate=args.bitrate, listen_only=False) as bus:
    status = read_status(bus)
    if status is None:
        raise SystemExit(
            "The vehicle did not answer, and it may not be able to.\n\n"
            "This tool must TRANSMIT, which requires the controller in NORMAL\n"
            "mode -- and on this vehicle normal mode currently receives nothing\n"
            "at all (README §2.6). Listen-only tools work fine; transmitting ones\n"
            "are blocked pending that investigation.\n\n"
            "Check first:\n"
            "  - ignition on?\n"
            "  - pigtail seated?\n"
            "  - does `uv run jeep-kl/bus_analysis.py --seconds 5` see traffic?\n"
            "    If yes, the bus is fine and this is the normal-mode problem.\n"
            "For reading fault codes meanwhile, use a consumer ELM327 dongle.\n"
        )
    report["status"] = status

    print(f"\n{'=' * 66}")
    print("VEHICLE STATUS")
    print(f"{'=' * 66}")
    print(f"  MIL (check engine):  {'ON' if status['mil_on'] else 'off'}")
    print(f"  confirmed DTC count: {status['dtc_count']}")
    print(f"  PID 01 raw:          {status['raw']}")

    vin = read_vin(bus)
    report["vin"] = vin
    print(f"  VIN:                 {vin or '(no answer)'}")
    if vin and len(vin) >= 10:
        year_map = {"E": 2014, "F": 2015, "G": 2016, "H": 2017, "J": 2018}
        print(f"  model year (VIN pos 10 '{vin[9]}'): "
              f"{year_map.get(vin[9], 'unknown')}")

    for label, service, key in (
        ("STORED (confirmed)", SVC_STORED_DTC, "stored"),
        ("PENDING (not yet confirmed)", SVC_PENDING_DTC, "pending"),
        ("PERMANENT (cannot be cleared)", SVC_PERMANENT_DTC, "permanent"),
    ):
        print(f"\n{'=' * 66}")
        print(f"{label}  — service 0x{service:02X}")
        print(f"{'=' * 66}")
        found = read_dtcs(bus, service, request_id=FUNCTIONAL_REQUEST)
        any_codes = False
        for aid, codes in sorted(found.items()):
            if codes:
                any_codes = True
                print(f"  module 0x{aid:03X}:")
                for code in codes:
                    print(f"    {code}")
            report[key][f"0x{aid:03X}"] = codes
        if not found:
            print("  (no module answered)")
        elif not any_codes:
            print("  none")

    # Freeze frame for the first stored code, if any.
    first_stored = next(
        (c for codes in report["stored"].values() for c in codes), None
    )
    if first_stored:
        print(f"\n{'=' * 66}")
        print("FREEZE FRAME — service 0x02, frame 0")
        print(f"{'=' * 66}")
        resp = request(bus, [0x02, 0x02, 0x00])
        body = resp.get(ECM_RESPONSE) or next(iter(resp.values()), None)
        if body:
            report["freeze_frame"] = body.hex(" ")
            print(f"  raw: {body.hex(' ')}")
        else:
            print("  (no answer)")

    print(f"\n{'=' * 66}")
    print("SUPPORTED SERVICE 01 PIDS")
    print(f"{'=' * 66}")
    supported = sorted(supported_pids(bus))
    report["supported_pids"] = [f"0x{p:02X}" for p in supported]
    print(f"  {len(supported)} PIDs: "
          + " ".join(f"{p:02X}" for p in supported))

    # Write the report BEFORE clearing. A clear that loses the record is worse
    # than no clear at all.
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nreport saved: {out_path}")

    if args.clear:
        all_codes = [c for codes in report["stored"].values() for c in codes]
        perm = [c for codes in report["permanent"].values() for c in codes]
        print(f"\n{'=' * 66}")
        print("CLEARING — service 0x04")
        print(f"{'=' * 66}")
        if perm:
            print(f"  note: {len(perm)} permanent code(s) will NOT clear: "
                  + ", ".join(perm))
        if not all_codes:
            print("  nothing stored to clear; sending anyway to reset readiness "
                  "monitors was NOT requested, so skipping.")
        else:
            print(f"  clearing {len(all_codes)} stored code(s): "
                  + ", ".join(all_codes))
            resp = request(bus, [SVC_CLEAR_DTC], request_id=FUNCTIONAL_REQUEST,
                           window=2.0, expect_multiple=True)
            if not resp:
                print("  no acknowledgement received — clear may not have applied")
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

            after = read_status(bus)
            if after:
                print(f"\n  MIL after clear: {'ON' if after['mil_on'] else 'off'}"
                      f"   stored count: {after['dtc_count']}")
                if after["mil_on"]:
                    print("  MIL still on — the underlying fault is active. "
                          "This is information, not a failure of the clear.")
            print("\n  Readiness monitors are now reset. Expect 'not ready' until a "
                  "full drive cycle completes.")

print("\nDone.")

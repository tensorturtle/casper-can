# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Full diagnostic trouble code (DTC) reader - what a shop scan tool shows you.

Three layers, all read-only:

  1. OBD-II emissions layer on the ECM: MIL ("check engine") lamp state and
     confirmed DTC count (Mode 01 PID 0x01), readiness monitors, then stored
     (Mode 03), pending (Mode 07) and permanent (Mode 0A) codes.
  2. UDS ReadDTCInformation (0x19 subfunction 0x02, "report DTC by status mask")
     against all 15 known ECUs - this is where chassis/body faults live, and
     it's the layer a generic $20 OBD dongle can't reach.
  3. UDS DTC count (0x19 subfunction 0x01) as a cross-check, since some ECUs
     answer the count but not the list.

Codes are decoded to standard `P0123` / `P0123-12` form, colour-coded by
severity, with their ISO 14229-1 status flags spelled out.

Severity is derived from the status flags, NOT from a code merely existing -
this car stores DTCs with no failure bits set at all, which are not faults:

  green  OK    no DTCs stored
  dim    INFO  stored, but no failure bit set (e.g. "test not completed")
  yellow WARN  confirmed or previously failed, but NOT currently failing
  red    FAIL  currently failing, or requesting a dashboard warning light

CRITICALLY: this script never sends DiagnosticSessionControl (0x10) or
ClearDiagnosticInformation (0x14). It cannot clear codes, and it does not
provoke the transient "Check ESC" light that session control causes on this
car (README Safety Note). Safe to run parked or driving; parked is still
preferable for a full sweep.

Usage:
  uv run scripts/read_dtcs.py
  uv run scripts/read_dtcs.py --detail      # + freeze-frame & occurrence counters
  uv run scripts/read_dtcs.py --no-color
"""
import argparse
import json
import os
import sys
import time

import canbus
from canbus import Bus, KNOWN_ECUS

REPORT_PATH = "dtc_report.json"

# Mode 01 PID 0x01: byte A bit 7 = MIL on, bits 0-6 = confirmed DTC count.
READINESS_TESTS = (
    "Misfire",
    "Fuel System",
    "Components",
    "(reserved)",
    "Catalyst",
    "Heated Catalyst",
    "Evap System",
    "Secondary Air",
    "A/C Refrigerant",
    "Oxygen Sensor",
    "O2 Sensor Heater",
    "EGR System",
)

# --- severity + colour ----------------------------------------------------

# (rank, label, symbol, ansi) - rank orders the overall verdict.
OK = (0, "OK", "+", "32")       # green
INFO = (1, "INFO", ".", "2")    # dim
WARN = (2, "WARN", "!", "33")   # yellow
FAIL = (3, "FAIL", "x", "31")   # red

_USE_COLOR = True


def init_color(no_color):
    """Honour --no-color, NO_COLOR, dumb terminals, and piped output."""
    global _USE_COLOR
    _USE_COLOR = (
        not no_color
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )


def paint(text, severity):
    if not _USE_COLOR:
        return text
    return f"\033[{severity[3]}m{text}\033[0m"


def tag(severity):
    """A coloured [SYMBOL LABEL] badge. Never colour alone - the label carries
    the meaning for colourblind readers, piped output and NO_COLOR."""
    return paint(f"[{severity[2]} {severity[1]:4s}]", severity)


def dtc_severity(status):
    """Map an ISO 14229-1 statusOfDTC byte onto a severity.

    A stored DTC is not automatically a problem. What matters is whether it is
    failing *now* (bits 0/1), or asking for a dash light (bit 7) -> FAIL;
    versus a latched history of failure (bits 3/5) that is not currently
    active -> WARN; versus no failure bit at all -> INFO.
    """
    if status & 0b10000011:  # testFailed | testFailedThisOpCycle | warningIndicator
        return FAIL
    if status & 0b00101000:  # confirmedDTC | testFailedSinceLastClear
        return WARN
    return INFO


def worst(severities):
    return max(severities, key=lambda s: s[0]) if severities else OK


# --- requests -------------------------------------------------------------

def read_mil_status(bus):
    """Mode 01 PID 0x01 - MIL lamp, DTC count, and readiness monitor status."""
    resp = bus.isotp_request(canbus.ECM_REQ, [0x01, 0x01], canbus.ECM_RESP, tries=3, window=0.8)
    if not resp or canbus.is_negative(resp) or len(resp) < 6 or resp[0] != 0x41:
        return None
    a, b, c, d = resp[2:6]
    monitors = []
    # Byte B bits 0-2 = the three continuous monitors; bits 4-6 their completeness.
    for i in range(3):
        if b & (1 << i):
            monitors.append((READINESS_TESTS[i], not (b & (1 << (i + 4)))))
    # Bytes C/D = non-continuous monitors: C bit n supported, D bit n incomplete.
    for i in range(8):
        if c & (1 << i):
            monitors.append((READINESS_TESTS[i + 4], not (d & (1 << i))))
    return {
        "mil_on": bool(a & 0x80),
        "dtc_count": a & 0x7F,
        "monitors": monitors,
    }


def read_obd_dtc_mode(bus, mode):
    resp = bus.isotp_request(canbus.ECM_REQ, [mode], canbus.ECM_RESP, tries=2, window=1.0)
    return canbus.parse_obd_dtcs(resp, 0x40 + mode), canbus.describe_response(resp)


def read_uds_dtcs(bus, req_id):
    """0x19 0x02 0xFF - report all DTCs by status mask, in the default session."""
    resp = bus.isotp_request(req_id, [0x19, 0x02, 0xFF], tries=2, window=1.2)
    return canbus.parse_uds_dtcs(resp), resp


def read_uds_dtc_count(bus, req_id):
    """0x19 0x01 0xFF - number of DTCs matching the mask.

    Response: 0x59 0x01 <availabilityMask> <formatIdentifier> <countHi> <countLo>
    """
    resp = bus.isotp_request(req_id, [0x19, 0x01, 0xFF], tries=2, window=1.0)
    if not resp or canbus.is_negative(resp) or len(resp) < 6 or resp[0] != 0x59:
        return None, resp
    return (resp[4] << 8) | resp[5], resp


def read_dtc_extended(bus, req_id, dtc):
    """0x19 0x06 - extended data records for one DTC (occurrence/aging counters).

    Record 0xFF requests all records. The per-record layout is ECU-specific,
    so the bytes are reported raw rather than guessed at.
    """
    return bus.isotp_request(
        req_id, [0x19, 0x06, dtc[0], dtc[1], dtc[2], 0xFF], tries=2, window=1.5
    )


def read_dtc_snapshot(bus, req_id, dtc):
    """0x19 0x04 - snapshot (freeze-frame) records captured when the DTC set."""
    return bus.isotp_request(
        req_id, [0x19, 0x04, dtc[0], dtc[1], dtc[2], 0xFF], tries=2, window=1.5
    )


def hexs(data, limit=32):
    if not data:
        return "(no response)"
    out = " ".join(f"{b:02X}" for b in data[:limit])
    return out + (" ..." if len(data) > limit else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detail", action="store_true",
                        help="also query freeze-frame (0x19 0x04) and extended "
                             "data / occurrence counters (0x19 0x06) per DTC")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()
    init_color(args.no_color)

    report = {"unix_time": time.time(), "obd": {}, "ecus": {}}
    severities = []

    with Bus() as bus:
        print("=" * 72)
        print("EMISSIONS / OBD-II LAYER (ECM 0x7E0)")
        print("=" * 72)

        mil = read_mil_status(bus)
        if mil is None:
            print(f"  {tag(WARN)} Mode 01 PID 0x01 gave no usable response "
                  f"(is the ignition on?)")
            severities.append(WARN)
        else:
            sev = FAIL if mil["mil_on"] else OK
            severities.append(sev)
            print(f"  {tag(sev)} MIL / check-engine lamp : "
                  f"{paint('ON' if mil['mil_on'] else 'off', sev)}")

            sev = WARN if mil["dtc_count"] else OK
            severities.append(sev)
            print(f"  {tag(sev)} Confirmed DTC count     : {mil['dtc_count']}")

            print("  Readiness monitors:")
            for name, complete in mil["monitors"]:
                sev = OK if complete else WARN
                severities.append(sev)
                print(f"    {tag(sev)} {name:22s} "
                      f"{paint('complete' if complete else 'NOT complete', sev)}")
            report["obd"]["mil"] = {
                "mil_on": mil["mil_on"],
                "dtc_count": mil["dtc_count"],
                "monitors": {n: c for n, c in mil["monitors"]},
            }

        print()
        for mode, label, sev_if_found in (
            (0x03, "Stored/confirmed", FAIL),
            (0x07, "Pending", WARN),
            (0x0A, "Permanent", FAIL),
        ):
            codes, raw = read_obd_dtc_mode(bus, mode)
            sev = sev_if_found if codes else OK
            severities.append(sev)
            detail = paint(", ".join(codes), sev) if codes else paint("none", OK)
            print(f"  {tag(sev)} {label:18s} (Mode {mode:02X}): {detail}")
            report["obd"][label.lower().split("/")[0]] = codes

        print()
        print("=" * 72)
        print("UDS LAYER - ReadDTCInformation across all known ECUs")
        print("=" * 72)

        total_faults = 0
        for req_id in sorted(KNOWN_ECUS):
            label, part = KNOWN_ECUS[req_id]
            header = f"0x{req_id:03X} {label}" + (f" [{part}]" if part else "")
            bus.drain()
            dtcs, raw = read_uds_dtcs(bus, req_id)
            count, count_raw = read_uds_dtc_count(bus, req_id)

            entry = {
                "label": label,
                "part": part,
                "dtcs": [
                    {"code": c, "status": s, "flags": canbus.describe_status(s),
                     "severity": dtc_severity(s)[1]}
                    for c, s, _ in dtcs
                ],
                "reported_count": count,
                "raw_list_response": raw,
                "raw_count_response": count_raw,
            }
            report["ecus"][f"0x{req_id:03X}"] = entry

            if dtcs:
                total_faults += len(dtcs)
                ecu_sev = worst([dtc_severity(s) for _, s, _ in dtcs])
                severities.append(ecu_sev)
                print(f"\n{tag(ecu_sev)} {header}")
                print(f"  {len(dtcs)} DTC(s):")
                for code, status, raw_dtc in dtcs:
                    sev = dtc_severity(status)
                    print(f"    {tag(sev)} {paint(code, sev):22s} "
                          f"status=0x{status:02X}  ({canbus.describe_status(status)})")
                    if args.detail:
                        ext = read_dtc_extended(bus, req_id, raw_dtc)
                        snap = read_dtc_snapshot(bus, req_id, raw_dtc)
                        # Layout past the 0x59/subfn/DTC/status header is
                        # ECU-specific, so report raw rather than mis-decode it.
                        print(f"          extended (0x19 06): {hexs(ext)}")
                        print(f"          snapshot (0x19 04): {hexs(snap)}")
                        entry["dtcs"][-1]["extended_raw"] = ext
                        entry["dtcs"][-1]["snapshot_raw"] = snap
            elif count:
                severities.append(WARN)
                print(f"\n{tag(WARN)} {header}")
                print(f"  reports {count} DTC(s) via count subfunction but "
                      f"returned no list")
                print(f"  raw list response: {canbus.describe_response(raw)}")
            elif raw and not canbus.is_negative(raw):
                severities.append(OK)
                print(f"{tag(OK)} {header:50s} {paint('no faults', OK)}")
            else:
                # Cannot report - not a clean bill of health, but not a fault.
                severities.append(INFO)
                print(f"{tag(INFO)} {header:50s} "
                      f"{paint(canbus.describe_response(raw), INFO)}")

        overall = worst(severities)
        print()
        print("=" * 72)
        print(f"OVERALL: {tag(overall)} {paint(overall[1], overall)}   "
              f"({total_faults} DTC(s) decoded across all ECUs)")
        if overall is OK:
            print("Everything queried reported healthy.")
        elif overall is INFO:
            print("No faults. Some ECUs cannot report DTCs in the default "
                  "session - see INFO lines.")
        elif overall is WARN:
            print("Stored/confirmed fault history present, but nothing is "
                  "currently failing and no warning light is requested.")
        else:
            print("Something is failing NOW or requesting a warning light - "
                  "see the FAIL lines above.")
        print("=" * 72)

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull raw + decoded report written to {REPORT_PATH}")
    print("Note: this tool cannot clear codes - that is deliberate.")


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Interactive UDS exploration CLI. READ-ONLY BY DESIGN.

Implements only: ECU discovery, ReadDataByIdentifier (0x22), ReadDTCInformation
(0x19), RequestRoutineResults (0x31 subfunction 0x03 - reads a routine's
result WITHOUT starting it), and a "services" probe that sends minimal/
malformed requests for common SIDs to see which are supported and whether
they're security-locked, via the negative-response code alone.

Deliberately NOT implemented: IOControlByIdentifier (0x2F) actuation,
RoutineControl start (0x31 subfunction 0x01), WriteDataByIdentifier (0x2E),
SecurityAccess key exchange (0x27 with a real seed/key attempt). If you type
raw bytes via the `raw` command that happen to trigger one of these, that's
on you - the built-in commands never do.

SAFETY: run this parked, in P, with parking brake + foot brake applied.
Never target ABS/ESC (0x7D1) or MDPS (0x7D4) with anything beyond `read`/
`dtc`/`services` - see README.md Safety Note about the "Check ESC" warning
triggered by Diagnostic Session Control on this car.

Usage: uv run scripts/uds_cli.py
Commands:
  list                          - show known ECUs
  scan                          - rescan 0x700-0x7FF for responding ECUs
  read <ecu> <did_hex>          - ReadDataByIdentifier, e.g. read 7e0 f190
  dtc <ecu>                     - ReadDTCInformation (report all by status mask)
  services <ecu>                - probe which UDS services are supported/locked
  raw <ecu> <hex bytes>         - send an arbitrary raw UDS request (advanced, use with care)
  snapshot <name> <ecu> <did_start_hex> <did_end_hex>
                                 - scan a DID range (0x22 reads only) and save
                                   the positive responses under <name>, e.g.
                                   snapshot locked 7d0 0100 01ff
  diff <name1> <name2>          - compare two snapshots, print DIDs whose
                                   response bytes changed (or appeared/vanished)
  snapshots                     - list saved snapshot names
  quit

Typical workflow to find e.g. the door-lock-state DID:
  uds> snapshot unlocked 7d0 0100 01ff
  (physically lock the doors)
  uds> snapshot locked 7d0 0100 01ff
  uds> diff unlocked locked
"""
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

KNOWN_ECUS = {
    "770": "unknown (91950-O6191, wiring/junction-related)",
    "780": "unknown",
    "796": "PDC/around-view? (99240-O6500)",
    "7a0": "transmission-adjacent? (95400-O6110)",
    "7b3": "HVAC/climate (97250-O6210)",
    "7b7": "rear radar/BSD? (99140-O6000)",
    "7c4": "Front camera / LKAS (99211-O6000)",
    "7c6": "Cluster/CLU (94013-O6000)",
    "7d0": "BCM/CCM (99110-O6000)",
    "7d1": "ABS/ESC (58900-O6810) - CAUTION, see README safety note",
    "7d2": "unknown, complex payload (95910-O6000)",
    "7d4": "MDPS/steering (56340-O6000) - CAUTION, see README safety note",
    "7e0": "ECM",
    "7e1": "TCM",
    "7f1": "unknown (acks tester present only)",
}

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

PROBE_SERVICES = [
    (0x10, "DiagnosticSessionControl"),
    (0x14, "ClearDiagnosticInformation"),
    (0x19, "ReadDTCInformation"),
    (0x22, "ReadDataByIdentifier"),
    (0x27, "SecurityAccess"),
    (0x28, "CommunicationControl"),
    (0x2E, "WriteDataByIdentifier"),
    (0x2F, "InputOutputControlByIdentifier"),
    (0x31, "RoutineControl"),
    (0x3E, "TesterPresent"),
]


def wait_for_device(retries=20, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


class Bus:
    def __init__(self):
        self.dev = wait_for_device()
        if self.dev is None:
            raise SystemExit("No gs_usb device found")
        self.dev.set_bitrate(500000)
        self.dev.start()

    def send(self, can_id, data):
        tx = GsUsbFrame()
        tx.can_id = can_id
        tx.can_dlc = 8
        tx.data = list(data) + [0xAA] * (8 - len(data))
        self.dev.send(tx)

    def read_one(self, timeout_ms=120):
        frame = GsUsbFrame()
        try:
            if self.dev.read(frame=frame, timeout_ms=timeout_ms):
                if frame.echo_id == GS_USB_NONE_ECHO_ID:
                    return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
        except Exception:
            pass
        return None, None

    def isotp_request(self, req_id, resp_id, data, tries=2, window=1.0):
        collected = None
        for _ in range(tries):
            self.send(req_id, data)
            end = time.time() + window
            collected = None
            expected_len = None
            while time.time() < end:
                aid, d = self.read_one(120)
                if aid is None or aid != resp_id:
                    continue
                frame_type = d[0] >> 4
                if frame_type == 0x0:
                    return d[1 : 1 + (d[0] & 0x0F)]
                elif frame_type == 0x1:
                    expected_len = ((d[0] & 0x0F) << 8) | d[1]
                    collected = list(d[2:8])
                    self.send(req_id, [0x30, 0x00, 0x00])
                elif frame_type == 0x2 and collected is not None:
                    collected.extend(d[1:8])
                    if len(collected) >= expected_len:
                        return collected[:expected_len]
            time.sleep(0.15)
        return collected

    def stop(self):
        self.dev.stop()


def as_text(data):
    if not data:
        return ""
    return bytes([b for b in data if 32 <= b < 127]).decode(errors="replace")


def parse_ecu(token):
    token = token.lower().replace("0x", "")
    try:
        req_id = int(token, 16)
    except ValueError:
        print(f"  invalid ECU id: {token}")
        return None
    return req_id


def describe_response(resp):
    if not resp:
        return "(no response)"
    if resp[0] == 0x7F and len(resp) >= 3:
        nrc = resp[2]
        name = NRC_NAMES.get(nrc, f"unknown NRC 0x{nrc:02X}")
        return f"NEGATIVE: service=0x{resp[1]:02X} NRC=0x{nrc:02X} ({name})"
    return f"positive: {resp}"


def cmd_list():
    print("Known ECUs (request ID -> guessed identity):")
    for req, desc in KNOWN_ECUS.items():
        print(f"  0x{req} : {desc}")


def cmd_scan(bus):
    print("Scanning 0x700-0x7FF with Tester Present...")
    found = []
    for req_id in range(0x700, 0x800):
        bus.send(req_id, [0x02, 0x3E, 0x00])
        end = time.time() + 0.1
        while time.time() < end:
            aid, d = bus.read_one(30)
            if aid == req_id + 8:
                found.append(req_id)
                print(f"  0x{req_id:03x} -> 0x{aid:03x}: {d}")
                break
    print(f"Found {len(found)} ECU(s).")


def cmd_read(bus, ecu_token, did_token):
    req_id = parse_ecu(ecu_token)
    if req_id is None:
        return
    try:
        did = int(did_token, 16)
    except ValueError:
        print(f"  invalid DID: {did_token}")
        return
    resp_id = req_id + 8
    resp = bus.isotp_request(req_id, resp_id, [0x03, 0x22, (did >> 8) & 0xFF, did & 0xFF])
    print(f"  {describe_response(resp)}")
    if resp and resp[0] != 0x7F:
        print(f"  as text: {as_text(resp[3:])}")


def cmd_dtc(bus, ecu_token):
    req_id = parse_ecu(ecu_token)
    if req_id is None:
        return
    resp_id = req_id + 8
    resp = bus.isotp_request(req_id, resp_id, [0x03, 0x19, 0x02, 0xFF])
    print(f"  {describe_response(resp)}")


def cmd_services(bus, ecu_token):
    req_id = parse_ecu(ecu_token)
    if req_id is None:
        return
    resp_id = req_id + 8
    print(f"Probing service support on 0x{req_id:03x} (minimal/malformed requests, no actuation)...")
    for sid, name in PROBE_SERVICES:
        if sid == 0x2F:
            # deliberately short/malformed - most stacks NRC (length or security)
            # before ever touching an actual output
            probe = [0x02, sid, 0x00]
        elif sid == 0x31:
            # requestRoutineResults (0x03) - reads status, does NOT start a routine
            probe = [0x04, sid, 0x03, 0x00, 0x00]
        elif sid == 0x27:
            probe = [0x02, sid, 0x01]  # request seed only, no key sent back
        else:
            probe = [0x02, sid, 0x00]
        resp = bus.isotp_request(req_id, resp_id, probe, tries=1, window=0.4)
        print(f"  0x{sid:02X} {name:35s}: {describe_response(resp)}")


def cmd_raw(bus, ecu_token, hex_bytes):
    req_id = parse_ecu(ecu_token)
    if req_id is None:
        return
    try:
        data = [int(b, 16) for b in hex_bytes.split()]
    except ValueError:
        print("  invalid hex bytes")
        return
    resp_id = req_id + 8
    print("  WARNING: raw command sends exactly what you type - use with care.")
    resp = bus.isotp_request(req_id, resp_id, [len(data)] + data)
    print(f"  {describe_response(resp)}")


def cmd_snapshot(bus, snapshots, name, ecu_token, did_start_token, did_end_token):
    req_id = parse_ecu(ecu_token)
    if req_id is None:
        return
    try:
        did_start = int(did_start_token, 16)
        did_end = int(did_end_token, 16)
    except ValueError:
        print("  invalid DID range")
        return
    resp_id = req_id + 8
    total = did_end - did_start + 1
    print(f"Scanning {total} DID(s) on 0x{req_id:03x}...")
    result = {}
    for i, did in enumerate(range(did_start, did_end + 1)):
        resp = bus.isotp_request(
            req_id, resp_id, [0x03, 0x22, (did >> 8) & 0xFF, did & 0xFF], tries=1, window=0.3
        )
        if resp and resp[0] != 0x7F:
            result[did] = resp
        if (i + 1) % 32 == 0:
            print(f"  {i + 1}/{total} scanned, {len(result)} positive so far")
    snapshots[name] = {"ecu": req_id, "data": result}
    print(f"Saved snapshot '{name}': {len(result)} DID(s) with positive response.")


def cmd_diff(snapshots, name1, name2):
    if name1 not in snapshots or name2 not in snapshots:
        print(f"  unknown snapshot name(s) - have: {list(snapshots.keys())}")
        return
    s1, s2 = snapshots[name1]["data"], snapshots[name2]["data"]
    all_dids = sorted(set(s1) | set(s2))
    changed = 0
    for did in all_dids:
        v1, v2 = s1.get(did), s2.get(did)
        if v1 != v2:
            changed += 1
            print(f"  DID 0x{did:04X}: {name1}={v1}  ->  {name2}={v2}")
    print(f"\n{changed} DID(s) differ out of {len(all_dids)} total seen across both snapshots.")


def main():
    print(__doc__)
    bus = Bus()
    snapshots = {}
    try:
        while True:
            try:
                line = input("uds> ").strip()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0].lower()
            if cmd in ("quit", "exit"):
                break
            elif cmd == "list":
                cmd_list()
            elif cmd == "scan":
                cmd_scan(bus)
            elif cmd == "read" and len(parts) == 3:
                cmd_read(bus, parts[1], parts[2])
            elif cmd == "dtc" and len(parts) == 2:
                cmd_dtc(bus, parts[1])
            elif cmd == "services" and len(parts) == 2:
                cmd_services(bus, parts[1])
            elif cmd == "raw" and len(parts) >= 3:
                cmd_raw(bus, parts[1], " ".join(parts[2:]))
            elif cmd == "snapshot" and len(parts) == 5:
                cmd_snapshot(bus, snapshots, parts[1], parts[2], parts[3], parts[4])
            elif cmd == "diff" and len(parts) == 3:
                cmd_diff(snapshots, parts[1], parts[2])
            elif cmd == "snapshots":
                print(f"  saved: {list(snapshots.keys())}")
            else:
                print("  unknown command or wrong arg count - see the header comment for usage")
    finally:
        bus.stop()


if __name__ == "__main__":
    main()

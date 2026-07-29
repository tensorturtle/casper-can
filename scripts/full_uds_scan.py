# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Full UDS module discovery + identification scan.

Two phases:
  1. Scan the full 0x700-0x7FF physical request ID range with UDS Tester
     Present (0x3E 0x00) to find every responding ECU. Hyundai/Kia chassis
     and body ECUs commonly live outside the standard OBD 0x7E0-0x7E7 range.
  2. For each discovered ECU, query identification DIDs (VIN, software
     version, part number, serial number) and DTCs.

SAFETY: this sends Diagnostic Session Control (extended session) to every
discovered ECU, including safety-critical ones (ABS/ESC, MDPS/steering).
Only run this parked, in P, with the parking brake and foot brake applied.
Never run against ABS/ESC or MDPS while the vehicle is in motion - forcing
an extended diagnostic session can briefly suspend their normal control
loop. On this Casper it triggered a transient "Check ESC" warning light
that cleared after ~2s - treat any warning that does NOT clear within a
few seconds as a reason to stop and cycle the ignition before driving.
"""
import json
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame


def wait_for_device(retries=20, delay=0.3):
    for _ in range(retries):
        devs = GsUsb.scan()
        if devs:
            return devs[0]
        time.sleep(delay)
    return None


def send(dev, can_id, data):
    tx = GsUsbFrame()
    tx.can_id = can_id
    tx.can_dlc = 8
    tx.data = list(data) + [0xAA] * (8 - len(data))
    dev.send(tx)


def read_one(dev, timeout_ms=150):
    frame = GsUsbFrame()
    try:
        if dev.read(frame=frame, timeout_ms=timeout_ms):
            if frame.echo_id == GS_USB_NONE_ECHO_ID:
                return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
    except Exception:
        pass
    return None, None


def listen(dev, duration=0.15):
    out = []
    end = time.time() + duration
    while time.time() < end:
        aid, d = read_one(dev, 40)
        if aid is not None:
            out.append((aid, d))
    return out


def isotp_request(dev, req_id, resp_id, data, tries=2, window=1.0):
    collected = None
    for _ in range(tries):
        send(dev, req_id, data)
        end = time.time() + window
        collected = None
        expected_len = None
        while time.time() < end:
            aid, d = read_one(dev, 120)
            if aid is None or aid != resp_id:
                continue
            frame_type = d[0] >> 4
            if frame_type == 0x0:  # single frame
                return d[1 : 1 + (d[0] & 0x0F)]
            elif frame_type == 0x1:  # first frame
                expected_len = ((d[0] & 0x0F) << 8) | d[1]
                collected = list(d[2:8])
                send(dev, req_id, [0x30, 0x00, 0x00])  # flow control: CTS
            elif frame_type == 0x2 and collected is not None:  # consecutive frame
                collected.extend(d[1:8])
                if len(collected) >= expected_len:
                    return collected[:expected_len]
        time.sleep(0.15)
    return collected


def as_text(data):
    if not data:
        return ""
    return bytes([b for b in data if 32 <= b < 127]).decode(errors="replace")


def discover_ecus(dev):
    found = []
    print("Scanning 0x700-0x7FF with Tester Present (0x3E 0x00)...")
    for req_id in range(0x700, 0x800):
        send(dev, req_id, [0x02, 0x3E, 0x00])
        resp = listen(dev, 0.12)
        real_resp = [(aid, d) for aid, d in resp if aid == req_id + 8]
        if real_resp:
            found.append(req_id)
            print(f"  found ECU: req={hex(req_id)} resp={hex(req_id + 8)}: {real_resp[0][1]}")
    return found


def identify_ecu(dev, req_id):
    resp_id = req_id + 8
    entry = {}
    entry["session_ctrl_resp"] = isotp_request(dev, req_id, resp_id, [0x02, 0x10, 0x03], tries=1, window=0.4)
    entry["dtc_raw"] = isotp_request(dev, req_id, resp_id, [0x03, 0x19, 0x02, 0xFF], tries=2, window=0.6)
    for did_name, did_bytes in [
        ("VIN_F190", [0xF1, 0x90]),
        ("SW_F1A0", [0xF1, 0xA0]),
        ("PARTNUM_F187", [0xF1, 0x87]),
        ("SERIAL_F18C", [0xF1, 0x8C]),
    ]:
        r = isotp_request(dev, req_id, resp_id, [0x03, 0x22] + did_bytes, tries=1, window=0.5)
        if r:
            entry[did_name] = {"raw": r, "text": as_text(r)}
    return entry


def main():
    dev = wait_for_device()
    if dev is None:
        raise SystemExit("No gs_usb device found")
    dev.set_bitrate(500000)
    dev.start()

    ecu_ids = discover_ecus(dev)
    print(f"\n{len(ecu_ids)} ECU(s) found. Identifying each...\n")

    results = {}
    for req_id in ecu_ids:
        entry = identify_ecu(dev, req_id)
        results[hex(req_id)] = entry
        print(f"=== {hex(req_id)} -> {hex(req_id + 8)} ===")
        for k, v in entry.items():
            print(f"  {k}: {v}")

    with open("full_scan_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nSaved to full_scan_results.json")

    dev.stop()


if __name__ == "__main__":
    main()

# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Scan a UDS DID range (ReadDataByIdentifier, 0x22) on one ECU and save
positive responses to a JSON snapshot file. Read-only.

Usage: uv run scripts/snapshot_did.py <name> <ecu_hex> <did_start_hex> <did_end_hex>
Example: uv run scripts/snapshot_did.py unlocked 7d0 0100 01ff
"""
import json
import platform
import sys
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


def read_one(dev, timeout_ms=120):
    frame = GsUsbFrame()
    try:
        if dev.read(frame=frame, timeout_ms=timeout_ms):
            if frame.echo_id == GS_USB_NONE_ECHO_ID:
                return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
    except Exception:
        pass
    return None, None


def isotp_request(dev, req_id, resp_id, data, tries=1, window=0.3):
    collected = None
    for _ in range(tries):
        send(dev, req_id, data)
        end = time.time() + window
        expected_len = None
        while time.time() < end:
            aid, d = read_one(dev, 100)
            if aid is None or aid != resp_id:
                continue
            frame_type = d[0] >> 4
            if frame_type == 0x0:
                return d[1 : 1 + (d[0] & 0x0F)]
            elif frame_type == 0x1:
                expected_len = ((d[0] & 0x0F) << 8) | d[1]
                collected = list(d[2:8])
                send(dev, req_id, [0x30, 0x00, 0x00])
            elif frame_type == 0x2 and collected is not None:
                collected.extend(d[1:8])
                if len(collected) >= expected_len:
                    return collected[:expected_len]
    return collected


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        raise SystemExit(1)
    name, ecu_token, did_start_token, did_end_token = sys.argv[1:5]
    req_id = int(ecu_token, 16)
    did_start = int(did_start_token, 16)
    did_end = int(did_end_token, 16)
    resp_id = req_id + 8

    dev = wait_for_device()
    if dev is None:
        raise SystemExit("No gs_usb device found")
    dev.set_bitrate(500000)
    dev.start()

    total = did_end - did_start + 1
    print(f"Scanning {total} DID(s) on 0x{req_id:03x}...")
    result = {}
    for i, did in enumerate(range(did_start, did_end + 1)):
        resp = isotp_request(dev, req_id, resp_id, [0x03, 0x22, (did >> 8) & 0xFF, did & 0xFF])
        if resp and resp[0] != 0x7F:
            result[str(did)] = resp
        if (i + 1) % 64 == 0:
            print(f"  {i + 1}/{total} scanned, {len(result)} positive so far")

    out_path = f"snapshot_{name}.json"
    with open(out_path, "w") as f:
        json.dump({"ecu": req_id, "did_range": [did_start, did_end], "data": result}, f, indent=2)
    print(f"Saved {len(result)} positive DID(s) to {out_path}")

    dev.stop()


if __name__ == "__main__":
    main()

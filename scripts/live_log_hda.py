# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "gs_usb",
#     "pyusb",
# ]
# ///
"""Live-drive logger for HDA-related active polling.

Continuously polls known DIDs on the front camera (0x7C4) and MDPS (0x7D4)
via ReadDataByIdentifier (0x22, default session, read-only - same safety
profile as the ECM PID polling already validated during a real drive).
Also polls ECM speed (Mode 01 PID 0x0D) as a reference for when the car is
moving fast enough for HDA to be active (disengages below 10km/h per the
car's spec).

Does NOT send Diagnostic Session Control to MDPS - see README.md Safety
Note. Plain reads only.

Usage: uv run scripts/live_log_hda.py
Writes hda_drive_log.csv - after the drive, correlate timestamps against
when you recall engaging/disengaging HDA.
"""
import csv
import platform
import time

if platform.system().lower() == "darwin":
    import usb.core

    usb.core.Device.is_kernel_driver_active = lambda self, intf: False

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GS_USB_NONE_ECHO_ID, GsUsbFrame

DURATION_SECONDS = 180
LOG_PATH = "hda_drive_log.csv"

CAMERA_REQ, CAMERA_RESP = 0x7C4, 0x7CC
MDPS_REQ, MDPS_RESP = 0x7D4, 0x7DC
ECM_REQ, ECM_RESP = 0x7E0, 0x7E8

CAMERA_DIDS = [0x0101, 0x0102, 0x0103, 0x0140]
MDPS_DIDS = [0x0101, 0x0102]


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


def read_one(dev, timeout_ms=80):
    frame = GsUsbFrame()
    try:
        if dev.read(frame=frame, timeout_ms=timeout_ms):
            if frame.echo_id == GS_USB_NONE_ECHO_ID:
                return frame.arbitration_id, list(frame.data)[: frame.can_dlc]
    except Exception:
        pass
    return None, None


def isotp_read(dev, req_id, resp_id, did, window=0.25):
    send(dev, req_id, [0x03, 0x22, (did >> 8) & 0xFF, did & 0xFF])
    end = time.time() + window
    collected = None
    expected_len = None
    while time.time() < end:
        aid, d = read_one(dev, 60)
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
    return None


def main():
    dev = wait_for_device()
    if dev is None:
        raise SystemExit("No gs_usb device found")
    dev.set_bitrate(500000)
    dev.start()

    print(f"Starting {DURATION_SECONDS}s HDA active-poll log. Drive now, engage HDA when ready.")
    log_rows = []
    start = time.time()
    last_status = 0

    while time.time() - start < DURATION_SECONDS:
        now = time.time()

        speed_resp = None
        send(dev, ECM_REQ, [0x02, 0x01, 0x0D])
        end = time.time() + 0.2
        while time.time() < end:
            aid, d = read_one(dev, 60)
            if aid == ECM_RESP and len(d) >= 4 and d[1] == 0x41 and d[2] == 0x0D:
                speed_resp = d[3]
                break
        if speed_resp is not None:
            log_rows.append([time.time(), "SPEED", "kmh", speed_resp])

        for did in CAMERA_DIDS:
            resp = isotp_read(dev, CAMERA_REQ, CAMERA_RESP, did)
            if resp:
                log_rows.append([time.time(), "CAMERA", hex(did), resp])

        for did in MDPS_DIDS:
            resp = isotp_read(dev, MDPS_REQ, MDPS_RESP, did)
            if resp:
                log_rows.append([time.time(), "MDPS", hex(did), resp])

        if now - last_status > 5:
            remaining = DURATION_SECONDS - (now - start)
            print(f"[{remaining:5.0f}s left] rows logged={len(log_rows)}")
            last_status = now

    with open(LOG_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["unix_time", "source", "did_or_unit", "value"])
        writer.writerows(log_rows)

    print(f"\nDone. Logged {len(log_rows)} rows to {LOG_PATH}")
    dev.stop()


if __name__ == "__main__":
    main()
